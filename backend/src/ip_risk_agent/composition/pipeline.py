"""Lease-aware Source -> Gate -> Intelligence -> Control worker pipeline."""

from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass
from enum import StrEnum

from iprisk_contracts import SourceSnapshot

from ip_risk_agent.application.public_facade import SourceAccessReceiptContext
from ip_risk_agent.application.repositories import RecordNotFoundError
from ip_risk_agent.connectors.common.errors import SourceConnectorError
from ip_risk_agent.intelligence.common.errors import IntelligenceError
from ip_risk_agent.core.common import DomainInvariantError

from .analyzer_completeness import AnalyzerCompletenessError

logger = logging.getLogger(__name__)

#: 우리 코드로 볼 경로 조각. 이 밖의 frame 은 라이브러리이므로 위치로 삼지 않는다.
_OUR_PACKAGE = "ip_risk_agent"


def failure_site(exc: BaseException) -> str | None:
    """예외가 터진 **우리 코드**의 위치를 ``module.py:12`` 로 돌려준다.

    예외 메시지와 인자는 사용자 값(문서 내용, 파일 이름, 토큰)을 담을 수 있어
    남길 수 없다. 그래서 클래스 이름만 남겼는데, ``AttributeError`` 하나만 보고
    수만 줄에서 위치를 찾는 것은 사실상 불가능했다.

    파일 이름과 줄 번호는 우리가 쓴 코드이고 사용자 값이 아니다. 라이브러리
    안쪽에서 터졌으면 그 호출부(우리 코드의 가장 안쪽 frame)를 준다 — 원인을
    좁히는 데 쓸모 있는 것은 그쪽이다.
    """
    frames = traceback.extract_tb(exc.__traceback__)
    ours = [frame for frame in frames if _OUR_PACKAGE in frame.filename.replace("\\", "/")]
    chosen = (ours or frames)[-1] if (ours or frames) else None
    if chosen is None:
        return None
    return f"{chosen.filename.replace(chr(92), '/').rsplit('/', 1)[-1]}:{chosen.lineno}"
from .providers import ProviderRegistryError, SourceAdapterRegistry


class PipelineDisposition(StrEnum):
    COMPLETED = "COMPLETED"
    DUPLICATE = "DUPLICATE"
    GATE_DENIED = "GATE_DENIED"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"


@dataclass(frozen=True, slots=True)
class PipelineResult:
    disposition: PipelineDisposition
    change_event_id: str
    analysis_job_id: str | None = None
    terminal_job_status: str | None = None
    safe_code: str | None = None


class RetryablePipelineError(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class InvalidPipelineTaskError(ValueError):
    pass


class AnalysisPipeline:
    def __init__(
        self,
        *,
        control_facade,
        adapters: SourceAdapterRegistry,
        intelligence,
        explanations=None,
    ) -> None:
        self._control = control_facade
        self._adapters = adapters
        self._intelligence = intelligence
        # 설명은 판정이 아니므로 없어도 파이프라인은 동작한다.
        self._explanations = explanations

    async def execute(
        self,
        change_event_id: str,
        *,
        allow_retry: bool = True,
    ) -> PipelineResult:
        try:
            claim = await self._control.claim_analysis(
                change_event_id,
                allow_retry=allow_retry,
            )
        except RecordNotFoundError as exc:
            raise InvalidPipelineTaskError("unknown change_event_id") from exc
        if claim is None:
            return PipelineResult(PipelineDisposition.DUPLICATE, change_event_id)

        adapter = None
        snapshot_fetched = False
        try:
            adapter = self._adapters.require(claim.source_change.source_type)
            snapshot = await adapter.fetch_snapshot(claim.source_change)
            snapshot_fetched = True
            _validate_snapshot(snapshot, claim.source_change)
            if snapshot.resolved_revision != claim.source_change.revision:
                # 이 실행이 맡은 개정과 지금 소스에 있는 개정이 다르다. 새 내용을
                # 옛 개정에 붙여 기록하면 이력이 어긋나므로 여기서 멈춘다.
                #
                # 버리는 것이 아니다. 소스가 앞서 나갔다는 것은 변경 감지가 곧
                # (또는 이미) 새 ChangeEvent 를 만든다는 뜻이고, 그쪽이 현재 개정을
                # 분석한다. 다시 시도해도 결과가 같으므로 retryable 이 아니다.
                #
                # 예전에는 이 상황이 한참 뒤 access receipt 검증에서
                # "source access analysis context is inconsistent" 로 터졌다.
                # 화면에는 뜻을 알 수 없는 실패만 남았다.
                result = await self._fail(
                    change_event_id,
                    claim.analysis_job_id,
                    claim.attempt,
                    safe_code="SOURCE:REVISION_SUPERSEDED",
                    retryable=False,
                )
                await _cleanup(adapter, claim.source_change)
                return result
            await self._control.register_source_access(
                SourceAccessReceiptContext(
                    risk_workspace_id=snapshot.risk_workspace_id,
                    mount_id=snapshot.mount_id,
                    source_workspace_id=snapshot.source_workspace_id,
                    source_type=snapshot.source_type,
                    source_artifact_id=snapshot.source_artifact_id,
                    revision=snapshot.resolved_revision,
                    receipt=snapshot.source_access_receipt,
                    analysis_job_id=claim.analysis_job_id,
                )
            )
            gated = await self._control.build_analysis_artifact(
                snapshot,
                claim.analysis_job_id,
            )
            del snapshot
            if not gated.approved:
                await _cleanup(adapter, claim.source_change)
                return PipelineResult(
                    PipelineDisposition.GATE_DENIED,
                    change_event_id,
                    claim.analysis_job_id,
                    safe_code=gated.denial_reason,
                )

            artifact = gated.analysis_artifact
            assert artifact is not None
            results = await self._intelligence.analyze(artifact)
            final_status: str | None = None
            explained: list[str] = []
            for result in results:
                receipt = await self._control.accept_analysis_result(result)
                final_status = receipt.job_status
                explained.extend(receipt.affected_risk_ids)
            # 설명은 판정이 아니다. 실패해도 분석 결과는 그대로 두고 넘어간다.
            if explained and self._explanations is not None:
                await self._explanations.explain_risks(tuple(explained))
            if final_status not in {"SUCCEEDED", "INCONCLUSIVE", "FAILED"}:
                raise AnalyzerCompletenessError(
                    "complete result set did not terminate the canonical analysis job"
                )
            await _cleanup(adapter, claim.source_change)
            return PipelineResult(
                PipelineDisposition.COMPLETED,
                change_event_id,
                claim.analysis_job_id,
                terminal_job_status=final_status,
            )
        except SourceConnectorError as exc:
            result = await self._fail(
                change_event_id,
                claim.analysis_job_id,
                claim.attempt,
                safe_code=f"SOURCE:{exc.category.value}",
                retryable=exc.retryable,
            )
            if snapshot_fetched:
                await _cleanup(adapter, claim.source_change)
            return result
        except ProviderRegistryError:
            return await self._fail(
                change_event_id,
                claim.analysis_job_id,
                claim.attempt,
                safe_code="CONFIGURATION:SOURCE_ADAPTER_MISSING",
                retryable=False,
            )
        except AnalyzerCompletenessError:
            result = await self._fail(
                change_event_id,
                claim.analysis_job_id,
                claim.attempt,
                safe_code="CONTRACT:ANALYZER_RESULT_SET_MISMATCH",
                retryable=False,
            )
            if snapshot_fetched:
                await _cleanup(adapter, claim.source_change)
            return result
        except IntelligenceError as exc:
            retryable = bool(getattr(exc, "retryable", False))
            category = getattr(exc, "category", None)
            category_value = getattr(category, "value", "INTELLIGENCE_ERROR")
            result = await self._fail(
                change_event_id,
                claim.analysis_job_id,
                claim.attempt,
                safe_code=f"INTELLIGENCE:{category_value}",
                retryable=retryable,
            )
            if snapshot_fetched:
                await _cleanup(adapter, claim.source_change)
            return result
        except DomainInvariantError as exc:
            result = await self._fail(
                change_event_id,
                claim.analysis_job_id,
                claim.attempt,
                safe_code="CONTRACT:CANONICAL_INTAKE_REJECTED",
                retryable=False,
                reason=getattr(exc, "safe_reason", None),
            )
            if snapshot_fetched:
                await _cleanup(adapter, claim.source_change)
            return result
        except Exception as exc:
            # 예외 **클래스 이름과 터진 위치**만 남긴다. 메시지·인자·지역변수는
            # 값을 담을 수 있어 남기지 않는다. 이름만으로도 분류는 되짚을 수
            # 있고, 그것이 없으면 배포에서 FAILED 만 보이고 원인을 좁힐 길이
            # 없다 — 앞서 CANONICAL_INTAKE_REJECTED 에서 같은 값을 치렀다.
            return await self._fail(
                change_event_id,
                claim.analysis_job_id,
                claim.attempt,
                safe_code="INTERNAL:UNEXPECTED_PIPELINE_FAILURE",
                retryable=True,
                reason=type(exc).__name__,
                site=failure_site(exc),
            )

    async def _fail(
        self,
        change_event_id: str,
        analysis_job_id: str,
        attempt: int,
        *,
        safe_code: str,
        retryable: bool,
        reason: object = None,
        site: str | None = None,
    ) -> PipelineResult:
        # 실패 코드는 canonical 기록에만 남아 있었다. 배포에서 화면은 FAILED 인데
        # 로그에는 아무것도 없어 분류를 되짚을 수 없었다. 코드는 개발자가 쓴
        # 상수이므로 그대로 남긴다.
        logger.info(
            json.dumps(
                {
                    "schema_version": 1,
                    "event": "analysis_pipeline_failed",
                    "analysis_job_id": analysis_job_id,
                    "event_id": change_event_id,
                    "failure_safe": safe_code,
                    "retryable": retryable,
                    # 어떤 불변조건이 깨졌는지. 상수 메시지를 보장하는 예외만
                    # safe_reason 을 내놓는다.
                    **(
                        {"failure_reason": str(reason)}
                        if isinstance(reason, str) and reason
                        else {}
                    ),
                    # 우리 코드 어디서 터졌는지. 파일 이름과 줄 번호는 개발자가
                    # 쓴 것이고 사용자 값이 아니다.
                    **({"failure_site": site} if site else {}),
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        await self._control.fail_analysis(
            change_event_id,
            failure_safe=safe_code,
            attempt=attempt,
        )
        if retryable:
            raise RetryablePipelineError(safe_code)
        return PipelineResult(
            PipelineDisposition.TERMINAL_FAILURE,
            change_event_id,
            analysis_job_id,
            terminal_job_status="FAILED",
            safe_code=safe_code,
        )


def _validate_snapshot(snapshot: SourceSnapshot, change) -> None:
    expected = (
        change.risk_workspace_id,
        change.mount_id,
        change.source_workspace_id,
        change.source_type,
        change.artifact.source_artifact_id,
    )
    received = (
        snapshot.risk_workspace_id,
        snapshot.mount_id,
        snapshot.source_workspace_id,
        snapshot.source_type,
        snapshot.source_artifact_id,
    )
    if received != expected:
        raise AnalyzerCompletenessError(
            "source snapshot identity does not match canonical SourceChange"
        )


async def _cleanup(adapter, change) -> None:
    cleanup = getattr(adapter, "cleanup", None)
    if cleanup is not None:
        try:
            await cleanup(change)
        except Exception:
            return


__all__ = [
    "AnalysisPipeline",
    "PipelineDisposition",
    "PipelineResult",
    "InvalidPipelineTaskError",
    "RetryablePipelineError",
]

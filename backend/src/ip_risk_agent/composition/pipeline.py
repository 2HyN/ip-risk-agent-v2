"""Lease-aware Source -> Gate -> Intelligence -> Control worker pipeline."""

from __future__ import annotations

import json
import logging
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
    def __init__(self, *, control_facade, adapters: SourceAdapterRegistry, intelligence) -> None:
        self._control = control_facade
        self._adapters = adapters
        self._intelligence = intelligence

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
            for result in results:
                receipt = await self._control.accept_analysis_result(result)
                final_status = receipt.job_status
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
        except DomainInvariantError:
            result = await self._fail(
                change_event_id,
                claim.analysis_job_id,
                claim.attempt,
                safe_code="CONTRACT:CANONICAL_INTAKE_REJECTED",
                retryable=False,
            )
            if snapshot_fetched:
                await _cleanup(adapter, claim.source_change)
            return result
        except Exception:
            return await self._fail(
                change_event_id,
                claim.analysis_job_id,
                claim.attempt,
                safe_code="INTERNAL:UNEXPECTED_PIPELINE_FAILURE",
                retryable=True,
            )

    async def _fail(
        self,
        change_event_id: str,
        analysis_job_id: str,
        attempt: int,
        *,
        safe_code: str,
        retryable: bool,
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

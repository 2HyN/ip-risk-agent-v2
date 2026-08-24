"""로컬 개발 전용 API — GCP 없이 화면을 띄운다.

**왜 이것이 필요한가.** 로컬(`APP_ENV=local`)은 in-memory 저장소로 잘 뜨지만
비어 있다. 그래서 Review 화면을 열면 "No risks detected" 만 나오고, UI 를 고쳐도
그 결과를 볼 수가 없다. 확인하려면 배포본에 로그인하는 수밖에 없었고, 그건 팀
프로젝트의 IAM 권한이 있는 사람만 할 수 있다. UI 작업이 배포 권한에 묶여 있던
셈이다. 이 스크립트가 그 매듭을 끊는다 — 표본 Risk 를 넣고, 구글 없이 로그인이
되게 한다.

**왜 제품 코드가 아니라 여기인가.** 로그인 우회는 운영에 있어서는 안 되는
물건이다. `ContainerOverrides.oidc_client` 는 이미 열려 있는 구멍(테스트가 쓰는
바로 그것)이라 앱을 고칠 필요가 없고, `scripts/` 는 Dockerfile 이 이미지로
복사하지 않으므로 이 파일은 배포물에 **실리지 않는다**. 우회로를 앱 안에 두고
환경변수로 잠그는 방식보다 이쪽이 안전하다 — 잠금을 잘못 풀 여지가 없다.

**무엇이 진짜가 아닌가.** 저장소는 메모리라 끄면 사라지고, 분석기·KIPRIS·RAG 는
붙어 있지 않다. 여기 보이는 Risk 는 전부 아래에 손으로 적은 표본이다. 화면과
상호작용을 보는 용도이지 분석 결과를 확인하는 용도가 아니다.

사용법 (저장소 루트에서):

    .venv/Scripts/python scripts/dev_local.py            # 8000 포트
    .venv/Scripts/python scripts/dev_local.py --port 8010

그리고 다른 터미널에서 `pnpm --filter @iprisk/frontend dev`.
8000 이 아닌 포트를 쓰면 프런트엔드에도 알려 준다:

    IPRISK_API_PROXY=http://127.0.0.1:8010 pnpm --filter @iprisk/frontend dev
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import uvicorn
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from iprisk_contracts import (
    AnalysisType,
    ChangeType,
    EvidenceType,
    ReviewPriority,
    SourceArtifactRef,
    SourceChange,
    SourceType,
)
from ip_risk_agent.application.analysis_jobs import AnalysisJob, AnalysisJobStatus
from ip_risk_agent.application.auth import GoogleOidcIdentity
from ip_risk_agent.application.process_change import ChangeEvent, ChangeEventStatus
from ip_risk_agent.application.repositories import InMemoryControlStore
from ip_risk_agent.composition.app import create_api_app
from ip_risk_agent.composition.container import ContainerOverrides, build_container
from ip_risk_agent.composition.runtime import configure_logging
from ip_risk_agent.composition.settings import Settings
from ip_risk_agent.core.artifacts import (
    Artifact,
    ArtifactAvailability,
    ArtifactState,
    ArtifactStatus,
)
from ip_risk_agent.core.auth import User, UserStatus
from ip_risk_agent.core.common import ActorType
from ip_risk_agent.core.memberships import (
    Membership,
    MembershipRole,
    MembershipStatus,
    membership_id_for,
)
from ip_risk_agent.core.mounts import (
    MountStatus,
    SourceConnection,
    SourceConnectionStatus,
    SourceWorkspace,
    SourceWorkspaceStatus,
    WorkspaceMount,
)
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskEvent,
    RiskEventType,
    RiskEvidence,
    RiskLifecycleState,
)
from ip_risk_agent.core.workspaces import RiskWorkspace, RiskWorkspaceStatus

NOW = datetime(2026, 8, 24, 4, 16, tzinfo=timezone.utc)

DEV_IDENTITY = GoogleOidcIdentity(
    subject="dev-local-subject",
    email="dev@localhost.invalid",
    email_verified=True,
    display_name="Local Developer",
)
USER_ID = "user-dev"
WORKSPACE_ID = "vws-dev"


class DevOidcClient:
    """구글을 거치지 않고 곧장 콜백으로 되돌린다.

    운영 클라이언트와 같은 Protocol 을 만족하므로 앱은 차이를 모른다. 로그인
    버튼을 누르면 구글 동의 화면 대신 콜백으로 튕겨 항상 같은 사람으로 들어온다.
    """

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response:
        return RedirectResponse(redirect_uri, status_code=302)

    async def fetch_identity(self, request: Request) -> GoogleOidcIdentity:
        return DEV_IDENTITY


def _settings(base_url: str) -> Settings:
    # os.environ 을 쓰지 않는다. 셸에 남은 운영 값이 섞여 들어오면 로컬이 로컬이
    # 아니게 된다 — 이 스크립트가 무엇으로 뜨는지는 이 표에만 적혀 있어야 한다.
    return Settings.from_env(
        {
            "APP_ROLE": "api",
            "APP_ENV": "local",
            "LOG_LEVEL": "INFO",
            "SESSION_SECRET": secrets.token_hex(32),
            # 로그인 뒤 돌아갈 곳은 백엔드가 아니라 Vite 다. Vite 가 /api 를
            # 백엔드로 넘겨 주므로 세션 쿠키도 한 출처에 모인다.
            "APP_PUBLIC_BASE_URL": base_url,
        }
    )


async def seed(store: InMemoryControlStore) -> None:
    """표본 Risk 를 넣는다.

    등급 넷(HIGH·INDETERMINATE·MEDIUM·LOW)과 분석 종류 둘(LICENSE·PATENT)을 모두
    덮는다 — UI 는 값마다 다르게 그리므로 한 종류만 넣으면 나머지를 못 본다.
    근거에는 구간(`quote_start`/`quote_end`)을 넣어 강조가 실제로 걸리게 한다.
    """
    async with store() as uow:
        await uow.users.add(
            User(
                id=USER_ID,
                google_subject=DEV_IDENTITY.subject,
                email=DEV_IDENTITY.email,
                display_name=DEV_IDENTITY.display_name,
                created_at=NOW,
                last_login_at=NOW,
                status=UserStatus.ACTIVE,
            )
        )
        await uow.workspaces.add(
            RiskWorkspace(
                id=WORKSPACE_ID,
                name="Local dev workspace",
                owner_user_id=USER_ID,
                security_policy_version="security-v1",
                retention_policy_version="retention-v1",
                created_at=NOW,
                updated_at=NOW,
                status=RiskWorkspaceStatus.ACTIVE,
            )
        )
        await uow.memberships.add(
            Membership(
                # 멤버십 id 는 임의로 못 짓는다 — 조회가 (workspace, user) 에서
                # 파생한 이 키로만 이뤄져서, 다른 id 로 넣으면 목록에는 나오는데
                # 권한 판정에서는 "회원이 아님" 이 된다.
                id=membership_id_for(WORKSPACE_ID, USER_ID),
                risk_workspace_id=WORKSPACE_ID,
                user_id=USER_ID,
                role=MembershipRole.OWNER,
                status=MembershipStatus.ACTIVE,
                invited_by=USER_ID,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await uow.source_metadata.add_connection(
            SourceConnection(
                id="connection-dev",
                provider=SourceType.GITHUB,
                authorized_by_user_id=USER_ID,
                status=SourceConnectionStatus.ACTIVE,
                created_at=NOW,
                updated_at=NOW,
                provider_account_label="local-dev",
            )
        )
        await uow.source_metadata.add_source_workspace(
            SourceWorkspace(
                id="source-dev",
                source_connection_id="connection-dev",
                source_type=SourceType.GITHUB,
                external_scope_id="local/dev-repo",
                display_name="dev-repo",
                status=SourceWorkspaceStatus.ACTIVE,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await uow.mounts.add(
            WorkspaceMount(
                id="mount-dev",
                risk_workspace_id=WORKSPACE_ID,
                source_workspace_id="source-dev",
                alias="dev-repo",
                mounted_by_user_id=USER_ID,
                source_connection_id="connection-dev",
                status=MountStatus.ACTIVE,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for spec in _RISK_SPECS:
            await _add_risk(uow, spec)
        await uow.commit()


async def _add_risk(uow, spec: dict) -> None:
    artifact_id = f"artifact-{spec['key']}"
    revision = f"revision-{spec['key']}"
    if await uow.artifacts.get(artifact_id) is None:
        artifact = Artifact(
            id=artifact_id,
            risk_workspace_id=WORKSPACE_ID,
            mount_id="mount-dev",
            source_workspace_id="source-dev",
            source_type=SourceType.GITHUB,
            source_artifact_id=spec["path"],
            display_name=spec["path"].rsplit("/", 1)[-1],
            logical_path=spec["path"],
            status=ArtifactStatus.ACTIVE,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        await uow.artifacts.add(
            artifact,
            ArtifactState(
                artifact_id=artifact_id,
                latest_revision=revision,
                latest_checksum=None,
                availability_state=ArtifactAvailability.AVAILABLE,
                updated_at=NOW,
            ),
        )
        await uow.change_events.add(
            ChangeEvent(
                id=f"change-{spec['key']}",
                event_fingerprint=f"fingerprint-{spec['key']}",
                risk_workspace_id=WORKSPACE_ID,
                mount_id="mount-dev",
                source_workspace_id="source-dev",
                source_artifact_id=spec["path"],
                source_type=SourceType.GITHUB,
                change_type=ChangeType.CREATE,
                revision=revision,
                previous_revision=None,
                observed_at=NOW,
                status=ChangeEventStatus.PENDING,
                attempts=0,
                created_at=NOW,
                updated_at=NOW,
                source_change=SourceChange(
                    contract_version="1",
                    event_id=f"provider-event-{spec['key']}",
                    event_fingerprint=f"fingerprint-{spec['key']}",
                    risk_workspace_id=WORKSPACE_ID,
                    mount_id="mount-dev",
                    source_workspace_id="source-dev",
                    source_type=SourceType.GITHUB,
                    artifact=SourceArtifactRef(
                        source_artifact_id=spec["path"],
                        display_name=spec["path"].rsplit("/", 1)[-1],
                    ),
                    change_type=ChangeType.CREATE,
                    revision=revision,
                    observed_at=NOW,
                    safe_metadata={},
                ),
                artifact_id=artifact_id,
            )
        )
        await uow.analysis_jobs.add(
            AnalysisJob(
                id=f"job-{spec['key']}",
                change_event_id=f"change-{spec['key']}",
                artifact_id=artifact_id,
                revision=revision,
                requested_analysis_types=(spec["analysis_type"],),
                status=AnalysisJobStatus.SUCCEEDED,
                created_at=NOW,
                # 끝난 작업은 시작·완료 시각을 요구한다 (도메인 불변식).
                started_at=NOW,
                completed_at=NOW + timedelta(minutes=1),
            )
        )
    risk_id = f"risk-{spec['key']}-{spec['index']}"
    await uow.risks.add(
        Risk(
            id=risk_id,
            risk_workspace_id=WORKSPACE_ID,
            artifact_id=artifact_id,
            analysis_type=spec["analysis_type"],
            risk_key=risk_id,
            lifecycle_state=spec.get("lifecycle", RiskLifecycleState.NEW),
            review_disposition=spec.get("disposition", ReviewDisposition.UNREVIEWED),
            review_priority=spec["priority"],
            summary=spec["summary"],
            first_seen_at=NOW,
            last_seen_at=NOW + timedelta(minutes=1),
            latest_analysis_job_id=f"job-{spec['key']}",
            updated_at=NOW + timedelta(minutes=1),
            latest_evidence_revision=f"revision-{spec['key']}",
            explanation_safe=spec.get("explanation"),
            recommendation_safe=spec.get("recommendation"),
        )
    )
    await uow.risks.append_event(
        RiskEvent(
            id=f"event-{risk_id}",
            risk_id=risk_id,
            event_type=RiskEventType.DETECTED,
            actor_type=ActorType.SYSTEM,
            occurred_at=NOW,
        )
    )
    for order, evidence in enumerate(spec.get("evidence", ())):
        await uow.risks.add_evidence(
            RiskEvidence(
                id=f"evidence-{risk_id}-{order}",
                risk_id=risk_id,
                analysis_job_id=f"job-{spec['key']}",
                evidence_id_from_result=f"result-{order}",
                evidence_type=evidence["type"],
                excerpt=evidence["excerpt"],
                reference=evidence["reference"],
                source_revision=f"revision-{spec['key']}",
                created_at=NOW,
                metadata_safe=evidence.get("metadata", {}),
            )
        )


def _span(excerpt: str, quote: str) -> dict:
    start = excerpt.index(quote)
    return {"quote_start": start, "quote_end": start + len(quote)}


_GPL_EXCERPT = (
    "GNU General Public License version 3.0 (GPLv3) / 배포시 의무사항\n"
    "각 복제본에 저작권 고지와 보증책임이 없음을 명시. 프로그램을 양도 받는 모든 이들에게 "
    "프로그램과 함께 GPL 라이선스 사본 제공. 수정시 수정사실 및 일시를 명시. "
    "원본저작물과 파생저작물을 GPL3.0에 의해 배포. 원본저작물 및 파생저작물에 대한 "
    "소스코드를 제공하거나, 요청시 제공하겠다는 약정서 제공. 사용자제품에 대한 인증키 등 "
    "설치정보의 제공. 차별적인 특허라이선스 계약체결의 금지.\n"
    "동적 링크로 분리한 경우에 한해 소스코드 제공없이 배포 가능한지는 별도 검토가 필요하다."
)

_PLAN_EXCERPT = (
    "# 스마트팜 작물 생육 예측 서비스 기획서\n\n"
    "## 해결 방식\n"
    "1. 비닐하우스에 설치된 카메라가 작물 이미지를 주기적으로 촬영한다.\n"
    "2. 온습도·조도 센서 값을 함께 수집한다.\n"
    "3. 딥러닝 모델이 이미지에서 병해 징후와 생육 단계를 판별한다."
)

_PATENT_EXCERPT = (
    "PURPOSE: A system and a method for observing growth of crops are provided to quickly "
    "collect crops growth information from a remote place. CONSTITUTION: The cameras(10-30) "
    "capture the growth of the crops in day and night. An AWS(Automatic Weather System)(40) "
    "measures a wind direction/speed, a sunshine duration/intensity, temperature, humidity, "
    "and rainfall of an area including the camera."
)

_MIT_EXCERPT = (
    "MIT License / 배포시 의무사항\n"
    "취득한 모든 사람에게 소프트웨어를 무제한으로 사용·복제·수정·병합·게시·배포하고 "
    "재실시권을 허여할 권리를 허용한다. 다만 위 저작권 고지와 본 허가 고지를 "
    "소프트웨어의 모든 복제본 또는 중요한 부분에 포함해야 한다.\n"
    "파생저작물을 독점 형태로 배포 가능하며 별도의 상호주의 조건은 없다."
)

_APACHE_EXCERPT = (
    "Apache License 2.0 / 배포시 의무사항\n"
    "저작권·특허·상표·귀속 고지를 보존해야 한다. 수정한 파일에는 변경 사실을 명시하며, "
    "NOTICE 파일이 있으면 파생저작물에도 포함해야 한다.\n"
    "기여자는 특허 실시권을 허여하되 특허 소송을 제기하면 그 실시권이 종료된다. "
    "상호주의(copyleft) 조건은 없어 독점 배포 가능하다."
)

_LGPL_EXCERPT = (
    "GNU Lesser General Public License 2.1 / 배포시 의무사항\n"
    "라이브러리를 동적 링크로 쓰는 경우 응용프로그램 자체는 독점으로 둘 수 있으나, "
    "라이브러리를 수정했다면 그 수정본의 소스코드를 제공해야 한다. 이용자가 "
    "라이브러리를 교체할 수 있도록 재링크 수단을 제공할 의무가 있다.\n"
    "정적 링크로 결합하면 응용프로그램 전체가 동일한 라이선스의 적용을 받을 수 있다."
)


def _license_evidence(excerpt: str, quote: str, reference: str) -> dict:
    return {
        "type": EvidenceType.LICENSE_REFERENCE,
        "excerpt": excerpt,
        "reference": reference,
        "metadata": _span(excerpt, quote),
    }


_RISK_SPECS: tuple[dict, ...] = (
    {
        "key": "gpl",
        "index": 1,
        "path": "src/vendor/gpl_helper.c",
        "analysis_type": AnalysisType.LICENSE,
        "priority": ReviewPriority.HIGH,
        "summary": "src/vendor/gpl_helper.c — GPL-3.0-or-later",
        "explanation": (
            "GPL-3.0-or-later 라이선스는 원본저작물과 파생저작물을 동일한 라이선스로 "
            "배포해야 하며, 소스코드를 제공할 의무가 있습니다. 현재 독점(PROPRIETARY) "
            "배포 형태의 프로젝트 소스트리에 해당 코드가 직접 포함되어 있어 라이선스 "
            "전파 위험이 존재합니다."
        ),
        "recommendation": (
            "해당 GPL 코드를 제거하고 대체 가능한 허용적 라이선스(MIT, Apache 등)의 "
            "라이브러리를 찾습니다. 분리하여 별도 프로세스로 실행하거나 동적 링크 구조로 "
            "바꿀 수 있는지 검토합니다. 소스코드 공개가 불가능한 경우 해당 모듈의 사용을 "
            "중단합니다."
        ),
        "evidence": (
            {
                "type": EvidenceType.LICENSE_REFERENCE,
                "excerpt": _GPL_EXCERPT,
                "reference": "SPDX GPL-3.0-or-later",
                "metadata": _span(_GPL_EXCERPT, "소스코드를 제공하거나"),
            },
            {
                "type": EvidenceType.SOURCE_EXCERPT,
                "excerpt": (
                    "/* SPDX-License-Identifier: GPL-3.0-or-later */\n"
                    "static int gpl_helper_init(void) { return 0; }"
                ),
                "reference": "src/vendor/gpl_helper.c#L1-L2",
            },
        ),
    },
    {
        "key": "plan",
        "index": 1,
        "path": "docs/서비스기획서.md",
        "analysis_type": AnalysisType.PATENT,
        "priority": ReviewPriority.MEDIUM,
        "summary": "docs/서비스기획서.md ~ 1020050035886",
        "explanation": (
            "기획서 아이디어가 선행 특허 1020050035886 과 기술 구성이 겹칩니다. "
            "변리사 조사가 필요합니다. 침해 판정이 아니며 초록만 대조했습니다."
        ),
        "evidence": (
            {
                "type": EvidenceType.SOURCE_EXCERPT,
                "excerpt": _PLAN_EXCERPT,
                "reference": "docs/서비스기획서.md#seg-2",
                "metadata": _span(
                    _PLAN_EXCERPT,
                    "비닐하우스에 설치된 카메라가 작물 이미지를 주기적으로 촬영한다",
                ),
            },
            {
                "type": EvidenceType.PATENT_ABSTRACT,
                "excerpt": _PATENT_EXCERPT,
                "reference": "KIPRIS Plus 출원번호 1020050035886",
                "metadata": _span(
                    _PATENT_EXCERPT,
                    "The cameras(10-30) capture the growth of the crops in day and night.",
                ),
            },
        ),
    },
    {
        "key": "package",
        "index": 1,
        "path": "license/package.json",
        "analysis_type": AnalysisType.LICENSE,
        "priority": ReviewPriority.INDETERMINATE,
        "summary": "npm:express@4.19.2 — MIT",
        "explanation": (
            "배포 형태 축이 정해지지 않아 등급을 확정하지 못했습니다. 허용적 "
            "라이선스이나 고지 의무는 남습니다."
        ),
        "evidence": (
            {
                "type": EvidenceType.PACKAGE_METADATA,
                "excerpt": '{"name": "express", "version": "4.19.2", "license": "MIT"}',
                "reference": "deps.dev npm/express/4.19.2",
            },
            _license_evidence(
                _MIT_EXCERPT,
                "위 저작권 고지와 본 허가 고지를",
                "SPDX MIT",
            ),
        ),
    },
    {
        "key": "package",
        "index": 2,
        "path": "license/package.json",
        "analysis_type": AnalysisType.LICENSE,
        "priority": ReviewPriority.INDETERMINATE,
        "summary": "npm:typescript@5.9.3 — APACHE-2.0",
        "evidence": (
            {
                "type": EvidenceType.PACKAGE_METADATA,
                "excerpt": '{"name": "typescript", "version": "5.9.3", "license": "Apache-2.0"}',
                "reference": "deps.dev npm/typescript/5.9.3",
            },
            _license_evidence(
                _APACHE_EXCERPT,
                "수정한 파일에는 변경 사실을 명시하며",
                "SPDX Apache-2.0",
            ),
        ),
    },
    {
        "key": "package",
        "index": 3,
        "path": "license/package.json",
        "analysis_type": AnalysisType.LICENSE,
        "priority": ReviewPriority.LOW,
        "summary": "npm:lodash@4.17.21 — MIT",
        "lifecycle": RiskLifecycleState.EXISTING,
        "disposition": ReviewDisposition.MONITORING,
        "evidence": (
            {
                "type": EvidenceType.PACKAGE_METADATA,
                "excerpt": '{"name": "lodash", "version": "4.17.21", "license": "MIT"}',
                "reference": "deps.dev npm/lodash/4.17.21",
            },
            _license_evidence(
                _MIT_EXCERPT,
                "위 저작권 고지와 본 허가 고지를",
                "SPDX MIT",
            ),
        ),
    },
    {
        # MEDIUM 을 라이선스에도 하나 둔다. 이것이 없으면 주황색 낱말 강조를
        # 라이선스 본문에서 볼 수가 없다 — MEDIUM 이 특허에만 있었기 때문이다.
        "key": "lgpl",
        "index": 1,
        "path": "src/vendor/liblgpl.so",
        "analysis_type": AnalysisType.LICENSE,
        "priority": ReviewPriority.MEDIUM,
        "summary": "src/vendor/liblgpl.so — LGPL-2.1-only",
        "explanation": (
            "동적 링크로 쓰는 한 응용프로그램은 독점으로 둘 수 있으나, 라이브러리를 "
            "수정했다면 그 수정본의 소스코드를 제공해야 합니다. 현재 링크 방식이 "
            "확인되지 않아 정적 결합 여부를 먼저 봐야 합니다."
        ),
        "recommendation": (
            "빌드 산출물에서 링크 방식을 확인합니다. 정적 결합이라면 동적 링크로 바꾸거나 "
            "재링크 수단을 함께 배포합니다. 라이브러리를 수정했다면 그 수정본의 소스코드를 "
            "제공할 의무가 생깁니다."
        ),
        "evidence": (
            _license_evidence(
                _LGPL_EXCERPT,
                "그 수정본의 소스코드를 제공해야 한다",
                "SPDX LGPL-2.1-only",
            ),
            {
                "type": EvidenceType.PACKAGE_METADATA,
                "excerpt": '{"name": "liblgpl", "version": "2.4.1", "license": "LGPL-2.1-only"}',
                "reference": "deps.dev generic/liblgpl/2.4.1",
            },
        ),
    },
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--frontend-origin",
        default="http://localhost:5173",
        help="로그인 뒤 돌아갈 곳. Vite dev 서버의 주소다.",
    )
    args = parser.parse_args()

    settings = _settings(args.frontend_origin)
    configure_logging(settings.log_level)
    store = InMemoryControlStore()
    asyncio.run(seed(store))
    app = create_api_app(
        build_container(
            settings,
            overrides=ContainerOverrides(
                unit_of_work_factory=store,
                oidc_client=DevOidcClient(),
            ),
        )
    )
    print(
        f"\n  dev API   http://127.0.0.1:{args.port}"
        f"\n  화면      {args.frontend_origin}"
        f"\n  로그인    구글을 거치지 않고 {DEV_IDENTITY.email} 로 바로 들어간다"
        f"\n  데이터    표본 Risk {len(_RISK_SPECS)}건 (메모리 — 끄면 사라진다)\n"
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

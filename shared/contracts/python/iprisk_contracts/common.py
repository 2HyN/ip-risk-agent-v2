"""Supporting types for the frozen version 1 shared contracts."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

SafeMetadata = dict[str, JsonValue]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveLineNumber = Annotated[int, Field(ge=1)]


class StrictModel(BaseModel):
    """Strict, JSON-serializable base for all shared value models."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceType(str, Enum):
    GOOGLE_DRIVE = "GOOGLE_DRIVE"
    GITHUB = "GITHUB"
    LOCAL = "LOCAL"


class ChangeType(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    MOVE = "MOVE"


class ArtifactKind(str, Enum):
    TEXT = "TEXT"
    SOURCE_CODE = "SOURCE_CODE"
    MANIFEST = "MANIFEST"
    LOCKFILE = "LOCKFILE"
    DOCUMENT_TEXT = "DOCUMENT_TEXT"
    UNKNOWN = "UNKNOWN"


class ContentScope(str, Enum):
    FULL_TEXT = "FULL_TEXT"
    CHANGESET_WITH_CONTEXT = "CHANGESET_WITH_CONTEXT"
    METADATA_ONLY = "METADATA_ONLY"
    UNSUPPORTED = "UNSUPPORTED"


class SegmentKind(str, Enum):
    FULL = "FULL"
    CHANGED = "CHANGED"
    CONTEXT = "CONTEXT"


class SourceAccessType(str, Enum):
    METADATA = "METADATA"
    DIFF = "DIFF"
    PARTIAL_CONTENT = "PARTIAL_CONTENT"
    FULL_CONTENT = "FULL_CONTENT"


class AnalysisType(str, Enum):
    PATENT = "PATENT"
    LICENSE = "LICENSE"


class AnalysisStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    SKIPPED = "SKIPPED"


class AnalysisCoverage(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NONE = "NONE"


class OriginalSourceType(str, Enum):
    PROVIDER_URL = "PROVIDER_URL"
    LOCAL_DEVICE = "LOCAL_DEVICE"
    UNAVAILABLE = "UNAVAILABLE"


class SourceHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


class EvidenceType(str, Enum):
    SOURCE_EXCERPT = "SOURCE_EXCERPT"
    PATENT_CLAIM = "PATENT_CLAIM"
    PATENT_ABSTRACT = "PATENT_ABSTRACT"
    LICENSE_REFERENCE = "LICENSE_REFERENCE"
    RAG_REFERENCE = "RAG_REFERENCE"
    PACKAGE_METADATA = "PACKAGE_METADATA"


class ReviewPriority(str, Enum):
    """검토 순서. 앞의 셋은 **심각도**이고 마지막 하나는 **판정 여부**다.

    ``INDETERMINATE`` 를 따로 두는 이유가 있다. ``HIGH`` 는 "심각하다" 이고 이 값은
    "판정을 못 내렸다" 라 축이 다르다. 둘을 한 칸에 넣으면 어느 쪽으로 넣어도 틀린다 —
    분류하지 않은 라이선스를 ``MEDIUM`` 에 두면 **강한 copyleft 가 중간으로 묻히고**,
    ``HIGH`` 에 두면 폰트 라이선스가 AGPL 과 같은 칸에 앉는다.

    원장에 남는 값이기도 하다. "그때 우리가 뭐라고 판단했나" 를 되짚을 때 "모르겠다" 가
    ``HIGH`` 로 적혀 있으면 이력이 거짓말을 한다.

    순서는 ``HIGH`` 바로 아래다. 진짜 심각한 것이 먼저 보이고, 그다음이 "모르겠으니 봐
    달라" 다.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    #: 판정을 내리지 못했다 — 분류하지 않은 라이선스, 일부만 본 결과, 조회 실패.
    INDETERMINATE = "INDETERMINATE"
    HIGH = "HIGH"


class LicensePolicyOutcome(str, Enum):
    NO_ACTION = "NO_ACTION"
    NOTICE_REQUIRED = "NOTICE_REQUIRED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    POLICY_CONFLICT = "POLICY_CONFLICT"
    UNKNOWN = "UNKNOWN"


class TextSegment(StrictModel):
    segment_id: str
    text: str
    line_start: PositiveLineNumber | None = None
    line_end: PositiveLineNumber | None = None
    segment_kind: SegmentKind

    @model_validator(mode="after")
    def validate_line_range(self) -> "TextSegment":
        if self.line_end is not None and self.line_start is None:
            raise ValueError("line_end requires line_start")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class SourceArtifactRef(StrictModel):
    source_artifact_id: str
    display_name: str
    path_hint: str | None = None


class MountRef(StrictModel):
    risk_workspace_id: str
    mount_id: str
    source_workspace_id: str
    source_type: SourceType


class SourceHealth(StrictModel):
    status: SourceHealthStatus
    checked_at: AwareDatetime
    safe_metadata: SafeMetadata


class OriginalSourceLocator(StrictModel):
    original_source_type: OriginalSourceType
    provider_url: str | None = None
    device_id: str | None = None
    source_artifact_id: str | None = None
    metadata_safe: SafeMetadata

    @model_validator(mode="after")
    def validate_locator(self) -> "OriginalSourceLocator":
        if self.original_source_type is OriginalSourceType.PROVIDER_URL:
            if not self.provider_url or self.device_id is not None:
                raise ValueError("PROVIDER_URL requires provider_url only")
        elif self.original_source_type is OriginalSourceType.LOCAL_DEVICE:
            if not self.device_id or not self.source_artifact_id or self.provider_url is not None:
                raise ValueError("LOCAL_DEVICE requires device_id and source_artifact_id")
        elif any((self.provider_url, self.device_id, self.source_artifact_id)):
            raise ValueError("UNAVAILABLE cannot expose a source locator")
        return self


class SourceAccessReceipt(StrictModel):
    access_type: SourceAccessType
    provider_request_id: str | None = None
    content_bytes: NonNegativeInt
    occurred_at: AwareDatetime


class AnalysisSecurityContext(StrictModel):
    approved: bool
    policy_version: str
    redaction_count: NonNegativeInt
    original_checksum: str
    analysis_input_checksum: str


class Evidence(StrictModel):
    evidence_id: str
    evidence_type: EvidenceType
    excerpt: str
    reference: str
    metadata_safe: SafeMetadata


class ProviderFailure(StrictModel):
    provider: str
    category: str
    retryable: bool
    safe_message: str


class AnalysisVersions(StrictModel):
    analyzer_version: str
    model_id: str | None = None
    prompt_version: str | None = None
    policy_version: str | None = None
    rag_corpus_version: str | None = None


class PatentCandidate(StrictModel):
    normalized_application_number: str
    title: str
    suggested_review_priority: ReviewPriority
    matched_elements: list[str]
    evidence_ids: list[str]
    provider_metadata_safe: SafeMetadata


class LicenseCandidate(StrictModel):
    ecosystem: str
    normalized_package_name: str
    resolved_version: str | None = None
    normalized_license_expression: str
    policy_outcome: LicensePolicyOutcome
    evidence_ids: list[str]
    uncertainty_flags: list[str]


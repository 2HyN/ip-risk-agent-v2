"""Risk Intelligence Plane 의 유일한 공개 접점.

Integration Layer 는 이 파일만 import 한다 (Agent 3 Spec 3). 내부 모듈 구조가 바뀌어도
조립 코드는 그대로여야 한다.

이 plane 은 Source Provider 를 호출하지 않고 Risk 상태를 만들지 않는다.
승인된 ``AnalysisArtifact`` 를 받아 ``AnalysisResult`` 를 돌려주는 것이 전부다.
"""

from __future__ import annotations

from dataclasses import dataclass

from iprisk_contracts import AnalysisArtifact, AnalysisResult, AnalysisType

from .common.analyzer import Analyzer
from .common.errors import (
    ArtifactRejectedError,
    FailureCategory,
    IntelligenceError,
    ProviderFailureError,
)
from .common.registry import AnalyzerRegistry
from .gemini.client import GoogleGenAIClient, PromptLibrary, StructuredModelClient
from .license.analyzer import LicenseAnalyzer
from .license.explanation import LicenseExplainer, ReferenceRetriever
from .license.package_metadata import (
    HttpPackageMetadataProvider,
    PackageMetadataProvider,
)
from .patent.analyzer import PatentAnalyzer
from .patent.kipris import KiprisClient, PatentSearchProvider

__all__ = [
    "Analyzer",
    "AnalyzerRegistry",
    "ArtifactRejectedError",
    "FailureCategory",
    "IntelligenceConfig",
    "IntelligenceError",
    "IntelligenceFacade",
    "ProviderFailureError",
    "create_analyzer_registry",
    "create_facade_from_env",
]


@dataclass(frozen=True)
class IntelligenceConfig:
    """이 plane 이 필요로 하는 설정.

    값은 Integration 이 환경변수에서 읽어 넘긴다. 여기서 직접 읽지 않는다.
    """

    gemini_model_id: str
    gemini_api_key: str | None = None
    vertex_config: dict[str, str] | None = None
    kipris_access_key: str | None = None
    patent_candidate_cap: int = 6

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "IntelligenceConfig":
        model_id = env.get("GEMINI_MODEL_ID")
        if not model_id:
            raise ValueError("GEMINI_MODEL_ID is required")
        return cls(
            gemini_model_id=model_id,
            gemini_api_key=env.get("GEMINI_API_KEY"),
            kipris_access_key=env.get("KIPRIS_ACCESS_KEY"),
        )


class IntelligenceFacade:
    """Integration 이 호출하는 단일 진입점."""

    def __init__(self, registry: AnalyzerRegistry, *, risk_explainer=None) -> None:
        self._registry = registry
        # Risk 설명기는 분석기가 아니다. 이미 판정이 끝난 Risk 에 설명을 붙이는
        # 것이므로 registry 밖에 둔다. Integration 이 여기서 꺼내 쓴다.
        self.risk_explainer = risk_explainer

    async def analyze(self, artifact: AnalysisArtifact) -> list[AnalysisResult]:
        """요청된 Analyzer 를 모두 실행한다.

        하나의 artifact 에 PATENT 와 LICENSE 가 함께 요청될 수 있으므로 결과는 목록이다.
        요청되었으나 다룰 수 없는 종류는 결과에 나타나지 않는다.
        """
        return await self._registry.analyze(artifact)

    def supports(self, artifact: AnalysisArtifact) -> bool:
        return bool(self._registry.selected(artifact))

    @property
    def active_analysis_types(self) -> tuple[AnalysisType, ...]:
        return self._registry.analysis_types


def create_analyzer_registry(
    *,
    metadata_provider: PackageMetadataProvider,
    model_client: StructuredModelClient,
    search_provider: PatentSearchProvider | None = None,
    retriever: ReferenceRetriever | None = None,
    explainer: LicenseExplainer | None = None,
    prompts: PromptLibrary | None = None,
    patent_candidate_cap: int = 6,
    patent_response_cache=None,
    previously_matched_patents=None,
) -> AnalyzerRegistry:
    """Analyzer 를 조립한다.

    provider 를 전부 인자로 받는다. 테스트는 대역을 넣고 배포는 실제 구현을 넣는다.
    특허 검색기를 넣지 않으면 라이선스만 등록된다.
    """
    analyzers: list[Analyzer] = [
        LicenseAnalyzer(metadata_provider, retriever=retriever, explainer=explainer)
    ]
    if search_provider is not None:
        analyzers.append(
            PatentAnalyzer(
                search_provider,
                model_client,
                prompts=prompts,
                candidate_cap=patent_candidate_cap,
                response_cache=patent_response_cache,
                previously_matched=previously_matched_patents,
            )
        )
    return AnalyzerRegistry(analyzers)


def create_facade_from_env(
    env: dict[str, str],
    *,
    retriever: ReferenceRetriever | None = None,
    explainer: LicenseExplainer | None = None,
) -> IntelligenceFacade:
    """배포용 조립.

    RAG 검색기는 region 설정이 필요해 Integration 이 만들어 넘긴다
    (:class:`~.rag.engine.RagEngineRetriever` 참조).
    """
    config = IntelligenceConfig.from_env(env)
    client = GoogleGenAIClient(
        config.gemini_model_id,
        api_key=config.gemini_api_key,
        vertex_config=config.vertex_config,
    )
    search_provider = (
        KiprisClient(config.kipris_access_key) if config.kipris_access_key else None
    )
    return IntelligenceFacade(
        create_analyzer_registry(
            metadata_provider=HttpPackageMetadataProvider(),
            model_client=client,
            search_provider=search_provider,
            retriever=retriever,
            explainer=explainer,
            patent_candidate_cap=config.patent_candidate_cap,
        )
    )

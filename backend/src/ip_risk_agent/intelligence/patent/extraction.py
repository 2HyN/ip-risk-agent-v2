"""기술 요소와 검색어 추출.

특허 검토 대상인지부터 가른다. 회의록이나 일정표까지 KIPRIS 로 보내면 한도만
소모하고 결과도 무의미하다.

"기술 내용이 부족하다"와 "특허 대상 문서가 아니다"를 구분한다 (Agent 3 Spec 13).
앞은 INCONCLUSIVE, 뒤는 SKIPPED 다. 둘을 섞으면 Control 이 잘못 판단한다.
"""

from __future__ import annotations

from iprisk_contracts import AnalysisArtifact

from ..gemini.client import PromptLibrary, StructuredModelClient
from ..gemini.schemas import TechnicalExtraction

# 검색어가 너무 많으면 KIPRIS 호출이 그만큼 늘어난다 (Agent 3 Spec 13).
MAX_QUERIES = 5
MIN_QUERY_WORDS = 2
MAX_QUERY_WORDS = 3

# v1 은 영문 검색어를 지시했다. KIPRIS 는 한국 특허 DB 이고 색인 본문이 한국어라
# 영문 2~3 단어로는 히트가 0 건이었다 — 배포 진단에서 query_count=3,
# search_failures=0, hit_total=0 으로 확인했다. v2 는 한국어 검색어를 만든다.
# v1 파일은 과거 결과의 prompt_version 근거로 남긴다.
PROMPT_NAME = "patent_extract_v2"


def render_segments(artifact: AnalysisArtifact) -> str:
    """모델에 넘길 입력. segment ID 를 붙여 근거를 가리킬 수 있게 한다."""
    return "\n\n".join(
        f"[{segment.segment_id}]\n{segment.text}" for segment in artifact.text_segments
    )


def clamp_queries(queries: list[str], *, max_queries: int = MAX_QUERIES) -> list[str]:
    """검색어를 2~3 단어로 자른다.

    KIPRIS 의 anySearch 는 넣은 단어를 모두 포함하는 문서만 찾는다. 다섯 단어를
    넣으면 결과가 0건이 된다. 모델이 길게 만들어도 여기서 줄인다.

    상한은 검색 전략(plan)이 정한다. 기본값은 현행 그대로다.
    """
    cleaned: list[str] = []
    for raw in queries:
        words = raw.replace(",", " ").split()
        if len(words) < MIN_QUERY_WORDS:
            continue
        candidate = " ".join(words[:MAX_QUERY_WORDS])
        if candidate not in cleaned:
            cleaned.append(candidate)
    return cleaned[:max_queries]


class TechnicalExtractor:
    """모델을 호출해 기술 요소와 검색어를 얻는다.

    프롬프트와 검색어 상한은 검색 전략이 주입한다. 기본값이 현행 상수라 아무것도
    넘기지 않으면 지금까지와 같은 동작이다.
    """

    def __init__(
        self,
        client: StructuredModelClient,
        prompts: PromptLibrary | None = None,
        *,
        prompt_name: str = PROMPT_NAME,
        max_queries: int = MAX_QUERIES,
    ) -> None:
        self._client = client
        self._prompts = prompts or PromptLibrary()
        self._prompt_name = prompt_name
        self._max_queries = max_queries

    @property
    def prompt_version(self) -> str:
        return self._prompts.get(self._prompt_name).prompt_version

    async def extract(self, artifact: AnalysisArtifact) -> TechnicalExtraction:
        prompt = self._prompts.get(self._prompt_name)
        rendered = prompt.render(segments=render_segments(artifact))
        result = await self._client.generate(rendered, TechnicalExtraction)

        known = {segment.segment_id for segment in artifact.text_segments}
        return TechnicalExtraction(
            is_technical=result.is_technical,
            technical_elements=result.technical_elements,
            search_queries=clamp_queries(
                result.search_queries, max_queries=self._max_queries
            ),
            # 입력에 없는 segment 를 지목했다면 그 참조만 버린다.
            source_segment_ids=[s for s in result.source_segment_ids if s in known],
        )

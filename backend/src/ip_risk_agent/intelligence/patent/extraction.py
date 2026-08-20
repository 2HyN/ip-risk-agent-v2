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

PROMPT_NAME = "patent_extract_v1"


def render_segments(artifact: AnalysisArtifact) -> str:
    """모델에 넘길 입력. segment ID 를 붙여 근거를 가리킬 수 있게 한다."""
    return "\n\n".join(
        f"[{segment.segment_id}]\n{segment.text}" for segment in artifact.text_segments
    )


def clamp_queries(queries: list[str]) -> list[str]:
    """검색어를 2~3 단어로 자른다.

    KIPRIS 의 anySearch 는 넣은 단어를 모두 포함하는 문서만 찾는다. 다섯 단어를
    넣으면 결과가 0건이 된다. 모델이 길게 만들어도 여기서 줄인다.
    """
    cleaned: list[str] = []
    for raw in queries:
        words = raw.replace(",", " ").split()
        if len(words) < MIN_QUERY_WORDS:
            continue
        candidate = " ".join(words[:MAX_QUERY_WORDS])
        if candidate not in cleaned:
            cleaned.append(candidate)
    return cleaned[:MAX_QUERIES]


class TechnicalExtractor:
    """모델을 호출해 기술 요소와 검색어를 얻는다."""

    def __init__(
        self,
        client: StructuredModelClient,
        prompts: PromptLibrary | None = None,
    ) -> None:
        self._client = client
        self._prompts = prompts or PromptLibrary()

    @property
    def prompt_version(self) -> str:
        return self._prompts.get(PROMPT_NAME).prompt_version

    async def extract(self, artifact: AnalysisArtifact) -> TechnicalExtraction:
        prompt = self._prompts.get(PROMPT_NAME)
        rendered = prompt.render(segments=render_segments(artifact))
        result = await self._client.generate(rendered, TechnicalExtraction)

        known = {segment.segment_id for segment in artifact.text_segments}
        return TechnicalExtraction(
            is_technical=result.is_technical,
            technical_elements=result.technical_elements,
            search_queries=clamp_queries(result.search_queries),
            # 입력에 없는 segment 를 지목했다면 그 참조만 버린다.
            source_segment_ids=[s for s in result.source_segment_ids if s in known],
        )

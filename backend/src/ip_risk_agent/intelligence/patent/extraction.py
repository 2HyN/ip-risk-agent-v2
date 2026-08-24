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


def expand_queries(queries: list[str], *, cap: int = 15) -> list[str]:
    """3단어 질의를 2단어 부분조합으로도 검색한다.

    KIPRIS 검색은 넣은 단어를 **모두** 포함한 문서만 찾는다. 그래서 3단어
    질의는 표현이 조금만 달라도 통째로 빈다 — 골든셋 실측에서 "셔터 CCTV
    연동" 같은 정확한 질의가 심사관 인용 문헌을 못 데려온 원인 후보다.
    원 질의를 앞에 두고(정밀한 것 우선), 그 2단어 조합을 뒤에 붙인다.

    결정론적이다 — 같은 질의 목록이면 같은 확장이 나온다. 검색 호출 수가
    cap 까지 늘어나므로 기본 경로에서는 쓰지 않고 옵션으로 켠다.

    cap 은 2라운드(질의당 조합 둘)가 들어가는 크기여야 한다. 10 이었을 때
    5질의 × 1라운드에서 잘려 정답 질의("셔터 제어"·"셔터 연동")가 목록에
    못 들어간 것을 골든셋 역방향 테스트로 확인했다.
    """
    expanded: list[str] = []

    def _add(candidate: str) -> bool:
        if candidate not in expanded and len(expanded) < cap:
            expanded.append(candidate)
        return len(expanded) < cap

    for query in queries:
        _add(query)
    # 질의별로 돌아가며 하나씩 넣는다 — 첫 질의의 조합이 cap 을 독식해
    # 뒤 질의("셔터 CCTV 연동")의 조합이 아예 못 들어가는 것을 막는다.
    pools = []
    for query in queries:
        words = query.split()
        if len(words) < 3:
            continue
        pools.append(
            [
                f"{words[i]} {words[j]}"
                for i in range(len(words))
                for j in range(i + 1, len(words))
            ]
        )
    position = 0
    while any(position < len(pool) for pool in pools):
        for pool in pools:
            if position < len(pool) and not _add(pool[position]):
                return expanded
        position += 1
    return expanded


def query_families(originals: list[str], executed: list[str]) -> dict[str, str]:
    """실행 질의 → 원 질의(계열) 매핑.

    확장 질의(2단어 부분조합)는 원 질의의 변형이지 새로운 각도가 아니다.
    순위(RRF)가 계열당 최대 기여만 세도록, 각 실행 질의를 단어 집합이 포함되는
    첫 원 질의에 귀속시킨다. 어느 원 질의에도 안 들어가면 자기 자신이 계열이다.
    """
    families: dict[str, str] = {}
    for query in executed:
        words = set(query.split())
        family = query
        for original in originals:
            if words <= set(original.split()):
                family = original
                break
        families[query] = family
    return families


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

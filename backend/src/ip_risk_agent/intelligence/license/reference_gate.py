"""RAG 참조가 분석 대상 라이선스를 실제로 다루는지 판정한다.

corpus 는 작고 임베딩 검색은 항상 ``top_k`` 개를 돌려준다. 관련 문서가 하나도
없어도 **가장 덜 관련 없는 것**이 나온다. 그 결과 ``GPL-3.0-only`` 분석에
AGPL 문서가 근거로 붙어도 근거 ID 검증과 프롬프트 제약을 모두 통과한다.
근거가 없는 것보다 **틀린 근거가 붙는 것이 나쁘다.**

그래서 임베딩 점수가 아니라 **주제 일치**로 결정적으로 거른다. 점수 임계값은
provider 응답 필드에 의존해 실측 없이는 검증할 수 없고, 값이 바뀌면 조용히
무력화된다. 아래 표는 corpus manifest 에서 뽑아 이 패키지에 함께 실린다.

``rag-corpus/`` 는 런타임 이미지에 포함되지 않으므로 manifest 를 실행 시점에 읽을 수
없다. 그래서 예전에는 표를 **코드에 손으로 적었고**, 문서를 하나 더할 때마다 코드를
고쳐야 했다. 지금은 ``scripts/build_rag_corpus.py`` 가 manifest 의 ``covers`` 에서
뽑아 ``corpus_coverage.json`` 으로 내고, 배포 validator 가 셋이 같은지 확인한다.
"""

from __future__ import annotations

import json
from importlib import resources

from . import spdx

# source_id -> 그 문서가 실제로 다루는 SPDX 식별자.
#
# 부분 문자열로 판정하지 않는다. "AGPL-3.0-only" 는 "GPL-3.0-only" 를 포함하므로
# 그렇게 하면 이 게이트가 막으려는 바로 그 오류를 만든다.
#
# 손으로 적지 않는다. `scripts/build_rag_corpus.py` 가 manifest 에서 뽑아 둔 것을
# 읽는다 — 문서를 늘릴 때 코드를 고치지 않기 위해서다. 파일이 wheel 에 실리는지는
# `pyproject.toml` 의 package-data 와 배포 validator 가 함께 지킨다.
def _load_coverage() -> dict[str, frozenset[str]]:
    payload = (
        resources.files(__package__)
        .joinpath("corpus_coverage.json")
        .read_text(encoding="utf-8")
    )
    return {
        str(name): frozenset(values) for name, values in json.loads(payload).items()
    }


CORPUS_SUBJECT_COVERAGE: dict[str, frozenset[str]] = _load_coverage()


def _covered_identifiers(source_id: str) -> frozenset[str]:
    """chunk 의 source 식별자를 표에 맞춘다.

    RAG Engine 은 ``sourceDisplayName`` 을 파일명으로 돌려줄 수 있어 확장자와
    경로를 떼고 대조한다. 표에 없는 source 는 커버리지를 주장하지 않는다.
    """
    name = source_id.rsplit("/", 1)[-1].strip().lower()
    if name.endswith(".md"):
        name = name[: -len(".md")]
    return CORPUS_SUBJECT_COVERAGE.get(name, frozenset())


def expression_identifiers(license_expression: str) -> frozenset[str]:
    """표현식에 등장하는 라이선스 식별자 집합."""
    node = spdx.try_parse_expression(license_expression)
    if node is None:
        return frozenset()
    return frozenset(leaf.identifier for leaf in spdx.leaves(node))


def is_relevant(source_id: str, license_expression: str) -> bool:
    """이 참조가 분석 대상 라이선스를 실제로 다루는가."""
    covered = _covered_identifiers(source_id)
    if not covered:
        return False
    return bool(covered & expression_identifiers(license_expression))


def select_relevant(chunks, license_expression: str) -> list:
    """주제가 맞는 참조만 남긴다. 없으면 빈 목록이다.

    빈 목록이면 호출부는 근거 없이 ``policy.describe()`` 고정 문구로 간다.
    모르는 것을 아는 척하지 않는다.
    """
    return [chunk for chunk in chunks if is_relevant(chunk.source_id, license_expression)]


__all__ = [
    "CORPUS_SUBJECT_COVERAGE",
    "expression_identifiers",
    "is_relevant",
    "select_relevant",
]

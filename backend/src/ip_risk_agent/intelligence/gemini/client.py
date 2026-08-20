"""Gemini 접근 계층.

Analyzer 는 SDK 를 모른다. 여기서만 안다 (Agent 3 Spec 9). 그래야 SDK 가 바뀌거나
모델을 갈아끼울 때 분석 로직을 건드리지 않는다.

프롬프트는 코드에 흩어 두지 않고 파일로 관리하며 버전 ID 를 결과에 기록한다
(Agent 3 Spec 10). 과거 판단이 왜 달랐는지를 설명할 수 있어야 한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ..common.errors import FailureCategory, MalformedProviderOutputError, ProviderFailureError
from .retry import RetryBudget, with_retry

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

# 파일 앞의 YAML 머리말에서 버전을 읽는다.
_FRONT_MATTER = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.S)
_VERSION = re.compile(r"^version:\s*(?P<value>\S+)\s*$", re.M)

OutputT = TypeVar("OutputT", bound=BaseModel)

# Gemini 는 JSON Schema 를 그대로 받지 않는다. Pydantic 이 붙이는 부가 항목 중
# 일부를 모르는 필드로 보고 400 을 돌려준다. 검증은 우리 쪽에서 계속 엄격하게 하고,
# API 에는 이해할 수 있는 형태만 보낸다.
_SCHEMA_DROP = ("additionalProperties", "title", "$schema", "default", "examples")


def to_api_schema(model: type[BaseModel]) -> dict:
    """Pydantic 모델을 Gemini 가 받는 스키마로 바꾼다.

    ``$ref`` 는 펼친다. 중첩 모델을 참조로 남기면 해석하지 못한다.
    """
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def convert(node: object) -> object:
        if isinstance(node, list):
            return [convert(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = str(node["$ref"]).rsplit("/", 1)[-1]
            return convert(dict(definitions.get(name, {})))
        return {
            key: convert(value)
            for key, value in node.items()
            if key not in _SCHEMA_DROP
        }

    return convert(schema)  # type: ignore[return-value]




@dataclass(frozen=True)
class Prompt:
    """버전이 붙은 프롬프트. 이름과 버전이 결과에 기록된다."""

    prompt_id: str
    version: str
    template: str

    @property
    def prompt_version(self) -> str:
        return f"{self.prompt_id}_{self.version}"

    def render(self, **values: str) -> str:
        return self.template.format(**values)


class PromptLibrary:
    """프롬프트 파일을 읽어 캐시한다."""

    def __init__(self, directory: Path = PROMPT_DIR) -> None:
        self._directory = directory
        self._cache: dict[str, Prompt] = {}

    def get(self, name: str) -> Prompt:
        """``patent_extract_v1`` 처럼 파일 이름(확장자 제외)으로 찾는다."""
        if cached := self._cache.get(name):
            return cached

        path = self._directory / f"{name}.md"
        if not path.is_file():
            raise FileNotFoundError(f"prompt not found: {path}")
        raw = path.read_text(encoding="utf-8")

        match = _FRONT_MATTER.match(raw)
        if not match:
            raise ValueError(f"prompt {name!r} is missing front matter")
        version_match = _VERSION.search(match.group("body"))
        if not version_match:
            raise ValueError(f"prompt {name!r} is missing a version")

        prompt = Prompt(
            prompt_id=name.rsplit("_", 1)[0],
            version=version_match.group("value"),
            template=raw[match.end():],
        )
        self._cache[name] = prompt
        return prompt


class StructuredModelClient(Protocol):
    """구조화된 출력만 받는다. 자유 서술은 검증할 수 없다."""

    @property
    def model_id(self) -> str:
        ...

    async def generate(self, prompt: str, output_model: type[OutputT]) -> OutputT:
        ...


class GoogleGenAIClient:
    """google-genai SDK 구현.

    SDK 는 선택 의존성이다. 설치되어 있지 않으면 생성 시점에 알린다.
    필요한 패키지는 ``agent-deliverables/agent-3-dependencies.md`` 에 적어 두었다.
    """

    def __init__(
        self,
        model_id: str,
        *,
        api_key: str | None = None,
        vertex_config: dict[str, str] | None = None,
        budget: RetryBudget | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        try:
            from google import genai  # noqa: PLC0415 - 선택 의존성
        except ImportError as exc:  # pragma: no cover - 설치 여부에 따라 갈린다
            raise RuntimeError(
                "google-genai is required for GoogleGenAIClient; "
                "see agent-deliverables/agent-3-dependencies.md"
            ) from exc

        self._genai = genai
        self._model_id = model_id
        self._budget = budget or RetryBudget()
        self._timeout_seconds = timeout_seconds
        # AI Studio 와 Vertex 를 같은 코드로 쓴다. region 은 설정으로 받는다.
        self._client = genai.Client(api_key=api_key, **(vertex_config or {}))

    @property
    def model_id(self) -> str:
        return self._model_id

    async def generate(self, prompt: str, output_model: type[OutputT]) -> OutputT:
        async def call() -> OutputT:
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model_id,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": to_api_schema(output_model),
                        "http_options": {"timeout": int(self._timeout_seconds * 1000)},
                    },
                )
            except TimeoutError as exc:
                raise ProviderFailureError(
                    "GEMINI", FailureCategory.TIMEOUT, "request timed out"
                ) from exc
            except Exception as exc:  # noqa: BLE001 - SDK 예외 종류가 넓다
                raise ProviderFailureError(
                    "GEMINI", FailureCategory.UNAVAILABLE, type(exc).__name__
                ) from exc

            return _parse(response.text, output_model)

        return await with_retry(call, self._budget)


def _parse(text: str | None, output_model: type[OutputT]) -> OutputT:
    """응답 본문을 스키마로 검증한다. 실패하면 재시도 대상이다."""
    if not text:
        raise MalformedProviderOutputError("GEMINI", "empty response")
    try:
        return output_model.model_validate_json(text)
    except ValidationError as exc:
        # 원문을 메시지에 싣지 않는다. 어떤 필드가 문제인지만 남긴다.
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        raise MalformedProviderOutputError(
            "GEMINI", f"schema mismatch: {', '.join(fields)}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise MalformedProviderOutputError("GEMINI", "response was not valid JSON") from exc


class ScriptedModelClient:
    """테스트용. 정해진 응답을 순서대로 돌려준다.

    응답 자리에 예외를 넣으면 그 시점에 실패를 재현할 수 있다.
    """

    def __init__(self, responses: list[BaseModel | Exception], model_id: str = "fake-model") -> None:
        self._responses = list(responses)
        self._model_id = model_id
        self.prompts: list[str] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    async def generate(self, prompt: str, output_model: type[OutputT]) -> OutputT:
        self.prompts.append(prompt)
        if not self._responses:
            raise MalformedProviderOutputError("GEMINI", "no scripted response left")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if not isinstance(response, output_model):
            raise MalformedProviderOutputError(
                "GEMINI", f"expected {output_model.__name__}"
            )
        return response

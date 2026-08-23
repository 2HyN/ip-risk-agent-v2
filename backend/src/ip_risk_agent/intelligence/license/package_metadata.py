"""패키지 라이선스 조회.

레지스트리가 돌려주는 값은 법적 결론이 아니라 사실 근거다 (Agent 3 Spec 26).
그래서 어디서 온 값인지를 함께 들고 다닌다.

단일 출처만 믿으면 상위 위험이 조용히 누락된다. deps.dev 는 PyMuPDF 의 라이선스를
``non-standard`` 로 돌려주는데 실제로는 AGPL 이다. 그 경우 레지스트리 원문을 다시
읽어 복원한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from . import spdx
from .dependency_models import Ecosystem
from ..common.errors import FailureCategory, ProviderFailureError

DEPS_DEV_BASE_URL = "https://api.deps.dev/v3"
PYPI_BASE_URL = "https://pypi.org/pypi"
NPM_BASE_URL = "https://registry.npmjs.org"

_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class PackageLicenseFact:
    """조회 결과. 값과 출처를 함께 남긴다."""

    ecosystem: Ecosystem
    package: str
    version: str | None
    license_expression: str
    source: str
    inferred_from_free_text: bool = False
    #: 요청한 버전이 레지스트리에 없었다. 최신 버전으로 **대체하지 않았다**는 표시다.
    version_not_found: bool = False

    @property
    def is_unknown(self) -> bool:
        return self.license_expression == spdx.UNKNOWN_LICENSE


class PackageMetadataProvider(Protocol):
    """생태계에 상관없이 같은 형태로 답한다."""

    async def get_license(
        self, ecosystem: Ecosystem, package: str, version: str | None
    ) -> PackageLicenseFact:
        ...


class HttpPackageMetadataProvider:
    """deps.dev 우선, 실패하거나 미상이면 레지스트리 원문으로 보완."""

    def __init__(
        self,
        deps_dev_base_url: str = DEPS_DEV_BASE_URL,
        pypi_base_url: str = PYPI_BASE_URL,
        npm_base_url: str = NPM_BASE_URL,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = _TIMEOUT_SECONDS,
    ) -> None:
        self._deps_dev = deps_dev_base_url.rstrip("/")
        self._pypi = pypi_base_url.rstrip("/")
        self._npm = npm_base_url.rstrip("/")
        self._owns_client = client is None
        # 의존성 수만큼 호출하므로 연결을 재사용한다.
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={"User-Agent": "ip-risk-agent/1.0"},
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "HttpPackageMetadataProvider":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def get_license(
        self, ecosystem: Ecosystem, package: str, version: str | None
    ) -> PackageLicenseFact:
        fact = await self._from_deps_dev(ecosystem, package, version)
        if fact is not None and not fact.is_unknown:
            return fact

        fallback = await self._from_registry(ecosystem, package, version)
        if fallback is not None:
            return fallback
        if fact is not None:
            return fact

        raise ProviderFailureError(
            "PACKAGE_METADATA",
            FailureCategory.NOT_FOUND,
            f"no license metadata for {ecosystem.value}/{package}",
        )

    # ------------------------------------------------------------ deps.dev

    async def _from_deps_dev(
        self, ecosystem: Ecosystem, package: str, version: str | None
    ) -> PackageLicenseFact | None:
        if version is None:
            return None  # 버전 없이 조회하면 어느 버전의 답인지 알 수 없다.
        system = "PYPI" if ecosystem is Ecosystem.PYPI else "NPM"
        url = f"{self._deps_dev}/systems/{system}/packages/{package}/versions/{version}"
        payload = await self._get(url, "DEPS_DEV")
        if payload is None:
            return None
        licenses = [str(item) for item in payload.get("licenses") or []]
        expression = " AND ".join(licenses) if licenses else ""
        return PackageLicenseFact(
            ecosystem=ecosystem,
            package=package,
            version=version,
            license_expression=spdx.normalize(expression),
            source="deps.dev",
        )

    # ------------------------------------------------------------ 레지스트리

    async def _from_registry(
        self, ecosystem: Ecosystem, package: str, version: str | None
    ) -> PackageLicenseFact | None:
        declared = ""
        if ecosystem is Ecosystem.PYPI:
            path = f"{package}/{version}" if version else package
            payload = await self._get(f"{self._pypi}/{path}/json", "PYPI")
            info = (payload or {}).get("info", {})
            # PEP 639 이 들여온 **정규 SPDX 표현식** 필드다. 예전에는 이것을
            # 읽지 않고 자유 서술인 ``license`` 만 봤다. 그러는 동안 PyPI 는
            # ``license`` 를 폐기하고 이쪽으로 옮겼고, 옮긴 패키지는 ``license`` 가
            # 빈문자열이 된다. 그래서 ``chardet==7.6.0`` 은 PyPI 가 ``0BSD`` 를
            # 명시하는데도 우리는 "모른다" 를 냈고, ``paramiko==5.0.0`` 은
            # ``LGPL-2.1`` 을 명시하는데도 **약한 반대급부 의무가 통째로
            # 사라졌다.** 패키지가 PEP 639 로 옮길수록 더 나빠진다.
            declared = str(info.get("license_expression") or "")
            raw = str(info.get("license") or "")
            classifiers = info.get("classifiers") or ()
            source = "pypi.org"
        else:
            payload = await self._get(f"{self._npm}/{package}", "NPM")
            info = payload or {}
            if version and isinstance(info.get("versions"), dict):
                found = info["versions"].get(version)
                if found is None:
                    # 요청한 버전이 없다. 예전에는 문서 전체로 폴백해 **최신 버전의
                    # 라이선스를 그 버전의 것으로 기록**했고, 표시조차 붙지 않았다.
                    #
                    # 라이선스는 버전마다 달라진다. 그리고 실제로 라이선스를 바꾼
                    # 패키지들이 이 제품이 잡으려는 대상이다 — 그 순간에 최신 값으로
                    # 덮으면 **바뀌었다는 사실 자체가 사라진다.**
                    return PackageLicenseFact(
                        ecosystem=ecosystem,
                        package=package,
                        version=version,
                        license_expression=spdx.UNKNOWN_LICENSE,
                        source="registry.npmjs.org",
                        version_not_found=True,
                    )
                info = found
            raw = str(info.get("license") or "")
            classifiers = ()
            source = "registry.npmjs.org"

        if payload is None:
            return None

        # 순서가 중요하다. 먼저 **명시된 표현식**을 본다 — 그것은 이미 SPDX 이므로
        # 추정이 아니다. 추정으로 표시하면 조회해 온 사실을 우리 짐작으로 낮춰 적는 것이 된다.
        # 그다음이 자유 서술 ``license`` 이고, 거기서 나온 것은 추정으로 남긴다 —
        # 밝히지 않으면 사용자가 조회된 값과 구분할 수 없다.
        expression, inferred = self._resolve_declaration(declared, raw, classifiers)
        return PackageLicenseFact(
            ecosystem=ecosystem,
            package=package,
            version=version,
            license_expression=expression,
            source=source,
            inferred_from_free_text=inferred,
        )

    @staticmethod
    def _resolve_declaration(
        declared: str, raw: str, classifiers: object
    ) -> tuple[str, bool]:
        """레지스트리가 말한 것들에서 식별자 하나를 고른다. ``(식별식, 추정인가)``.

        순서가 곧 신뢰도다.

        1. **명시된 SPDX 표현식** (PEP 639 ``license_expression``). 이미 표현식이므로
           추정이 아니다. 추정으로 표시하면 조회해 온 사실을 우리 짐작으로 낮춰 적는 셈이다.
        2. **자유 서술이 그대로 표현식으로 읽히는 경우** (``license: "BSD-3-Clause"``).
           흔하고, 역시 짐작이 아니다. 다만 이름 길이일 때만 본다 — 전문을 표현식으로
           파싱해 볼 이유가 없다.
        3. **trove 분류자.** 닫힌 어휘라 훑지 않아도 되고, 자유 서술을 거절하기로 한
           이상 이것이 있어야 한다. 판을 말하지 않는 항목은 좁혀 적으므로 추정으로 남긴다.
        4. **자유 서술 훑기.** 마지막이고, 이름 길이일 때만 한다.

        분류자를 자유 서술보다 앞에 두는 이유는 분류자가 더 정확할 때가 있어서다.
        ``license: "LGPL"`` 로는 2.0 인지 2.1 인지 or-later 인지 알 수 없어 짐작해야
        하는데, 옆의 분류자가 "v2 or later (LGPLv2+)" 라고 적어 둔다.
        """
        parsed = spdx.try_parse_expression(declared) if declared else None
        if parsed is not None and not spdx.is_all_unknown(parsed):
            return str(parsed), False

        if spdx.is_declared_expression(raw):
            parsed = spdx.try_parse_expression(raw)
            if parsed is not None and not spdx.is_all_unknown(parsed):
                return str(parsed), False

        if isinstance(classifiers, (list, tuple)):
            found, narrowed = spdx.from_trove_classifiers(classifiers)
            if found != spdx.UNKNOWN_LICENSE:
                return found, narrowed

        guessed = spdx.from_free_text(raw)
        return guessed, guessed != spdx.UNKNOWN_LICENSE

    # ------------------------------------------------------------ 공통

    async def _get(self, url: str, provider: str) -> dict | None:
        """404 는 정상적인 '없음'이고, 그 외 실패는 provider 장애다."""
        try:
            response = await self._client.get(url)
        except httpx.TimeoutException as exc:
            raise ProviderFailureError(
                provider, FailureCategory.TIMEOUT, "request timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderFailureError(
                provider, FailureCategory.UNAVAILABLE, type(exc).__name__
            ) from exc

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            category = (
                FailureCategory.RATE_LIMITED
                if response.status_code == 429
                else FailureCategory.UNAVAILABLE
            )
            raise ProviderFailureError(
                provider, category, f"HTTP {response.status_code}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise ProviderFailureError(
                provider, FailureCategory.MALFORMED_OUTPUT, "response was not valid JSON"
            ) from exc


class StaticPackageMetadataProvider:
    """테스트용. 실제 호출 없이 정해진 답을 돌려준다."""

    def __init__(
        self,
        licenses: dict[tuple[str, str], str],
        *,
        failures: set[tuple[str, str]] | None = None,
    ) -> None:
        self._licenses = licenses
        self._failures = failures or set()

    async def get_license(
        self, ecosystem: Ecosystem, package: str, version: str | None
    ) -> PackageLicenseFact:
        key = (ecosystem.value, package)
        if key in self._failures:
            raise ProviderFailureError(
                "PACKAGE_METADATA", FailureCategory.UNAVAILABLE, "provider unavailable"
            )
        raw = self._licenses.get(key)
        if raw is None:
            raise ProviderFailureError(
                "PACKAGE_METADATA", FailureCategory.NOT_FOUND, "not found"
            )
        return PackageLicenseFact(
            ecosystem=ecosystem,
            package=package,
            version=version,
            license_expression=spdx.normalize(raw),
            source="static",
        )

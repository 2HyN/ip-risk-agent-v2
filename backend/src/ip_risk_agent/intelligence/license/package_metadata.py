"""패키지 라이선스 조회.

레지스트리가 돌려주는 값은 법적 결론이 아니라 사실 근거다 (Agent 3 Spec 26).
그래서 어디서 온 값인지를 함께 들고 다닌다.

단일 출처만 믿으면 상위 위험이 조용히 누락된다. deps.dev 는 PyMuPDF 의 라이선스를
``non-standard`` 로 돌려주는데 실제로는 AGPL 이다. 그 경우 레지스트리 원문을 다시
읽어 복원한다.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

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

    @property
    def is_unknown(self) -> bool:
        return self.license_expression == spdx.UNKNOWN_LICENSE


class PackageMetadataProvider(Protocol):
    """생태계에 상관없이 같은 형태로 답한다."""

    async def get_license(
        self, ecosystem: Ecosystem, package: str, version: str | None
    ) -> PackageLicenseFact:
        ...


def _fetch_json(url: str) -> dict:
    """동기 HTTP. 호출부에서 스레드로 넘긴다.

    표준 라이브러리만 쓴다. root 의존성을 늘리지 않기 위해서다.
    HTTP client 를 추가하면 agent-3-dependencies.md 를 통해 요청한다.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "ip-risk-agent/1.0"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return json.loads(response.read())


class HttpPackageMetadataProvider:
    """deps.dev 우선, 실패하거나 미상이면 레지스트리 원문으로 보완."""

    def __init__(
        self,
        deps_dev_base_url: str = DEPS_DEV_BASE_URL,
        pypi_base_url: str = PYPI_BASE_URL,
        npm_base_url: str = NPM_BASE_URL,
    ) -> None:
        self._deps_dev = deps_dev_base_url.rstrip("/")
        self._pypi = pypi_base_url.rstrip("/")
        self._npm = npm_base_url.rstrip("/")

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
        url = (
            f"{self._deps_dev}/systems/{system}/packages/"
            f"{urllib.parse.quote(package, safe='')}/versions/"
            f"{urllib.parse.quote(version, safe='')}"
        )
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
        if ecosystem is Ecosystem.PYPI:
            path = f"{package}/{version}" if version else package
            payload = await self._get(f"{self._pypi}/{path}/json", "PYPI")
            raw = str((payload or {}).get("info", {}).get("license") or "")
            source = "pypi.org"
        else:
            payload = await self._get(f"{self._npm}/{urllib.parse.quote(package, safe='@/')}", "NPM")
            info = payload or {}
            if version and isinstance(info.get("versions"), dict):
                info = info["versions"].get(version, info)
            raw = str(info.get("license") or "")
            source = "registry.npmjs.org"

        if payload is None:
            return None

        # 레지스트리 값은 표현식이 아니라 설명문인 경우가 많다.
        expression = spdx.normalize(raw)
        inferred = False
        if expression == spdx.UNKNOWN_LICENSE and raw:
            expression = spdx.from_free_text(raw)
            inferred = expression != spdx.UNKNOWN_LICENSE
        return PackageLicenseFact(
            ecosystem=ecosystem,
            package=package,
            version=version,
            license_expression=expression,
            source=source,
            inferred_from_free_text=inferred,
        )

    # ------------------------------------------------------------ 공통

    async def _get(self, url: str, provider: str) -> dict | None:
        """404 는 정상적인 '없음'이고, 그 외 실패는 provider 장애다."""
        try:
            return await asyncio.to_thread(_fetch_json, url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            category = (
                FailureCategory.RATE_LIMITED if exc.code == 429 else FailureCategory.UNAVAILABLE
            )
            raise ProviderFailureError(provider, category, f"HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise ProviderFailureError(provider, FailureCategory.TIMEOUT, "request timed out") from exc
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            raise ProviderFailureError(
                provider, FailureCategory.UNAVAILABLE, type(exc).__name__
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

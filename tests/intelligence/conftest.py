"""Agent 3 테스트 설정."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: 실제 외부 provider 를 호출한다. 자격증명이 없으면 건너뛴다"
    )

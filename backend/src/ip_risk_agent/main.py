"""API 프로세스 진입점.

실행:

    uvicorn ip_risk_agent.main:app

조립은 전부 `ip_risk_agent.composition` 에 있다. 이 파일은 그 결과를 ASGI
런타임이 찾을 수 있는 이름으로 노출하기만 한다.
"""

from __future__ import annotations

from fastapi import FastAPI

from ip_risk_agent.composition import create_app

app: FastAPI = create_app()

__all__ = ["app"]

# IP Risk Agent — API 와 워커가 같은 이미지를 쓰고 진입점만 다르다.
# 이미지를 하나로 두면 두 서비스가 항상 같은 코드로 돈다.
FROM python:3.14.7-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 의존성 레이어를 먼저 만들어 코드 변경 시 재설치를 피한다.
COPY pyproject.toml README.md ./
COPY shared/contracts/python ./shared/contracts/python
COPY backend/src ./backend/src
COPY scripts ./scripts

RUN python -m pip install --upgrade pip \
 && python -m pip install .

# 루트로 돌지 않는다.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Cloud Run 이 PORT 를 주입한다. 기본값은 로컬 실행용이다.
ENV PORT=8080
EXPOSE 8080

# 기본 진입점은 API. 워커는 배포 설정에서 command 를 덮어쓴다.
CMD ["sh", "-c", "uvicorn ip_risk_agent.main:app --host 0.0.0.0 --port ${PORT}"]

# IP Risk Agent — Web UI 를 API 와 같은 이미지에 담는다.
#
# 프론트엔드는 production 번들에서 상대 경로로 /api/v1 을 호출하고, 하드닝
# 설정도 origin 하나만 허용한다. same-origin 서빙이 전제이므로 한 이미지에
# 넣는다 (composition/static.py 주석 참고).
#
# API 와 워커는 이 이미지를 공유하고 command 만 다르게 배포한다. 두 서비스가
# 항상 같은 코드로 도는 것이 중요하다.

# ---------------------------------------------------------------- web build
FROM node:24.19.0-slim AS web

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable && corepack prepare pnpm@11.19.0 --activate

WORKDIR /src

# 의존성 레이어를 먼저 만들어 소스만 바뀔 때 재설치를 피한다.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json ./frontend/
COPY apps/desktop/package.json ./apps/desktop/
COPY shared/contracts/typescript/package.json ./shared/contracts/typescript/
RUN pnpm install --frozen-lockfile

COPY shared/contracts ./shared/contracts
COPY frontend ./frontend
COPY scripts ./scripts

# contracts 를 먼저 빌드해야 frontend 가 @iprisk/contracts 를 해석한다.
RUN pnpm --filter @iprisk/contracts build \
 && pnpm --filter @iprisk/frontend build

# ------------------------------------------------------------------ runtime
FROM python:3.14.7-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY shared/contracts/python ./shared/contracts/python
COPY backend/src ./backend/src
COPY scripts ./scripts

RUN python -m pip install --upgrade pip \
 && python -m pip install .

# 빌드된 Web UI. 이 경로가 있으면 앱이 same-origin 으로 서빙한다.
COPY --from=web /src/frontend/dist /app/frontend/dist
ENV FRONTEND_DIST_DIR=/app/frontend/dist

# 루트로 돌지 않는다.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Cloud Run 이 PORT 를 주입한다. 기본값은 로컬 실행용이다.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn ip_risk_agent.main:app --host 0.0.0.0 --port ${PORT}"]

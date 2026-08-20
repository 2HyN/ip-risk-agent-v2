# syntax=docker/dockerfile:1.7
FROM node:24.19.0-bookworm-slim AS web
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
WORKDIR /workspace
RUN corepack enable && corepack prepare pnpm@11.19.0 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY shared/contracts/typescript/package.json shared/contracts/typescript/package.json
COPY frontend/package.json frontend/package.json
RUN pnpm install --frozen-lockfile --filter @iprisk/contracts --filter @iprisk/frontend
COPY shared/contracts/typescript shared/contracts/typescript
COPY frontend frontend
RUN pnpm --filter @iprisk/contracts build && pnpm --filter @iprisk/frontend build

FROM python:3.14.7-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    FRONTEND_DIST_DIR=/app/frontend/dist
WORKDIR /app
RUN groupadd --system --gid 10001 iprisk \
    && useradd --system --uid 10001 --gid iprisk --home-dir /nonexistent --shell /usr/sbin/nologin iprisk
COPY requirements.lock pyproject.toml ./
RUN python -m pip install --no-cache-dir -r requirements.lock
COPY backend backend
COPY shared/contracts/python shared/contracts/python
COPY --from=web /workspace/frontend/dist frontend/dist
RUN python -m pip install --no-cache-dir --no-deps . \
    && chown -R iprisk:iprisk /app
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "ip_risk_agent.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]

FROM node:22-slim AS frontend
# The public address a printed sheet label points at. The platform's CLI cannot pass a build argument (it builds
# an uploaded source zip), so deploy/maritime/deploy.py writes frontend/.env.production instead; a local
# `docker build --build-arg VITE_PUBLIC_URL=https://...` still works and wins over that file.
ARG VITE_PUBLIC_URL
WORKDIR /build
# Pinned to the team's pnpm: newer releases refuse lockfile entries published within the last day.
RUN corepack enable && corepack prepare pnpm@10.33.2 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/
RUN pnpm -C frontend install --frozen-lockfile
COPY contracts contracts
COPY frontend frontend
RUN pnpm -C frontend build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/
RUN uv sync --project backend --no-dev --frozen
COPY backend backend
COPY mocks mocks
COPY data/drawings data/drawings
COPY data/project data/project
COPY data/messages data/messages
COPY data/machines.json data/machines.json
COPY contracts contracts
COPY --from=frontend /build/frontend/dist frontend/dist
ENV DATA_DIR=/data
# The host injects PORT; the app binds it and keeps its state under /data.
CMD ["uv", "run", "--directory", "backend", "--no-dev", "--frozen", "python", "-m", "app.core.main"]

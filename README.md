# Aurora for Talona

Construction project coordination: drawing revisions, crew communication, schedules and source-backed decisions in one application.

## Run

Install Docker. Copy .env.example to .env, then run:

docker build -t talona-aurora .

docker run --rm -p 8000:8000 -e PORT=8000 --env-file .env -v talona-aurora-data:/data talona-aurora

Open http://localhost:8000. The volume preserves project data. The prepared example works with simulated external services. Live integrations require the corresponding credentials and switches in .env. Never commit credentials.

## Development

The backend is Python 3.12 with FastAPI and SQLite. The frontend is React, TypeScript and Three.js. Install uv and pnpm, then run:

pnpm -C frontend install --frozen-lockfile

pnpm -C frontend build

uv run --python 3.12 --directory backend python -m app.core.main

## Rights

Built for Talona. No open-source licence is granted.

# Local Three-Service Containerization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Run PostgreSQL, FastAPI, and Next.js with one Docker Compose command, while exposing a dependable backend readiness endpoint.

**Architecture:** PostgreSQL stays as the stateful Compose service with its existing named volume. Backend and frontend are independent production images. Compose startup is postgres → backend → frontend; the backend receives a container-only database URL whose host is postgres.

**Tech Stack:** Docker Compose v5, PostgreSQL 16, Python 3.12 slim, FastAPI, Uvicorn, SQLAlchemy async plus asyncpg, Node.js 24 Alpine, Next.js 16, TypeScript, pytest, httpx.

**Spec:** docs/superpowers/specs/2026-09-22-containerize-local-services.md

## Global Constraints

- Use project root as the build context for both images.
- Do not copy .env, .env.*, virtual environments, node_modules, .next, or Git metadata into images.
- Keep GET /health/db; add GET /api/v1/health.
- DATABASE_URL is host execution only; DATABASE_URL_DOCKER is Compose execution only.
- Do not introduce CORS, frontend API calls, tables, migrations, or Agent features.
- Never commit real keys, real passwords, or an actual resolved DSN.

## Review Focus

- A blank model API key must not break readiness, because health must not call the model.
- Database loss after startup must result in HTTP 503, not stale HTTP 200.
- Container database host must be postgres, never localhost.
- Actual .env must be absent from both images and Git status.
- The backend root currently serves the old frontend path, but frontend/index.html was moved; root must be made a JSON service descriptor.

### Task 1: Add a testable v1 health endpoint and remove the obsolete static-root dependency

**Files:**
- Create: backend/requirements-dev.txt
- Create: backend/tests/__init__.py
- Create: backend/tests/test_health.py
- Modify: backend/app/api/routes.py

**Interfaces:**
- Consumes: check_database() returning DatabaseHealthResult.
- Produces: GET /api/v1/health.
- Produces: GET / returning service JSON.

- [ ] **Step 1: Run the two preflight gates**

Run the existing frontend locally:

    cd frontend
    npm run dev

In another terminal:

    Invoke-WebRequest http://localhost:3000 -UseBasicParsing

Expected: HTTP 200.

Run the existing backend locally and then:

    Invoke-RestMethod http://127.0.0.1:8000/health/db

Expected: status is ok and database is connected. If not, correct only the local .env driver scheme to postgresql+asyncpg:// before continuing. Do not print the complete .env value.

- [ ] **Step 2: Install test dependencies**

Create backend/requirements-dev.txt:

    -r ../requirements.txt
    pytest>=8,<9
    httpx>=0.27,<1

Create empty backend/tests/__init__.py and install dependencies:

    pip install -r backend/requirements-dev.txt

- [ ] **Step 3: Write failing endpoint tests**

Create backend/tests/test_health.py:

    from fastapi.testclient import TestClient

    from app.api import routes
    from app.main import app
    from app.services.database_health import DatabaseHealthResult


    def test_v1_health_is_200_when_database_is_connected(monkeypatch):
        async def connected() -> DatabaseHealthResult:
            return DatabaseHealthResult(connected=True)

        monkeypatch.setattr(routes, "check_database", connected)

        with TestClient(app) as client:
            response = client.get("/api/v1/health")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "backend",
            "database": "connected",
        }


    def test_v1_health_is_503_when_database_is_unavailable(monkeypatch):
        async def unavailable() -> DatabaseHealthResult:
            return DatabaseHealthResult(
                connected=False,
                error_type="ConnectionRefusedError",
                message="无法连接数据库，请确认 PostgreSQL 容器已启动且 DATABASE_URL 配置正确。",
            )

        monkeypatch.setattr(routes, "check_database", unavailable)

        with TestClient(app) as client:
            response = client.get("/api/v1/health")

        assert response.status_code == 503
        assert response.json()["status"] == "error"
        assert response.json()["service"] == "backend"
        assert response.json()["database"] == "unavailable"
        assert "password" not in response.text.lower()

Run from backend:

    pytest tests/test_health.py -v

Expected: both fail with 404 before implementation.

- [ ] **Step 4: Implement the two routes without duplicating database logic**

In backend/app/api/routes.py remove FileResponse and FRONTEND_DIR imports; add Literal from typing.

Add after DatabaseHealthResponse:

    class ApplicationHealthResponse(DatabaseHealthResponse):
        service: Literal["backend"] = "backend"

Replace the root route:

    @router.get("/")
    def index() -> dict[str, str]:
        return {
            "service": "data-platform-agent-backend",
            "docs": "/docs",
            "health": "/api/v1/health",
        }

Extract the current health_db body into:

    async def get_database_health(response: Response) -> DatabaseHealthResponse:
        try:
            result = await check_database()
        except ConfigurationError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        if not result.connected:
            response.status_code = 503
            return DatabaseHealthResponse(
                status="error",
                database="unavailable",
                error_type=result.error_type,
                message=result.message,
            )
        return DatabaseHealthResponse(status="ok", database="connected")

Make health_db return await get_database_health(response). Add:

    @router.get(
        "/api/v1/health",
        response_model=ApplicationHealthResponse,
        response_model_exclude_none=True,
    )
    async def application_health(response: Response) -> ApplicationHealthResponse:
        health = await get_database_health(response)
        return ApplicationHealthResponse(
            service="backend",
            **health.model_dump(exclude_none=True),
        )

- [ ] **Step 5: Verify and commit**

    cd backend
    pytest tests/test_health.py -v
    Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
    Invoke-RestMethod http://127.0.0.1:8000/
    git add app/api/routes.py requirements-dev.txt tests
    git commit -m "feat: add versioned backend health endpoint"

Expected: two tests pass, health includes service backend, and root no longer tries to serve a missing file.

### Task 2: Create the production FastAPI image

**Files:**
- Create: .dockerignore
- Create: backend/Dockerfile

**Interfaces:**
- Consumes: root requirements.txt and backend/app.
- Produces: Uvicorn process on port 8000.

- [ ] **Step 1: Create root Docker context exclusions**

Create .dockerignore:

    .git
    .gitignore
    .env
    .env.*
    .venv
    venv
    env
    __pycache__
    *.py[cod]
    .pytest_cache
    .mypy_cache
    .ruff_cache
    node_modules
    frontend/node_modules
    frontend/.next
    *.docx
    docs

- [ ] **Step 2: Create backend/Dockerfile**

    FROM python:3.12-slim

    ENV PYTHONDONTWRITEBYTECODE=1 \
        PYTHONUNBUFFERED=1 \
        PIP_NO_CACHE_DIR=1

    WORKDIR /app

    COPY requirements.txt ./requirements.txt
    RUN pip install --no-cache-dir -r requirements.txt

    COPY backend/app ./app

    EXPOSE 8000

    CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

- [ ] **Step 3: Build and smoke-test it**

From root:

    docker build --file backend/Dockerfile --tag data-platform-agent-backend:local .
    docker run --rm data-platform-agent-backend:local python -c "from pathlib import Path; assert not Path('/app/.env').exists(); print('no .env in image')"
    docker run --rm --publish 8000:8000 --env DATABASE_URL=postgresql+asyncpg://invalid:invalid@postgres:5432/invalid data-platform-agent-backend:local

In another terminal:

    Invoke-WebRequest http://127.0.0.1:8000/docs -UseBasicParsing

Expected: docs HTTP 200. Stop the isolated image. Its v1 health correctly returns 503 because no database is attached.

- [ ] **Step 4: Commit**

    git add .dockerignore backend/Dockerfile
    git commit -m "build: add production FastAPI image"

### Task 3: Create the standalone Next.js production image

**Files:**
- Create: frontend/Dockerfile
- Create: frontend/public/.gitkeep
- Modify: frontend/next.config.ts

**Interfaces:**
- Consumes: frontend/package-lock.json and frontend source.
- Produces: standalone Node server on port 3000.

- [ ] **Step 1: Enable standalone output**

Replace frontend/next.config.ts:

    import type { NextConfig } from "next";

    const nextConfig: NextConfig = {
      output: "standalone",
    };

    export default nextConfig;

Create empty frontend/public/.gitkeep.

- [ ] **Step 2: Verify standalone output**

    cd frontend
    npm run build
    Test-Path .next/standalone/server.js

Expected: build succeeds and Test-Path returns True.

- [ ] **Step 3: Create frontend/Dockerfile**

    FROM node:24-alpine AS dependencies

    WORKDIR /app
    COPY frontend/package.json frontend/package-lock.json ./
    RUN npm ci

    FROM node:24-alpine AS builder

    WORKDIR /app
    ENV NEXT_TELEMETRY_DISABLED=1
    COPY --from=dependencies /app/node_modules ./node_modules
    COPY frontend/ ./
    RUN npm run build

    FROM node:24-alpine AS runner

    WORKDIR /app
    ENV NODE_ENV=production \
        NEXT_TELEMETRY_DISABLED=1 \
        HOSTNAME=0.0.0.0 \
        PORT=3000

    COPY --from=builder /app/public ./public
    COPY --from=builder /app/.next/standalone ./
    COPY --from=builder /app/.next/static ./.next/static

    EXPOSE 3000
    CMD ["node", "server.js"]

- [ ] **Step 4: Build, test, and commit**

From root:

    docker build --file frontend/Dockerfile --tag data-platform-agent-frontend:local .
    docker run --rm --publish 3000:3000 data-platform-agent-frontend:local

In another terminal:

    Invoke-WebRequest http://127.0.0.1:3000 -UseBasicParsing

Expected: HTTP 200 and body contains 数据中台 Agent. Stop the image, then:

    git add frontend/Dockerfile frontend/next.config.ts frontend/public/.gitkeep
    git commit -m "build: add standalone Next.js image"

### Task 4: Compose the three services with health-gated dependencies

**Files:**
- Modify: docker-compose.yml
- Modify: .env.example

**Interfaces:**
- Consumes: the two Dockerfiles plus local POSTGRES settings, model settings, and DATABASE_URL_DOCKER.
- Produces: host port 8000 for backend and 3000 for frontend.

- [ ] **Step 1: Add a container-only DSN template**

Append to .env.example:

    # 仅 Docker Compose 内的后端使用；容器内不能用 localhost。
    DATABASE_URL_DOCKER=postgresql+asyncpg://data_platform:data_platform_dev@postgres:5432/data_platform

Add the same key to actual local .env privately, with the same credentials/database as DATABASE_URL but host postgres. Do not display it.

- [ ] **Step 2: Add backend and frontend to docker-compose.yml**

Keep current name, postgres, and volumes. Add these two services under services:

    backend:
      build:
        context: .
        dockerfile: backend/Dockerfile
      restart: unless-stopped
      environment:
        OPENAI_API_KEY: ${OPENAI_API_KEY:-}
        OPENAI_BASE_URL: ${OPENAI_BASE_URL:-https://api.deepseek.com/v1}
        MODEL_NAME: ${MODEL_NAME:-deepseek-chat}
        TEMPERATURE: ${TEMPERATURE:-0.0}
        DATABASE_URL: ${DATABASE_URL_DOCKER:-postgresql+asyncpg://data_platform:data_platform_dev@postgres:5432/data_platform}
      depends_on:
        postgres:
          condition: service_healthy
      ports:
        - "8000:8000"
      healthcheck:
        test: ["CMD", "python", "-c", "from urllib.request import urlopen; response = urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3); assert response.status == 200"]
        interval: 10s
        timeout: 5s
        retries: 6
        start_period: 20s

    frontend:
      build:
        context: .
        dockerfile: frontend/Dockerfile
      restart: unless-stopped
      environment:
        NEXT_TELEMETRY_DISABLED: "1"
      depends_on:
        backend:
          condition: service_healthy
      ports:
        - "3000:3000"
      healthcheck:
        test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:3000').then((response) => process.exit(response.ok ? 0 : 1)).catch(() => process.exit(1))"]
        interval: 10s
        timeout: 5s
        retries: 6
        start_period: 20s

- [ ] **Step 3: Validate and run complete startup**

    docker compose config

Expected: postgres, backend, frontend appear; backend waits for postgres healthy and frontend waits for backend healthy. Do not paste resolved secrets.

Stop host-run backend/frontend to free ports, then run:

    docker compose down
    docker compose up --build -d
    docker compose ps
    Invoke-RestMethod http://localhost:8000/api/v1/health
    Invoke-WebRequest http://localhost:8000/docs -UseBasicParsing
    Invoke-WebRequest http://localhost:3000 -UseBasicParsing

Expected: all three become healthy; health reports backend plus connected database; docs and frontend are HTTP 200.

- [ ] **Step 4: Verify container networking and recovery**

    docker compose exec backend python -c "from app.core.config import get_settings; print(get_settings().require_database_url().split('@', 1)[1].split(':', 1)[0])"
    docker compose restart postgres
    docker compose ps
    Invoke-RestMethod http://localhost:8000/api/v1/health

Expected: first command prints exactly postgres; after database recovery health returns ok. Never use docker compose down -v in this stage.

- [ ] **Step 5: Commit**

    git add docker-compose.yml .env.example
    git commit -m "feat: orchestrate frontend backend and database"

### Task 5: Document one-command startup and perform final regression

**Files:**
- Modify: README.md

**Interfaces:**
- Produces: newcomer-facing startup, diagnostics, and shutdown instructions.

- [ ] **Step 1: Add Docker-first README instructions**

Before separate local-start sections add heading 一键启动全部服务（Docker） and these commands:

    docker compose up --build
    docker compose up --build -d
    docker compose ps
    docker compose logs -f backend
    docker compose down

Document:

    前端：     http://localhost:3000
    后端文档： http://localhost:8000/docs
    健康检查： http://localhost:8000/api/v1/health

Explain that /health/db is the host-development database probe; /api/v1/health is Compose readiness.

- [ ] **Step 2: Correct host-name documentation**

Use this exact statement:

    后端跑在 Windows 宿主机时使用 DATABASE_URL（主机名 localhost）；后端跑在 Docker Compose 时使用 DATABASE_URL_DOCKER（主机名 postgres）。两者不能混用。

- [ ] **Step 3: Run final checks and inspect secret safety**

    cd backend
    pytest tests/test_health.py -v
    cd ..\frontend
    npm run lint
    npm run build
    cd ..
    docker compose up --build -d
    docker compose ps
    Invoke-RestMethod http://localhost:8000/api/v1/health
    git status --short
    git check-ignore -v .env

Expected: tests/lint/build pass; three containers healthy; health succeeds; .env is ignored and absent from status.

- [ ] **Step 4: Commit the runbook after staged-diff review**

    git add README.md
    git diff --cached -- . ':!*.lock'
    git commit -m "docs: document one-command Docker startup"

Before commit, ensure staged changes have no real key, real password, or resolved real DSN.

## Self-Review

Spec coverage: backend Dockerfile is Task 2; frontend Dockerfile is Task 3; Compose and dependency health chain are Task 4; unified health is Task 1; one-command startup is Tasks 4 and 5; secret exclusion is Tasks 2 and 5.

Type consistency: Task 1 creates /api/v1/health, Task 4 uses it for the Compose backend health check, and Task 5 documents it. Task 3 enables standalone output before its Dockerfile copies .next/standalone. Task 4 defines DATABASE_URL_DOCKER before Compose consumes it.

## Execution Handoff

Plan complete and saved to docs/superpowers/plans/2026-09-22-containerize-local-services.md. Please review the plan and choose an execution method.

- Subagent-driven: independent implementation and review for every task; most thorough.
- Native: execute the dependent tasks in one workspace, then perform one whole-project review; faster and better suited to the tightly coupled Docker, health-check, and environment-variable changes.

I recommend Native. Does the plan capture what you want, and which approach should we use?


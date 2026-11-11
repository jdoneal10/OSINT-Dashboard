# ADR 0001 — Local runtime: PostGIS in Docker, services native

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

The project runs on one Mac Mini (Apple Silicon) for one analyst. Phase 0 needs `make dev` to bring up the database, API, worker and web UI. Later phases run a local model (MLX) for relevance filtering, and MLX needs the Metal GPU, which containers on macOS can't reach.

## Decision

- **Container runtime:** OrbStack. It is light, fast on Apple Silicon, and works with the `docker compose` CLI.
- **Compose runs only PostgreSQL 16 + PostGIS 3.5.** The image is `imresamu/postgis:16-3.5`, a multi-arch build of the docker-postgis images published by one of their maintainers. The official `postgis/postgis` image ships amd64 only, which would need Rosetta emulation. CI uses the same image.
- **The API (uvicorn), worker (APScheduler) and web (Vite) run natively** under `honcho` (`Procfile.dev`). This gives fast reloads, and the worker can later reach MLX on the GPU.
- **Everything binds to loopback:** Postgres on `127.0.0.1:5432`, the API on `127.0.0.1:8000`, Vite on `127.0.0.1:5173`. The database credential in Compose is a local-only development value.
- **The browser reaches the API through Vite's `/api` proxy.** CORS also allows only the Vite origin, as a backstop.

## Consequences

- One `make dev` starts all four processes, and Ctrl+C stops the three native ones. The database container keeps running until `make db-down`.
- A public or hosted demo (Phase 5) will need its own deployment decision. Nothing here is designed for exposure beyond localhost.

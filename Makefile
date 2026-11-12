# Cartel OSINT Dashboard — developer commands.
# Postgres/PostGIS runs in Docker Compose; api, worker and web run natively (ADR 0001).

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND  := cd backend &&
FRONTEND := cd frontend &&
UV       := uv run

SOURCE  ?=
SINCE   ?=
FILE    ?=
ALL     ?=
DELETED ?=

.PHONY: help setup dev db-up db-down db-reset db-migrate seed basemap \
        test test-backend test-frontend lint lint-backend lint-frontend fmt ingest

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend/frontend deps and pre-commit hooks
	$(BACKEND) uv sync
	$(FRONTEND) npm install
	uv tool install pre-commit
	pre-commit install

dev: db-up db-migrate ## Start db, api, worker and web
	uv run --project backend honcho start -f Procfile.dev

db-up: ## Start PostGIS and wait until healthy
	docker compose up -d --wait db

db-down: ## Stop PostGIS (data volume is kept)
	docker compose down

db-reset: ## Destroy the PostGIS volume and recreate it (asks first)
	@read -p "Delete ALL local database data? [y/N] " ans && [ "$$ans" = "y" ]
	docker compose down -v
	$(MAKE) db-up db-migrate

db-migrate: ## Apply Alembic migrations
	$(BACKEND) $(UV) alembic upgrade head

seed: ## Load cited reference data from data/reference (idempotent)
	$(BACKEND) $(UV) python -m app.reference.load

basemap: ## One-time: extract the local Protomaps basemap for the AOI
	./scripts/basemap.sh

test: test-backend test-frontend ## Run all tests

test-backend:
	$(BACKEND) $(UV) pytest

test-frontend:
	$(FRONTEND) npm test

lint: lint-backend lint-frontend ## ruff, mypy, eslint, prettier --check

lint-backend:
	$(BACKEND) $(UV) ruff check .
	$(BACKEND) $(UV) ruff format --check .
	$(BACKEND) $(UV) mypy

lint-frontend:
	$(FRONTEND) npm run lint
	$(FRONTEND) npm run format:check
	$(FRONTEND) npm run typecheck

fmt: ## Auto-format backend and frontend
	$(BACKEND) $(UV) ruff check --fix .
	$(BACKEND) $(UV) ruff format .
	$(FRONTEND) npm run format

ingest: ## Run one ingester: make ingest SOURCE=acled SINCE=2026-01-01 (see app/ingest/__main__.py)
	$(BACKEND) $(UV) python -m app.ingest $(SOURCE) $(if $(SINCE),--since $(SINCE),) \
		$(if $(FILE),--file "$(CURDIR)/$(FILE)",) $(if $(ALL),--all,) $(if $(DELETED),--deleted,)

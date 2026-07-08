.PHONY: help install dev backend frontend db migrate clean test lint docker-build docker-up docker-down

PYTHON := python
VENV := .venv
VENV_PYTHON := $(VENV)/Scripts/python.exe
VENV_PIP := $(VENV)/Scripts/pip.exe
BACKEND_DIR := backend
FRONTEND_DIR := frontend

# Default target
help:
	@echo "SignalForge Development Commands"
	@echo "================================"
	@echo "  make install      - Create venv and install dependencies"
	@echo "  make dev          - Start backend + frontend in parallel (requires tmux or new terminals)"
	@echo "  make backend      - Start backend server with auto-reload"
	@echo "  make frontend     - Start frontend dev server"
	@echo "  make db           - Start PostgreSQL + Redis via Docker Compose"
	@echo "  make migrate      - Run Alembic database migrations"
	@echo "  make clean        - Remove __pycache__, .pyc files"
	@echo "  make test         - Run backend tests"
	@echo "  make lint         - Run ruff linter on backend"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-up    - Start full stack with Docker Compose"
	@echo "  make docker-down  - Stop Docker Compose stack"

# Installation
install:
	cd $(BACKEND_DIR) && $(PYTHON) -m venv $(VENV)
	cd $(BACKEND_DIR) && $(VENV_PIP) install -r requirements.txt
	cd $(FRONTEND_DIR) && npm install

# Development servers
backend:
	cd $(BACKEND_DIR) && $(VENV_PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd $(FRONTEND_DIR) && npm run dev

dev:
	@echo "Starting backend and frontend..."
	@echo "Open two terminals and run:"
	@echo "  make backend"
	@echo "  make frontend"

# Database
migrate:
	cd $(BACKEND_DIR) && $(VENV_PYTHON) -m alembic upgrade head

db:
	docker compose -f docker-compose.dev.yml up -d postgres redis

db-stop:
	docker compose -f docker-compose.dev.yml down

# Testing
test:
	cd $(BACKEND_DIR) && $(VENV_PYTHON) -m pytest -xvs

# Linting
lint:
	cd $(BACKEND_DIR) && $(VENV_PYTHON) -m ruff check app

# Cleanup
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".DS_Store" -delete 2>/dev/null || true

# Docker
docker-build:
	docker build -t signalforge:latest -f $(BACKEND_DIR)/Dockerfile $(BACKEND_DIR)

# Full production-like stack (Postgres + Redis + backend + nginx frontend).
# Uses -f docker-compose.yml explicitly so the local dev override
# (SQLite + no frontend) is NOT auto-merged.
docker-up:
	docker compose -f docker-compose.yml up -d --build

docker-down:
	docker compose -f docker-compose.yml down

docker-logs:
	docker compose -f docker-compose.yml logs -f

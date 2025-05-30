# Makefile for News Aggregation Service
.PHONY: help build up down logs shell test clean restart

# Default target
help: ## Show this help message
	@echo "News Aggregation Service - Docker Commands"
	@echo "============================================="
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Development commands
build: ## Build all Docker images
	docker-compose build

up: ## Start all services in development mode
	docker-compose up -d
	@echo "Waiting for services to be ready..."
	@sleep 10
	@make health

down: ## Stop all services
	docker-compose down

restart: ## Restart all services
	docker-compose restart

logs: ## Show logs for all services
	docker-compose logs -f

logs-api: ## Show API logs
	docker-compose logs -f api

logs-worker: ## Show Celery worker logs
	docker-compose logs -f celery-worker

logs-beat: ## Show Celery beat logs
	docker-compose logs -f celery-beat

# Service-specific commands
shell: ## Get shell access to API container
	docker-compose exec api /bin/bash

shell-worker: ## Get shell access to worker container
	docker-compose exec celery-worker /bin/bash

redis-cli: ## Connect to Redis CLI
	docker-compose exec redis redis-cli

# Database commands
migrate: ## Run database migrations
	docker-compose exec api alembic upgrade head

migrate-down: ## Rollback last migration
	docker-compose exec api alembic downgrade -1

db-init: ## Initialize database with seed data
	docker-compose exec api python -c "import sys; sys.path.append('/app'); from src.db.operations import initialize_db; initialize_db()"

# Testing
test: ## Run tests in container
	docker-compose exec api python -m pytest tests/ -v

test-coverage: ## Run tests with coverage
	docker-compose exec api python -m pytest tests/ --cov=src --cov-report=html

# Health checks
health: ## Check health of all services
	@echo "Checking service health..."
	@docker-compose exec redis redis-cli ping > /dev/null 2>&1 && echo "✅ Redis: OK" || echo "❌ Redis: FAIL"
	@curl -f http://localhost:7700/health > /dev/null 2>&1 && echo "✅ MeiliSearch: OK" || echo "❌ MeiliSearch: FAIL"
	@curl -f http://localhost:8000/api/v1/health/ > /dev/null 2>&1 && echo "✅ API: OK" || echo "❌ API: FAIL"

# Cleanup
clean: ## Remove all containers, volumes, and images
	docker-compose down -v --rmi all
	docker system prune -f

clean-volumes: ## Remove all volumes (WARNING: This will delete all data)
	docker-compose down -v

# Production commands
prod-build: ## Build production images
	docker-compose -f docker-compose.prod.yml build

prod-up: ## Start production services
	docker-compose -f docker-compose.prod.yml up -d

prod-down: ## Stop production services
	docker-compose -f docker-compose.prod.yml down

prod-logs: ## Show production logs
	docker-compose -f docker-compose.prod.yml logs -f

# Monitoring
stats: ## Show container resource usage
	docker stats

ps: ## Show running containers
	docker-compose ps

# Import data
import-articles: ## Import articles to MeiliSearch
	docker-compose exec api python scripts/import_to_meilisearch.py

# Backup and restore (production)
backup-db: ## Backup database (production only)
	docker-compose -f docker-compose.prod.yml exec postgres pg_dump -U $$POSTGRES_USER -d $$POSTGRES_DB > backups/backup_$$(date +%Y%m%d_%H%M%S).sql

# Development setup
setup: ## Initial setup for development
	@echo "Setting up development environment..."
	@make build
	@make up
	@make migrate
	@make db-init
	@echo "✅ Development environment ready!"

# Quick start for new developers
quick-start: ## Quick start guide for new developers
	@echo "🚀 Quick Start Guide"
	@echo "==================="
	@echo "1. make setup      - Initial setup"
	@echo "2. make logs       - View logs"
	@echo "3. make test       - Run tests"
	@echo "4. make health     - Check service health"
	@echo ""
	@echo "Services will be available at:"
	@echo "- API: http://localhost:8000"
	@echo "- Docs: http://localhost:8000/docs"
	@echo "- MeiliSearch: http://localhost:7700"

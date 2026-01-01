# Polymarket MCP Server - Makefile
# Convenient commands for Docker operations

.PHONY: help build up down restart logs logs-tail ps stats test clean clean-all start shell build-multi push deploy-k8s undeploy-k8s validate env health update backup restore

# Default target
.DEFAULT_GOAL := help

# Variables
DOCKER_COMPOSE := docker compose
SERVICE_NAME := polymarket-mcp
IMAGE_NAME := polymarket-mcp
# Version derived from the package source of truth (src/polymarket_mcp/__init__.py;
# pyproject hatch reads the same file), so build-multi/push tags never drift.
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' src/polymarket_mcp/__init__.py)

## help: Show this help message
help:
	@echo "Polymarket MCP Server - Docker Commands"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@awk '/^##/ {desc = substr($$0, 4); getline; printf "  \033[36m%-15s\033[0m %s\n", $$1, desc}' $(MAKEFILE_LIST)

## build: Build Docker image
build:
	@echo "Building Docker image..."
	$(DOCKER_COMPOSE) build

## up: Start services
up:
	@echo "Starting services..."
	$(DOCKER_COMPOSE) up -d

## down: Stop services
down:
	@echo "Stopping services..."
	$(DOCKER_COMPOSE) down

## restart: Restart services
restart:
	@echo "Restarting services..."
	$(DOCKER_COMPOSE) restart

## logs: View logs (follow mode)
logs:
	$(DOCKER_COMPOSE) logs -f

## logs-tail: View last 50 lines of logs
logs-tail:
	$(DOCKER_COMPOSE) logs --tail=50

## shell: Open shell in container
shell:
	$(DOCKER_COMPOSE) exec $(SERVICE_NAME) /bin/bash

## ps: Show running containers
ps:
	$(DOCKER_COMPOSE) ps

## stats: Show resource usage
stats:
	docker stats $(SERVICE_NAME) --no-stream

## test: Run Docker infrastructure tests
test:
	./test-docker.sh

## clean: Remove containers and volumes
clean:
	@echo "Cleaning up..."
	$(DOCKER_COMPOSE) down -v
	docker rmi $(IMAGE_NAME):latest || true

## clean-all: Remove everything including images
clean-all: clean
	docker system prune -af

## start: Quick start with environment check
start:
	./docker-start.sh

## build-multi: Build multi-architecture image
build-multi:
	docker buildx build --platform linux/amd64,linux/arm64 \
		-t $(IMAGE_NAME):$(VERSION) \
		-t $(IMAGE_NAME):latest .

## push: Push image to registry (set REGISTRY variable)
push:
	@if [ -z "$(REGISTRY)" ]; then \
		echo "Error: REGISTRY not set. Use: make push REGISTRY=your-registry/polymarket-mcp"; \
		exit 1; \
	fi
	docker tag $(IMAGE_NAME):latest $(REGISTRY):latest
	docker tag $(IMAGE_NAME):latest $(REGISTRY):$(VERSION)
	docker push $(REGISTRY):latest
	docker push $(REGISTRY):$(VERSION)

## deploy-k8s: Deploy to Kubernetes
deploy-k8s:
	@echo "Deploying to Kubernetes..."
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/deployment.yaml
	kubectl apply -f k8s/service.yaml

## undeploy-k8s: Remove from Kubernetes
undeploy-k8s:
	kubectl delete -f k8s/

## validate: Validate configuration files
validate:
	@echo "Validating docker-compose.yml..."
	$(DOCKER_COMPOSE) config > /dev/null
	@echo "✓ docker-compose.yml is valid"
	@if command -v kubectl > /dev/null; then \
		echo "Validating Kubernetes manifests..."; \
		kubectl apply --dry-run=client -f k8s/ > /dev/null; \
		echo "✓ Kubernetes manifests are valid"; \
	fi

## env: Create .env from template
env:
	@if [ -f .env ]; then \
		echo ".env already exists"; \
	else \
		cp .env.example .env; \
		echo "Created .env from template. Please edit with your credentials."; \
	fi

## health: Check container health
health:
	@docker inspect --format='{{.State.Health.Status}}' $(SERVICE_NAME) 2>/dev/null || echo "Container not running"

## update: Pull latest code and rebuild
update:
	@echo "Updating..."
	git pull
	$(DOCKER_COMPOSE) build
	$(DOCKER_COMPOSE) up -d

## backup: Backup volumes
backup:
	@echo "Backing up volumes..."
	@VOLUME_NAME=$$(docker compose config --format json 2>/dev/null | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("volumes",{}).get("polymarket-data",{}).get("name",""))' 2>/dev/null); \
	if [ -z "$$VOLUME_NAME" ]; then \
		echo "Error: could not resolve the data volume name"; \
		exit 1; \
	fi; \
	mkdir -p backups; \
	docker run --rm -v "$$VOLUME_NAME":/data -v $(CURDIR)/backups:/backup alpine tar czf /backup/data-backup-$$(date +%Y%m%d-%H%M%S).tar.gz -C /data .
	@echo "Backup complete"

## restore: Restore volumes from latest backup
restore:
	@if [ ! -d backups ] || [ -z "$$(ls backups/*.tar.gz 2>/dev/null)" ]; then \
		echo "No backups found"; \
		exit 1; \
	fi
	@VOLUME_NAME=$$(docker compose config --format json 2>/dev/null | python3 -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("volumes",{}).get("polymarket-data",{}).get("name",""))' 2>/dev/null); \
	if [ -z "$$VOLUME_NAME" ]; then \
		echo "Error: could not resolve the data volume name"; \
		exit 1; \
	fi; \
	LATEST=$$(ls -t backups/*.tar.gz | head -1); \
	echo "Restoring from $$LATEST..."; \
	docker run --rm -v "$$VOLUME_NAME":/data -v $(CURDIR)/backups:/backup alpine tar xzf /backup/$$(basename $$LATEST) -C /data
	@echo "Restore complete"

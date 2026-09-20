.PHONY: up down logs api-test api-lint web-lint web-typecheck migrate seed

up:            ## Start the full local stack
	docker compose up --build

down:          ## Stop the stack
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:       ## Run database migrations inside the api container
	docker compose exec api alembic upgrade head

migration:     ## Autogenerate a migration: make migration m="add x"
	docker compose exec api alembic revision --autogenerate -m "$(m)"

api-test:      ## Run backend tests (local venv)
	cd apps/api && .venv/bin/python -m pytest -q

api-lint:
	cd apps/api && .venv/bin/ruff check cutpilot tests && .venv/bin/ruff format --check cutpilot tests

web-lint:
	cd apps/web && npm run lint

web-typecheck:
	cd apps/web && npm run typecheck

web-test:
	cd apps/web && npm test

test: api-test web-test  ## Run all tests

docker-build:
	docker compose build

docker-test:   ## Smoke-test the running stack
	curl -fsS localhost:8000/api/ready && echo && curl -fsS -o /dev/null -w "web %{http_code}\n" localhost:3000/login

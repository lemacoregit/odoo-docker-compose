# =============================================================================
# Odoo Docker Compose — Makefile
# Services: odoo-lema (production), odoo-demo18e, odoo-demo18c
# =============================================================================

COMPOSE         := docker compose
ENV_FILE        := .env
COMPOSE_FILE    := docker-compose.yml
SCRIPT_DIR      := github/script
UPGRADE_SCRIPT  := $(SCRIPT_DIR)/upgrade_modules.py

# Load .env so variables are available in targets that need them
ifneq (,$(wildcard $(ENV_FILE)))
  include $(ENV_FILE)
  export
endif

# Terminal colors
BOLD  := \033[1m
RED   := \033[31m
GRN   := \033[32m
YLW   := \033[33m
BLU   := \033[34m
RST   := \033[0m

# =============================================================================
# DEFAULT: help
# =============================================================================
.PHONY: help
help:
	@echo ""
	@echo "$(BOLD)Odoo Docker Compose$(RST)"
	@echo "$(BLU)════════════════════════════════════════════════════════$(RST)"
	@echo ""
	@echo "$(BOLD)Environment$(RST)"
	@echo "  setup          Copy .env.example to .env + chmod scripts"
	@echo "  validate-env   Verify required .env variables are set"
	@echo "  chmod-scripts  Fix permissions on all .sh files"
	@echo ""
	@echo "$(BOLD)All Services$(RST)"
	@echo "  up             chmod scripts + start all services (detached)"
	@echo "  down           Stop and remove all containers"
	@echo "  restart        Restart all services"
	@echo "  ps             Show service status"
	@echo "  pull           Pull latest images"
	@echo "  build          Build / rebuild custom images"
	@echo ""
	@echo "$(BOLD)Lema — Production$(RST)"
	@echo "  start-lema     Start odoo-lema"
	@echo "  stop-lema      Stop odoo-lema"
	@echo "  restart-lema   Restart odoo-lema"
	@echo "  logs-lema      Tail logs for odoo-lema"
	@echo "  shell-lema     Open bash inside odoo-lema container"
	@echo "  health-lema    Check odoo-lema health endpoint"
	@echo ""
	@echo "$(BOLD)Demo 18 Enterprise$(RST)"
	@echo "  start-demo18e  Start odoo-demo18e"
	@echo "  stop-demo18e   Stop odoo-demo18e"
	@echo "  restart-demo18e  Restart odoo-demo18e"
	@echo "  logs-demo18e   Tail logs for odoo-demo18e"
	@echo "  shell-demo18e  Open bash inside odoo-demo18e container"
	@echo "  health-demo18e Check odoo-demo18e health endpoint"
	@echo ""
	@echo "$(BOLD)Demo 18 Community$(RST)"
	@echo "  start-demo18c  Start odoo-demo18c"
	@echo "  stop-demo18c   Stop odoo-demo18c"
	@echo "  restart-demo18c  Restart odoo-demo18c"
	@echo "  logs-demo18c   Tail logs for odoo-demo18c"
	@echo "  shell-demo18c  Open bash inside odoo-demo18c container"
	@echo "  health-demo18c Check odoo-demo18c health endpoint"
	@echo ""
	@echo "$(BOLD)Infrastructure$(RST)"
	@echo "  start-db       Start PostgreSQL + PgBouncer"
	@echo "  stop-db        Stop PostgreSQL + PgBouncer"
	@echo "  start-redis    Start Redis"
	@echo "  stop-redis     Stop Redis"
	@echo "  restart-redis  Restart Redis"
	@echo "  logs-db        Tail logs for PostgreSQL"
	@echo "  logs-pgbouncer Tail logs for PgBouncer"
	@echo "  logs-redis     Tail logs for Redis"
	@echo ""
	@echo "$(BOLD)Database$(RST)"
	@echo "  db-shell       Open psql shell (via PgBouncer)"
	@echo "  db-shell-direct Open psql shell (direct to PostgreSQL)"
	@echo "  db-list        List all databases"
	@echo "  db-backup DB=<name>   Dump database to backups/<name>_<date>.sql"
	@echo "  db-restore DB=<name> FILE=<path>  Restore database from SQL file"
	@echo ""
	@echo "$(BOLD)Redis$(RST)"
	@echo "  redis-cli      Open Redis CLI"
	@echo "  redis-info     Show Redis server info"
	@echo "  redis-sessions Show session key count"
	@echo "  redis-flush-db Flush only Odoo session keys (use with care)"
	@echo ""
	@echo "$(BOLD)Modules$(RST)"
	@echo "  upgrade MODULES=<m1,m2> [SERVICE=lema|demo18e|demo18c]"
	@echo "                 Upgrade modules via XML-RPC"
	@echo "  upgrade-dry    Dry-run: list modules without upgrading"
	@echo "                 (same MODULES + SERVICE vars)"
	@echo ""
	@echo "$(BOLD)Cleanup$(RST)"
	@echo "  clean          Remove stopped containers and dangling images"
	@echo "  clean-logs     Truncate all Odoo log files"
	@echo "  clean-sessions Flush Redis Odoo session keys"
	@echo "  prune          docker system prune (removes all unused resources)"
	@echo ""
	@echo "$(BOLD)Misc$(RST)"
	@echo "  logs           Tail all service logs"
	@echo "  top            Live resource usage for all containers"
	@echo "  stats          Snapshot resource usage"
	@echo "  version        Show running Odoo version per service"
	@echo ""

# =============================================================================
# ENVIRONMENT
# =============================================================================
.PHONY: setup validate-env chmod-scripts

chmod-scripts:
	@echo "$(BLU)Setting permissions on shell scripts...$(RST)"
	@find . -name "*.sh" \
	  -not -path "./.git/*" \
	  -exec chmod 777 {} \;
	@echo "$(GRN)Done.$(RST)"

setup: chmod-scripts
	@if [ -f "$(ENV_FILE)" ]; then \
	  echo "$(YLW)$(ENV_FILE) already exists — skipping. Delete it first to reset.$(RST)"; \
	else \
	  cp .env.example $(ENV_FILE); \
	  echo "$(GRN)Created $(ENV_FILE) from .env.example — edit it before running 'make up'.$(RST)"; \
	fi

validate-env:
	@echo "Validating $(ENV_FILE)..."
	@MISSING=""; \
	for VAR in \
	    POSTGRES_PASSWORD POSTGRES_USER \
	    ODOO_LEMA_HTTP_PORT ODOO_LEMA_LONGPOLLING_PORT \
	    ODOO_DEMO18E_HTTP_PORT ODOO_DEMO18E_LONGPOLLING_PORT \
	    ODOO_DEMO18C_HTTP_PORT ODOO_DEMO18C_LONGPOLLING_PORT \
	    ODOO_SESSION_REDIS_PASSWORD REDIS_EXTERNAL_PORT; do \
	  VAL=$$(grep -E "^$${VAR}=" $(ENV_FILE) 2>/dev/null | cut -d= -f2-); \
	  if [ -z "$$VAL" ]; then MISSING="$$MISSING $$VAR"; fi; \
	done; \
	if [ -n "$$MISSING" ]; then \
	  echo "$(RED)Missing or empty variables:$(RST)$$MISSING"; \
	  exit 1; \
	else \
	  echo "$(GRN)All required variables are set.$(RST)"; \
	fi

# =============================================================================
# ALL SERVICES
# =============================================================================
.PHONY: up down restart ps pull build logs top stats
up: chmod-scripts
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

ps:
	$(COMPOSE) ps

pull:
	$(COMPOSE) pull

build:
	$(COMPOSE) build --no-cache

logs:
	$(COMPOSE) logs -f --tail=100

top:
	$(COMPOSE) top

stats:
	docker stats --no-stream $$($(COMPOSE) ps -q)

# =============================================================================
# LEMA — PRODUCTION
# =============================================================================
.PHONY: start-lema stop-lema restart-lema logs-lema shell-lema health-lema
start-lema:
	$(COMPOSE) up -d odoo-lema

stop-lema:
	$(COMPOSE) stop odoo-lema

restart-lema:
	$(COMPOSE) restart odoo-lema

logs-lema:
	$(COMPOSE) logs -f --tail=100 odoo-lema

shell-lema:
	$(COMPOSE) exec odoo-lema bash

health-lema:
	@PORT=$${ODOO_LEMA_HTTP_PORT:-8018}; \
	echo "Checking http://localhost:$$PORT/web/health ..."; \
	HTTP=$$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" "http://localhost:$$PORT/web/health" 2>/dev/null || echo "000"); \
	if [ "$$HTTP" = "200" ]; then \
	  echo "$(GRN)odoo-lema is healthy (HTTP $$HTTP)$(RST)"; \
	else \
	  echo "$(RED)odoo-lema is NOT healthy (HTTP $$HTTP)$(RST)"; exit 1; \
	fi

# =============================================================================
# DEMO 18 ENTERPRISE
# =============================================================================
.PHONY: start-demo18e stop-demo18e restart-demo18e logs-demo18e shell-demo18e health-demo18e
start-demo18e:
	$(COMPOSE) up -d odoo-demo18e

stop-demo18e:
	$(COMPOSE) stop odoo-demo18e

restart-demo18e:
	$(COMPOSE) restart odoo-demo18e

logs-demo18e:
	$(COMPOSE) logs -f --tail=100 odoo-demo18e

shell-demo18e:
	$(COMPOSE) exec odoo-demo18e bash

health-demo18e:
	@PORT=$${ODOO_DEMO18E_HTTP_PORT:-8118}; \
	echo "Checking http://localhost:$$PORT/web/health ..."; \
	HTTP=$$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" "http://localhost:$$PORT/web/health" 2>/dev/null || echo "000"); \
	if [ "$$HTTP" = "200" ]; then \
	  echo "$(GRN)odoo-demo18e is healthy (HTTP $$HTTP)$(RST)"; \
	else \
	  echo "$(RED)odoo-demo18e is NOT healthy (HTTP $$HTTP)$(RST)"; exit 1; \
	fi

# =============================================================================
# DEMO 18 COMMUNITY
# =============================================================================
.PHONY: start-demo18c stop-demo18c restart-demo18c logs-demo18c shell-demo18c health-demo18c
start-demo18c:
	$(COMPOSE) up -d odoo-demo18c

stop-demo18c:
	$(COMPOSE) stop odoo-demo18c

restart-demo18c:
	$(COMPOSE) restart odoo-demo18c

logs-demo18c:
	$(COMPOSE) logs -f --tail=100 odoo-demo18c

shell-demo18c:
	$(COMPOSE) exec odoo-demo18c bash

health-demo18c:
	@PORT=$${ODOO_DEMO18C_HTTP_PORT:-8218}; \
	echo "Checking http://localhost:$$PORT/web/health ..."; \
	HTTP=$$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" "http://localhost:$$PORT/web/health" 2>/dev/null || echo "000"); \
	if [ "$$HTTP" = "200" ]; then \
	  echo "$(GRN)odoo-demo18c is healthy (HTTP $$HTTP)$(RST)"; \
	else \
	  echo "$(RED)odoo-demo18c is NOT healthy (HTTP $$HTTP)$(RST)"; exit 1; \
	fi

# =============================================================================
# INFRASTRUCTURE
# =============================================================================
.PHONY: start-db stop-db start-redis stop-redis restart-redis
.PHONY: logs-db logs-pgbouncer logs-redis

start-db:
	$(COMPOSE) up -d db pgbouncer

stop-db:
	$(COMPOSE) stop db pgbouncer

start-redis:
	$(COMPOSE) up -d redis

stop-redis:
	$(COMPOSE) stop redis

restart-redis:
	$(COMPOSE) restart redis

logs-db:
	$(COMPOSE) logs -f --tail=100 db

logs-pgbouncer:
	$(COMPOSE) logs -f --tail=100 pgbouncer

logs-redis:
	$(COMPOSE) logs -f --tail=100 redis

# =============================================================================
# DATABASE
# =============================================================================
.PHONY: db-shell db-shell-direct db-list db-backup db-restore

db-shell:
	@echo "$(BLU)Connecting via PgBouncer (port $${PG_BOUNCER_PORT:-8765})...$(RST)"
	$(COMPOSE) exec pgbouncer psql \
	  -h localhost \
	  -p $${PG_BOUNCER_PORT:-8765} \
	  -U $${POSTGRES_USER:-odoo} \
	  $${POSTGRES_DB:-postgres}

db-shell-direct:
	@echo "$(BLU)Connecting directly to PostgreSQL...$(RST)"
	$(COMPOSE) exec db psql -U $${POSTGRES_USER:-odoo}

db-list:
	$(COMPOSE) exec db psql -U $${POSTGRES_USER:-odoo} -c "\l"

db-backup:
	@if [ -z "$(DB)" ]; then echo "$(RED)Usage: make db-backup DB=<database_name>$(RST)"; exit 1; fi
	@mkdir -p backups
	@TIMESTAMP=$$(date +%Y%m%d_%H%M%S); \
	FILE="backups/$(DB)_$${TIMESTAMP}.sql"; \
	echo "$(BLU)Dumping $(DB) -> $$FILE ...$(RST)"; \
	$(COMPOSE) exec -T db pg_dump -U $${POSTGRES_USER:-odoo} $(DB) > "$$FILE"; \
	echo "$(GRN)Backup saved: $$FILE ($$(du -sh $$FILE | cut -f1))$(RST)"

db-restore:
	@if [ -z "$(DB)" ] || [ -z "$(FILE)" ]; then \
	  echo "$(RED)Usage: make db-restore DB=<database_name> FILE=<path/to/file.sql>$(RST)"; exit 1; \
	fi
	@echo "$(YLW)Restoring $(FILE) -> $(DB) ...$(RST)"
	$(COMPOSE) exec -T db psql -U $${POSTGRES_USER:-odoo} $(DB) < "$(FILE)"
	@echo "$(GRN)Restore complete.$(RST)"

# =============================================================================
# REDIS
# =============================================================================
.PHONY: redis-cli redis-info redis-sessions redis-flush-db

redis-cli:
	$(COMPOSE) exec redis redis-cli -a "$${ODOO_SESSION_REDIS_PASSWORD}"

redis-info:
	$(COMPOSE) exec redis redis-cli -a "$${ODOO_SESSION_REDIS_PASSWORD}" --no-auth-warning info server

redis-sessions:
	@PREFIX=$${ODOO_SESSION_REDIS_PREFIX:-mazuta}; \
	echo "$(BLU)Session keys with prefix '$$PREFIX:*' ...$(RST)"; \
	$(COMPOSE) exec -T redis redis-cli -a "$${ODOO_SESSION_REDIS_PASSWORD}" --no-auth-warning \
	  eval "return #redis.call('keys', ARGV[1])" 0 "$$PREFIX:*"

redis-flush-db:
	@echo "$(YLW)WARNING: This will delete all Odoo session keys from Redis.$(RST)"
	@read -p "Type 'yes' to confirm: " CONFIRM; \
	if [ "$$CONFIRM" = "yes" ]; then \
	  PREFIX=$${ODOO_SESSION_REDIS_PREFIX:-mazuta}; \
	  $(COMPOSE) exec -T redis redis-cli -a "$${ODOO_SESSION_REDIS_PASSWORD}" --no-auth-warning \
	    eval "local keys = redis.call('keys', ARGV[1]) for _, k in ipairs(keys) do redis.call('del', k) end return #keys" \
	    0 "$$PREFIX:*"; \
	  echo "$(GRN)Done.$(RST)"; \
	else \
	  echo "Aborted."; \
	fi

# =============================================================================
# MODULES
# =============================================================================
.PHONY: upgrade upgrade-dry

upgrade:
	@if [ -z "$(MODULES)" ]; then echo "$(RED)Usage: make upgrade MODULES=<m1,m2> [SERVICE=lema|demo18e|demo18c]$(RST)"; exit 1; fi
	@SVC=$${SERVICE:-lema}; \
	case "$$SVC" in \
	  lema)    URL="http://localhost:$${ODOO_LEMA_HTTP_PORT:-8018}";    DB="$${ODOO_LEMA_DB:-lema_production}" ;; \
	  demo18e) URL="http://localhost:$${ODOO_DEMO18E_HTTP_PORT:-8118}"; DB="$${ODOO_DEMO18E_DB:-lema_demo18e}" ;; \
	  demo18c) URL="http://localhost:$${ODOO_DEMO18C_HTTP_PORT:-8218}"; DB="$${ODOO_DEMO18C_DB:-lema_demo18c}" ;; \
	  *) echo "$(RED)Unknown SERVICE: $$SVC (use lema|demo18e|demo18c)$(RST)"; exit 1 ;; \
	esac; \
	echo "$(BLU)Upgrading [$(MODULES)] on $$SVC ($$URL / $$DB)...$(RST)"; \
	python3 $(UPGRADE_SCRIPT) \
	  --url "$$URL" \
	  --db "$$DB" \
	  --user "$${ODOO_ADMIN_USER:-admin}" \
	  --password "$${ODOO_ADMIN_PASSWORD}" \
	  --modules "$(MODULES)"

upgrade-dry:
	@if [ -z "$(MODULES)" ]; then echo "$(RED)Usage: make upgrade-dry MODULES=<m1,m2> [SERVICE=lema|demo18e|demo18c]$(RST)"; exit 1; fi
	@SVC=$${SERVICE:-lema}; \
	case "$$SVC" in \
	  lema)    URL="http://localhost:$${ODOO_LEMA_HTTP_PORT:-8018}";    DB="$${ODOO_LEMA_DB:-lema_production}" ;; \
	  demo18e) URL="http://localhost:$${ODOO_DEMO18E_HTTP_PORT:-8118}"; DB="$${ODOO_DEMO18E_DB:-lema_demo18e}" ;; \
	  demo18c) URL="http://localhost:$${ODOO_DEMO18C_HTTP_PORT:-8218}"; DB="$${ODOO_DEMO18C_DB:-lema_demo18c}" ;; \
	  *) echo "$(RED)Unknown SERVICE: $$SVC (use lema|demo18e|demo18c)$(RST)"; exit 1 ;; \
	esac; \
	echo "$(BLU)[DRY RUN] Modules: $(MODULES) | Service: $$SVC | URL: $$URL | DB: $$DB$(RST)"; \
	python3 $(UPGRADE_SCRIPT) \
	  --url "$$URL" \
	  --db "$$DB" \
	  --user "$${ODOO_ADMIN_USER:-admin}" \
	  --password "$${ODOO_ADMIN_PASSWORD}" \
	  --modules "$(MODULES)" \
	  --dry-run

# =============================================================================
# CLEANUP
# =============================================================================
.PHONY: clean clean-logs clean-sessions prune

clean:
	$(COMPOSE) rm -f
	docker image prune -f

clean-logs:
	@echo "$(YLW)Truncating Odoo log files...$(RST)"
	@find etc/ -name "*.log" -exec truncate -s 0 {} \; 2>/dev/null || true
	@echo "$(GRN)Log files cleared.$(RST)"

clean-sessions: redis-flush-db

prune:
	@echo "$(YLW)WARNING: This removes ALL unused Docker resources (images, volumes, networks).$(RST)"
	@read -p "Type 'yes' to confirm: " CONFIRM; \
	if [ "$$CONFIRM" = "yes" ]; then \
	  docker system prune -af --volumes; \
	else \
	  echo "Aborted."; \
	fi

# =============================================================================
# MISC
# =============================================================================
.PHONY: version

version:
	@echo "$(BOLD)Odoo versions:$(RST)"
	@$(COMPOSE) exec odoo-lema    odoo --version 2>/dev/null | sed 's/^/  [lema]    /' || true
	@$(COMPOSE) exec odoo-demo18e odoo --version 2>/dev/null | sed 's/^/  [demo18e] /' || true
	@$(COMPOSE) exec odoo-demo18c odoo --version 2>/dev/null | sed 's/^/  [demo18c] /' || true

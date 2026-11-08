#!/usr/bin/env bash
# Seed reference data (providers, packages, pricing, platform admin) and an optional demo workspace.
set -euo pipefail
docker compose run --rm api python -m app.scripts.seed "$@"

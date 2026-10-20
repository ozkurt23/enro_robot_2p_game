#!/usr/bin/env bash
set -Euo pipefail
ENRO_COOP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec bash "$ENRO_COOP_ROOT/v2/run_coop_game.sh" "$@"

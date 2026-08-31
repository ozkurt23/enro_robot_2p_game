#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=runtime_common.sh
source "$SCRIPT_DIR/runtime_common.sh"

MODE="${1:-quick}"
if [[ "$MODE" != "quick" && "$MODE" != "full" ]]; then
    enro_die "Live eval modu quick veya full olmalı"
    exit 2
fi

enro_load_runtime_lock
enro_runtime_paths

python3 "$SCRIPT_DIR/local_ai_probe.py" live-eval

if [[ "$MODE" == "full" ]]; then
    if ! enro_python_env_valid; then
        enro_die "Full eval için pinlenmiş .deps/game-python ortamı hazır değil"
        exit 1
    fi
    export PYTHONPATH="$ENRO_V2_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
    enro_log "Checked-in Türkçe NLU corpus'u canlı Qwen ile değerlendiriliyor"
    "$ENRO_VENV_PYTHON" -m enro_terminal.eval_nlu --backend qwen
fi

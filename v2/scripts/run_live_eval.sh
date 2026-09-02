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
    enro_log "Gerçek persona policy + authorization hattı canlı Qwen ile değerlendiriliyor"
    "$ENRO_VENV_PYTHON" -m enro_terminal.eval_gameplay --backend qwen
    for actor_seed in 180 271 912; do
        enro_log "Yedi persona actor sözleşmesi canlı Qwen ile değerlendiriliyor (seed=$actor_seed)"
        "$ENRO_VENV_PYTHON" -m enro_terminal.eval_personas --seed "$actor_seed"
    done
fi

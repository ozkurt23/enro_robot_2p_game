#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/runtime_common.sh
source "$SCRIPT_DIR/scripts/runtime_common.sh"

usage() {
    cat <<'EOF'
Kullanım:
  ./run_local_ai.sh [--no-warmup] [--gpu-layers all|auto|N]
  ./run_local_ai.sh [--no-warmup] [--gpu-layers all|auto|N] --exec [--] KOMUT [ARG...]
  ./run_local_ai.sh [--gpu-layers all|auto|N] --print-command

Pinlenmiş llama-server'ı yalnız 127.0.0.1 üzerinde, offline/text-only ve
reasoning kapalı profille çalıştırır. --exec kullanıldığında sunucu health ve
warm-up tamamlandıktan sonra komutu çalıştırır; komut bitince veya sinyal
gelince sahip olduğu llama-server child'ını temizler.

İsteğe bağlı ENRO_LLM_API_KEY verilirse server authentication açılır ve --exec
child'ına aynı environment aktarılır.
EOF
}

SKIP_WARMUP=0
PRINT_COMMAND=0
EXEC_MODE=0
GPU_LAYERS=""
COMMAND_ARGS=()
while (($#)); do
    case "$1" in
        --no-warmup)
            SKIP_WARMUP=1
            shift
            ;;
        --print-command)
            PRINT_COMMAND=1
            shift
            ;;
        --gpu-layers)
            [[ $# -ge 2 ]] || {
                enro_die "--gpu-layers bir değer gerektirir"
                exit 2
            }
            GPU_LAYERS="$2"
            shift 2
            ;;
        --exec)
            EXEC_MODE=1
            shift
            [[ "${1:-}" == "--" ]] && shift
            COMMAND_ARGS=("$@")
            break
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            enro_die "Bilinmeyen seçenek: $1"
            exit 2
            ;;
    esac
done
if ((EXEC_MODE)) && ((${#COMMAND_ARGS[@]} == 0)); then
    enro_die "--exec sonrasında bir komut gerekli"
    exit 2
fi

enro_load_runtime_lock
enro_runtime_paths

SERVER_BUILDER_ARGS=(
    --lock "$ENRO_RUNTIME_LOCK"
    --model "$ENRO_MODEL_PATH"
)
[[ -n "$GPU_LAYERS" ]] && SERVER_BUILDER_ARGS+=(--gpu-layers "$GPU_LAYERS")
mapfile -d '' -t SERVER_ARGS < <(
    python3 "$SCRIPT_DIR/scripts/server_args.py" "${SERVER_BUILDER_ARGS[@]}"
)
if ((${#SERVER_ARGS[@]} == 0)); then
    enro_die "llama-server argümanları üretilemedi"
    exit 1
fi

if ((PRINT_COMMAND)); then
    printf '%q ' "$ENRO_LLAMA_SERVER" "${SERVER_ARGS[@]}"
    printf '\n'
    exit 0
fi

enro_require_command flock
enro_require_command setsid
enro_require_command python3
enro_require_command tail

if ! ENRO_QUIET=1 "$SCRIPT_DIR/setup_local_ai.sh" --verify-only --quiet; then
    enro_die "Kurulum doğrulanamadı. Önce çalıştırın: $SCRIPT_DIR/setup_local_ai.sh"
    exit 1
fi

install -d -m 0700 "$ENRO_STATE_ROOT"
exec 9>"$ENRO_STATE_ROOT/llama-server.lock"
if ! flock --nonblock 9; then
    enro_die "Başka bir ENRO llama-server supervisor'ı çalışıyor"
    exit 1
fi

if python3 "$SCRIPT_DIR/scripts/local_ai_probe.py" --quiet health --timeout 1 >/dev/null 2>&1; then
    enro_die "$ENRO_LLM_HEALTH_URL üzerinde zaten bir sunucu var; sahip olmadığımız süreci kullanmayı reddediyoruz"
    exit 1
fi

if [[ -n "${ENRO_LLM_API_KEY:-}" ]]; then
    SERVER_ARGS+=(--api-key "$ENRO_LLM_API_KEY")
    export ENRO_LLM_API_KEY
fi

# Bu makinede birden çok Mesa ICD'si de var. Kullanıcı açıkça başka bir ICD
# seçmediyse NVIDIA'nın kurulu Vulkan ICD'sini daraltarak yanlış GPU seçimini
# önlüyoruz. Hiçbir global ayar değiştirilmez.
if [[ -z "${VK_DRIVER_FILES:-}" && -z "${VK_ICD_FILENAMES:-}" \
    && -f /usr/share/vulkan/icd.d/nvidia_icd.json ]]; then
    export VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.json
    export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json
fi
export LD_LIBRARY_PATH="$ENRO_LLAMA_HOME${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ENRO_LLM_BASE_URL
export ENRO_LLM_API_BASE="$ENRO_LLM_BASE_URL"
export ENRO_LLM_URL="$ENRO_LLM_ROOT_URL"
export ENRO_LLM_MODEL="$ENRO_SERVER_ALIAS"
export ENRO_LLM_MODEL_ALIAS="$ENRO_SERVER_ALIAS"

SERVER_LOG="$ENRO_STATE_ROOT/llama-server.log"
SERVER_PID_FILE="$ENRO_STATE_ROOT/llama-server.pid"
SERVER_PID=""

cleanup() {
    local status=$? elapsed=0
    trap - EXIT INT TERM HUP
    if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
        enro_log "llama-server kapatılıyor (pid=$SERVER_PID)"
        kill -TERM -- "-$SERVER_PID" 2>/dev/null || kill -TERM "$SERVER_PID" 2>/dev/null || true
        while kill -0 "$SERVER_PID" 2>/dev/null \
            && ((elapsed < ENRO_SERVER_SHUTDOWN_TIMEOUT * 10)); do
            sleep 0.1
            ((elapsed += 1))
        done
        if kill -0 "$SERVER_PID" 2>/dev/null; then
            enro_log "Graceful kapanma zaman aşımı; child zorla sonlandırılıyor"
            kill -KILL -- "-$SERVER_PID" 2>/dev/null || kill -KILL "$SERVER_PID" 2>/dev/null || true
        fi
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    if [[ -f "$SERVER_PID_FILE" ]] && [[ "$(<"$SERVER_PID_FILE")" == "$SERVER_PID" ]]; then
        rm -f -- "$SERVER_PID_FILE"
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

: >"$SERVER_LOG"
enro_log "llama.cpp $ENRO_LLAMA_RELEASE/$ENRO_LLAMA_VERSION ($ENRO_LLAMA_BACKEND) başlatılıyor"
setsid "$ENRO_LLAMA_SERVER" "${SERVER_ARGS[@]}" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
printf '%s\n' "$SERVER_PID" >"$SERVER_PID_FILE"

START_SECONDS=$SECONDS
while true; do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        set +e
        wait "$SERVER_PID"
        SERVER_STATUS=$?
        set -e
        enro_log "llama-server hazır olmadan kapandı (status=$SERVER_STATUS)"
        tail -n 80 "$SERVER_LOG" >&2 || true
        exit 1
    fi
    if python3 "$SCRIPT_DIR/scripts/local_ai_probe.py" --quiet health --timeout 2; then
        break
    fi
    if ((SECONDS - START_SECONDS >= ENRO_SERVER_HEALTH_TIMEOUT)); then
        enro_log "Health zaman aşımı: ${ENRO_SERVER_HEALTH_TIMEOUT}s"
        tail -n 80 "$SERVER_LOG" >&2 || true
        exit 1
    fi
    sleep 0.5
done
enro_log "Hazır: $ENRO_LLM_BASE_URL (model=$ENRO_SERVER_ALIAS)"

if ((!SKIP_WARMUP)); then
    enro_log "Model warm-up yapılıyor"
    if ! python3 "$SCRIPT_DIR/scripts/local_ai_probe.py" --quiet warmup \
        --timeout "$ENRO_SERVER_WARMUP_TIMEOUT"; then
        enro_log "Warm-up başarısız"
        tail -n 80 "$SERVER_LOG" >&2 || true
        exit 1
    fi
    enro_log "Warm-up tamamlandı"
fi

if ((EXEC_MODE)); then
    set +e
    "${COMMAND_ARGS[@]}"
    COMMAND_STATUS=$?
    set -e
    exit "$COMMAND_STATUS"
fi

enro_log "Foreground sunucu çalışıyor; durdurmak için Ctrl-C"
set +e
wait "$SERVER_PID"
SERVER_STATUS=$?
set -e
exit "$SERVER_STATUS"

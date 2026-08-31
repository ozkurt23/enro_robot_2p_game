#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/runtime_common.sh
source "$SCRIPT_DIR/scripts/runtime_common.sh"

usage() {
    cat <<'EOF'
Kullanım: ./run_game.sh [runtime seçenekleri] [-- oyun seçenekleri]

  --no-setup      Eksik local-AI dosyalarını otomatik indirme; açık hata ver
  --no-warmup     llama-server warm-up isteğini atla
  --gpu-layers V  GPU offload: all, auto veya katman sayısı
  --python PATH   Oyun için kullanılacak Python executable
  -h, --help      Bu yardımı göster

İlk çalıştırmada yaklaşık 5.29 GiB model indirilir. Runtime ve model yalnız
v2/.deps ile v2/.models altına yazılır. Oyun bitince sahip olunan model sunucusu
otomatik kapatılır.
EOF
}

AUTO_SETUP=1
NO_WARMUP=0
GPU_LAYERS=""
PYTHON_BIN=""
GAME_ARGS=()
while (($#)); do
    case "$1" in
        --no-setup)
            AUTO_SETUP=0
            shift
            ;;
        --no-warmup)
            NO_WARMUP=1
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
        --python)
            [[ $# -ge 2 ]] || {
                enro_die "--python bir PATH gerektirir"
                exit 2
            }
            PYTHON_BIN="$2"
            shift 2
            ;;
        --)
            shift
            GAME_ARGS=("$@")
            break
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            GAME_ARGS+=("$1")
            shift
            ;;
    esac
done

enro_load_runtime_lock
enro_runtime_paths

if ! enro_runtime_tree_valid \
    || ! enro_size_matches "$ENRO_LLAMA_ARCHIVE" "$ENRO_LLAMA_ASSET_SIZE" \
    || ! enro_sha256_matches "$ENRO_LLAMA_ARCHIVE" "$ENRO_LLAMA_ASSET_SHA256" \
    || ! enro_size_matches "$ENRO_MODEL_PATH" "$ENRO_MODEL_SIZE" \
    || ! enro_sha256_matches "$ENRO_MODEL_PATH" "$ENRO_MODEL_SHA256" \
    || ! enro_python_env_valid; then
    if ((AUTO_SETUP)); then
        enro_log "Local AI eksik; pinlenmiş kullanıcı-lokal setup başlatılıyor."
        "$SCRIPT_DIR/setup_local_ai.sh"
    else
        enro_die "Local AI eksik. Çalıştırın: $SCRIPT_DIR/setup_local_ai.sh"
        exit 1
    fi
fi

if [[ -z "$PYTHON_BIN" ]]; then
    if [[ -x "$ENRO_VENV_PYTHON" ]]; then
        PYTHON_BIN="$ENRO_VENV_PYTHON"
    else
        PYTHON_BIN="$(command -v python3 || true)"
    fi
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    enro_die "Python executable bulunamadı: ${PYTHON_BIN:-<boş>}"
    exit 1
fi
if ! "$PYTHON_BIN" -c 'import py_trees' >/dev/null 2>&1; then
    enro_die "Seçilen Python'da py_trees yok. Çalıştırın: $SCRIPT_DIR/setup_local_ai.sh"
    exit 1
fi
if [[ ! -f "$SCRIPT_DIR/src/enro_terminal/__main__.py" ]]; then
    enro_die "Oyun entrypoint'i bulunamadı: src/enro_terminal/__main__.py"
    exit 1
fi

export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
RUNNER_ARGS=()
((NO_WARMUP)) && RUNNER_ARGS+=(--no-warmup)
[[ -n "$GPU_LAYERS" ]] && RUNNER_ARGS+=(--gpu-layers "$GPU_LAYERS")
RUNNER_ARGS+=(--exec -- "$PYTHON_BIN" -m enro_terminal)
RUNNER_ARGS+=("${GAME_ARGS[@]}")

cd -- "$SCRIPT_DIR"
exec "$SCRIPT_DIR/run_local_ai.sh" "${RUNNER_ARGS[@]}"

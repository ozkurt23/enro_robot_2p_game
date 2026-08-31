#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/runtime_common.sh
source "$SCRIPT_DIR/scripts/runtime_common.sh"

usage() {
    cat <<'EOF'
Kullanım: ./setup_local_ai.sh [--verify-only] [--quiet]

ENRO V2 için pinlenmiş llama.cpp Ubuntu/Vulkan runtime'ını v2/.deps altına,
Qwen3.5-9B-Q4_K_M modelini v2/.models altına ve oyun bağımlılıklarını izole
v2/.deps/game-python ortamına kurar. Geliştirme .venv'ine dokunmaz. Root/sudo
kullanmaz; sistem Python'unu, paketlerini veya GPU sürücüsünü değiştirmez.

  --verify-only  Ağ erişimi olmadan mevcut kurulumun size/SHA-256 pinlerini doğrula
  --quiet        Başarı mesajlarını bastır; hatalar yine yazılır
  -h, --help     Bu yardımı göster
EOF
}

VERIFY_ONLY=0
while (($#)); do
    case "$1" in
        --verify-only)
            VERIFY_ONLY=1
            ;;
        --quiet)
            ENRO_QUIET=1
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
    shift
done

enro_load_runtime_lock
enro_runtime_paths
enro_require_command sha256sum
enro_require_command awk
enro_require_command stat
enro_require_command flock

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
    enro_die "Pinlenmiş prebuilt yalnız Linux x86_64 içindir"
    exit 1
fi

verify_server_contract() {
    local version_output help_output required_flag wheel_index wheel_path
    local wheel_fields=()
    if ! enro_runtime_tree_valid; then
        enro_die "llama.cpp runtime ağacı eksik veya pin stamp'i uyuşmuyor: $ENRO_LLAMA_HOME"
        return 1
    fi
    if ! enro_size_matches "$ENRO_LLAMA_ARCHIVE" "$ENRO_LLAMA_ASSET_SIZE" \
        || ! enro_sha256_matches "$ENRO_LLAMA_ARCHIVE" "$ENRO_LLAMA_ASSET_SHA256"; then
        enro_die "llama.cpp release arşivi eksik veya checksum yanlış: $ENRO_LLAMA_ARCHIVE"
        return 1
    fi
    if ! enro_size_matches "$ENRO_MODEL_PATH" "$ENRO_MODEL_SIZE" \
        || ! enro_sha256_matches "$ENRO_MODEL_PATH" "$ENRO_MODEL_SHA256"; then
        enro_die "Model eksik veya checksum yanlış: $ENRO_MODEL_PATH"
        return 1
    fi
    mapfile -d '' -t wheel_fields < <(
        python3 "$ENRO_LOCK_HELPER" --lock "$ENRO_RUNTIME_LOCK" wheels0
    )
    if ((${#wheel_fields[@]} == 0 || ${#wheel_fields[@]} % 6 != 0)); then
        enro_die "Python wheel pinleri okunamadı"
        return 1
    fi
    for ((wheel_index = 0; wheel_index < ${#wheel_fields[@]}; wheel_index += 6)); do
        wheel_path="$ENRO_WHEELS_ROOT/${wheel_fields[wheel_index + 2]}"
        if ! enro_size_matches "$wheel_path" "${wheel_fields[wheel_index + 5]}" \
            || ! enro_sha256_matches "$wheel_path" "${wheel_fields[wheel_index + 4]}"; then
            enro_die "Python wheel eksik veya checksum yanlış: $wheel_path"
            return 1
        fi
    done
    if ! enro_python_env_valid; then
        enro_die "Pinlenmiş oyun Python ortamı eksik/uyuşmuyor: $ENRO_VENV_HOME"
        return 1
    fi

    if ! version_output="$(
        LD_LIBRARY_PATH="$ENRO_LLAMA_HOME${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
            "$ENRO_LLAMA_SERVER" --version 2>&1
    )"; then
        enro_die "llama-server çalıştırılamadı. Yerel Vulkan loader/driver durumunu kontrol edin."
        printf '%s\n' "$version_output" >&2
        return 1
    fi
    if [[ "$version_output" != *"10566"* \
        && "$version_output" != *"bb4caa7"* \
        && "$version_output" != *"0.2.0"* ]]; then
        enro_die "llama-server sürümü runtime lock ile eşleşmiyor: $version_output"
        return 1
    fi

    if ! help_output="$(
        LD_LIBRARY_PATH="$ENRO_LLAMA_HOME${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
            "$ENRO_LLAMA_SERVER" --help 2>&1
    )"; then
        enro_die "llama-server --help başarısız"
        return 1
    fi
    for required_flag in \
        --n-gpu-layers --flash-attn --jinja --reasoning --no-mmproj \
        --no-webui --no-slots --offline --host --port; do
        if ! grep -Fq -- "$required_flag" <<<"$help_output"; then
            enro_die "Pinlenmiş llama-server gerekli flag'i sunmuyor: $required_flag"
            return 1
        fi
    done

    enro_log "Runtime doğrulandı: $version_output"
    enro_log "Model doğrulandı: $ENRO_MODEL_FILE ($ENRO_MODEL_QUANTIZATION)"
    enro_log "Python ortamı doğrulandı: $ENRO_VENV_HOME"
}

install -d -m 0755 "$ENRO_DEPS_ROOT" "$ENRO_MODELS_ROOT" "$ENRO_STATE_ROOT"
exec 9>"$ENRO_DEPS_ROOT/setup.lock"
if ! flock --wait 30 9; then
    enro_die "Başka bir local-AI setup işlemi çalışıyor"
    exit 1
fi

if ((VERIFY_ONLY)); then
    verify_server_contract
    exit $?
fi

enro_require_command curl
enro_require_command mktemp
enro_require_command python3

CURRENT_PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$CURRENT_PYTHON_VERSION" != "$ENRO_PYTHON_VERSION" ]]; then
    enro_die "Python $ENRO_PYTHON_VERSION gerekli; bulunan=$CURRENT_PYTHON_VERSION"
    exit 1
fi

enro_log "Kullanıcı-lokal kurulum hedefi: $ENRO_V2_ROOT"
enro_log "Sistem paketi, CUDA Toolkit veya GPU sürücüsü değiştirilmeyecek."

mapfile -d '' -t WHEEL_FIELDS < <(
    python3 "$ENRO_LOCK_HELPER" --lock "$ENRO_RUNTIME_LOCK" wheels0
)
if ((${#WHEEL_FIELDS[@]} == 0 || ${#WHEEL_FIELDS[@]} % 6 != 0)); then
    enro_die "Python wheel pinleri okunamadı"
    exit 1
fi
WHEEL_PATHS=()
for ((WHEEL_INDEX = 0; WHEEL_INDEX < ${#WHEEL_FIELDS[@]}; WHEEL_INDEX += 6)); do
    WHEEL_FILE="${WHEEL_FIELDS[WHEEL_INDEX + 2]}"
    WHEEL_PATH="$ENRO_WHEELS_ROOT/$WHEEL_FILE"
    enro_download_verified \
        "${WHEEL_FIELDS[WHEEL_INDEX + 3]}" \
        "${WHEEL_FIELDS[WHEEL_INDEX + 4]}" \
        "${WHEEL_FIELDS[WHEEL_INDEX + 5]}" \
        "$WHEEL_PATH"
    WHEEL_PATHS+=("$WHEEL_PATH")
done

if ! enro_python_env_valid; then
    if [[ -e "$ENRO_VENV_HOME" ]]; then
        VENV_BACKUP="$(enro_corrupt_backup_name "$ENRO_VENV_HOME")"
        enro_log "Uyumsuz local Python ortamı kenara alınıyor: $VENV_BACKUP"
        mv -- "$ENRO_VENV_HOME" "$VENV_BACKUP"
    fi
    enro_log "Kullanıcı-lokal Python ortamı oluşturuluyor: $ENRO_VENV_HOME"
    python3 -m venv "$ENRO_VENV_HOME"
    "$ENRO_VENV_PYTHON" -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --no-index \
        --no-deps \
        "${WHEEL_PATHS[@]}"
    enro_expected_python_stamp >"$ENRO_VENV_STAMP"
    if ! enro_python_env_valid; then
        enro_die "Local Python ortamı kurulduktan sonra doğrulanamadı"
        exit 1
    fi
fi

enro_download_verified \
    "$ENRO_LLAMA_ASSET_URL" \
    "$ENRO_LLAMA_ASSET_SHA256" \
    "$ENRO_LLAMA_ASSET_SIZE" \
    "$ENRO_LLAMA_ARCHIVE"

STAGING_DIR=""
cleanup_staging() {
    local status=$?
    if [[ -n "$STAGING_DIR" && -d "$STAGING_DIR" ]]; then
        case "$STAGING_DIR" in
            "$ENRO_DEPS_ROOT"/.extract."$ENRO_LLAMA_RELEASE".*)
                rm -rf -- "$STAGING_DIR"
                ;;
            *)
                enro_log "Güvenli olmayan staging cleanup reddedildi: $STAGING_DIR"
                ;;
        esac
    fi
    return "$status"
}
trap cleanup_staging EXIT

if ! enro_runtime_tree_valid; then
    if [[ -e "$ENRO_LLAMA_HOME" ]]; then
        BACKUP_DIR="$(enro_corrupt_backup_name "$ENRO_LLAMA_HOME")"
        enro_log "Eksik/uyuşmayan runtime ağacı kenara alınıyor: $BACKUP_DIR"
        mv -- "$ENRO_LLAMA_HOME" "$BACKUP_DIR"
    fi
    STAGING_DIR="$(mktemp -d "$ENRO_DEPS_ROOT/.extract.$ENRO_LLAMA_RELEASE.XXXXXX")"
    python3 "$SCRIPT_DIR/scripts/safe_extract_tar.py" \
        "$ENRO_LLAMA_ARCHIVE" \
        "$STAGING_DIR" \
        "$ENRO_LLAMA_EXTRACT_DIR" >/dev/null
    CANDIDATE_DIR="$STAGING_DIR/$ENRO_LLAMA_EXTRACT_DIR"
    for executable in \
        "$CANDIDATE_DIR/$ENRO_LLAMA_SERVER_RELPATH" \
        "$CANDIDATE_DIR/$ENRO_LLAMA_CLI_RELPATH" \
        "$CANDIDATE_DIR/$ENRO_LLAMA_BENCH_RELPATH"; do
        if [[ ! -x "$executable" ]]; then
            enro_die "Resmî arşivde beklenen executable yok: $executable"
            exit 1
        fi
    done
    enro_expected_stamp >"$CANDIDATE_DIR/.enro-runtime-pin"
    mv -- "$CANDIDATE_DIR" "$ENRO_LLAMA_HOME"
    rmdir -- "$STAGING_DIR"
    STAGING_DIR=""
    enro_log "llama.cpp $ENRO_LLAMA_RELEASE kuruldu: $ENRO_LLAMA_HOME"
fi

enro_download_verified \
    "$ENRO_MODEL_URL" \
    "$ENRO_MODEL_SHA256" \
    "$ENRO_MODEL_SIZE" \
    "$ENRO_MODEL_PATH"

verify_server_contract
enro_log "Kurulum tamamlandı. Sunucu: ./run_local_ai.sh"

#!/usr/bin/env bash
# Shared helpers for ENRO V2 local-AI entrypoints. This file is sourced.

ENRO_SCRIPTS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENRO_V2_ROOT="$(cd -- "$ENRO_SCRIPTS_DIR/.." && pwd -P)"
ENRO_RUNTIME_LOCK="$ENRO_V2_ROOT/runtime.lock.toml"
ENRO_LOCK_HELPER="$ENRO_SCRIPTS_DIR/runtime_lock.py"

enro_log() {
    [[ "${ENRO_QUIET:-0}" == "1" ]] && return 0
    printf '[enro-local-ai] %s\n' "$*" >&2
}

enro_die() {
    enro_log "HATA: $*"
    return 1
}

enro_require_command() {
    local command_name="$1"
    command -v "$command_name" >/dev/null 2>&1 || {
        enro_die "Gerekli komut bulunamadı: $command_name"
        return 1
    }
}

enro_load_runtime_lock() {
    local variable_name variable_value
    enro_require_command python3 || return 1
    [[ -f "$ENRO_RUNTIME_LOCK" ]] || {
        enro_die "Runtime lock bulunamadı: $ENRO_RUNTIME_LOCK"
        return 1
    }
    while IFS= read -r -d '' variable_name && IFS= read -r -d '' variable_value; do
        [[ "$variable_name" =~ ^ENRO_[A-Z0-9_]+$ ]] || {
            enro_die "Runtime helper güvenli olmayan değişken adı üretti"
            return 1
        }
        printf -v "$variable_name" '%s' "$variable_value"
    done < <(python3 "$ENRO_LOCK_HELPER" --lock "$ENRO_RUNTIME_LOCK" env0)
    [[ -n "${ENRO_LLAMA_RELEASE:-}" && -n "${ENRO_MODEL_FILE:-}" ]] || {
        enro_die "Runtime lock yüklenemedi"
        return 1
    }
}

enro_sha256_matches() {
    local path="$1" expected="$2" actual
    [[ -f "$path" ]] || return 1
    actual="$(sha256sum -- "$path" | awk '{print $1}')" || return 1
    [[ "$actual" == "$expected" ]]
}

enro_size_matches() {
    local path="$1" expected="$2" actual
    [[ -f "$path" ]] || return 1
    actual="$(stat --format='%s' -- "$path")" || return 1
    [[ "$actual" == "$expected" ]]
}

enro_corrupt_backup_name() {
    local path="$1"
    printf '%s.corrupt.%(%Y%m%dT%H%M%S)T.%s\n' "$path" -1 "$$"
}

enro_download_verified() {
    local url="$1" expected_sha="$2" expected_size="$3" destination="$4"
    local partial backup

    partial="$destination.partial"
    install -d -m 0755 "$(dirname -- "$destination")"

    if [[ -f "$destination" ]]; then
        if enro_size_matches "$destination" "$expected_size" && enro_sha256_matches "$destination" "$expected_sha"; then
            enro_log "Doğrulandı, yeniden indirilmiyor: $destination"
            return 0
        fi
        backup="$(enro_corrupt_backup_name "$destination")"
        enro_log "Checksum uyuşmayan mevcut dosya kenara alınıyor: $backup"
        mv -- "$destination" "$backup"
    fi

    enro_log "İndiriliyor (kesilirse sonraki çalıştırmada devam eder): $url"
    if ! curl \
        --fail \
        --location \
        --retry 5 \
        --retry-delay 2 \
        --retry-all-errors \
        --connect-timeout 20 \
        --continue-at - \
        --output "$partial" \
        "$url"; then
        enro_die "İndirme başarısız; kısmi dosya resume için korundu: $partial"
        return 1
    fi

    if ! enro_size_matches "$partial" "$expected_size" || ! enro_sha256_matches "$partial" "$expected_sha"; then
        backup="$(enro_corrupt_backup_name "$partial")"
        mv -- "$partial" "$backup"
        enro_die "İndirilen dosyanın size/SHA-256 değeri yanlış; dosya korundu: $backup"
        return 1
    fi
    mv -- "$partial" "$destination"
    enro_log "SHA-256 doğrulandı: $destination"
}

enro_runtime_paths() {
    ENRO_DEPS_ROOT="$ENRO_V2_ROOT/.deps"
    ENRO_MODELS_ROOT="$ENRO_V2_ROOT/.models"
    ENRO_STATE_ROOT="$ENRO_V2_ROOT/.runtime"
    ENRO_WHEELS_ROOT="$ENRO_DEPS_ROOT/python-wheels"
    ENRO_VENV_HOME="$ENRO_V2_ROOT/$ENRO_PYTHON_VENV_DIR"
    ENRO_VENV_PYTHON="$ENRO_VENV_HOME/bin/python"
    ENRO_VENV_STAMP="$ENRO_VENV_HOME/.enro-python-pin"
    ENRO_LLAMA_ARCHIVE="$ENRO_DEPS_ROOT/downloads/$ENRO_LLAMA_ASSET_NAME"
    ENRO_LLAMA_HOME="$ENRO_DEPS_ROOT/$ENRO_LLAMA_EXTRACT_DIR"
    ENRO_LLAMA_SERVER="$ENRO_LLAMA_HOME/$ENRO_LLAMA_SERVER_RELPATH"
    ENRO_LLAMA_CLI="$ENRO_LLAMA_HOME/$ENRO_LLAMA_CLI_RELPATH"
    ENRO_LLAMA_BENCH="$ENRO_LLAMA_HOME/$ENRO_LLAMA_BENCH_RELPATH"
    ENRO_LLAMA_STAMP="$ENRO_LLAMA_HOME/.enro-runtime-pin"
    ENRO_MODEL_PATH="$ENRO_MODELS_ROOT/$ENRO_MODEL_FILE"
    ENRO_LLM_ROOT_URL="http://$ENRO_SERVER_HOST:$ENRO_SERVER_PORT"
    ENRO_LLM_HEALTH_URL="http://$ENRO_SERVER_HOST:$ENRO_SERVER_PORT$ENRO_SERVER_HEALTH_PATH"
    ENRO_LLM_BASE_URL="$ENRO_LLM_ROOT_URL$ENRO_SERVER_API_BASE_PATH"
}

enro_expected_python_stamp() {
    local fields index
    printf 'python=%s\n' "$ENRO_PYTHON_VERSION"
    mapfile -d '' -t fields < <(
        python3 "$ENRO_LOCK_HELPER" --lock "$ENRO_RUNTIME_LOCK" wheels0
    )
    for ((index = 0; index < ${#fields[@]}; index += 6)); do
        printf '%s=%s@%s\n' "${fields[index]}" "${fields[index + 1]}" "${fields[index + 4]}"
    done
}

enro_python_env_valid() {
    local expected actual
    [[ -x "$ENRO_VENV_PYTHON" && -f "$ENRO_VENV_STAMP" ]] || return 1
    expected="$(enro_expected_python_stamp)"
    actual="$(<"$ENRO_VENV_STAMP")"
    [[ "$actual" == "$expected" ]] || return 1
    "$ENRO_VENV_PYTHON" - "$ENRO_PYTHON_VERSION" <<'PY' >/dev/null 2>&1
import sys
from importlib.metadata import version
expected_python = tuple(map(int, sys.argv[1].split(".")))
assert sys.version_info[:2] == expected_python
assert version("pyparsing") == "3.2.3"
assert version("pydot") == "4.0.1"
assert version("py_trees") == "2.5.0"
import py_trees
PY
}

enro_expected_stamp() {
    printf 'release=%s\ncommit=%s\nasset_sha256=%s\nbackend=%s\n' \
        "$ENRO_LLAMA_RELEASE" \
        "$ENRO_LLAMA_COMMIT" \
        "$ENRO_LLAMA_ASSET_SHA256" \
        "$ENRO_LLAMA_BACKEND"
}

enro_runtime_tree_valid() {
    local expected actual
    [[ -d "$ENRO_LLAMA_HOME" ]] || return 1
    [[ -x "$ENRO_LLAMA_SERVER" && -x "$ENRO_LLAMA_CLI" && -x "$ENRO_LLAMA_BENCH" ]] || return 1
    [[ -f "$ENRO_LLAMA_STAMP" ]] || return 1
    expected="$(enro_expected_stamp)"
    actual="$(<"$ENRO_LLAMA_STAMP")"
    [[ "$actual" == "$expected" ]]
}

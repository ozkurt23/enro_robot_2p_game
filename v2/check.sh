#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/runtime_common.sh
source "$SCRIPT_DIR/scripts/runtime_common.sh"

usage() {
    cat <<'EOF'
Kullanım: ./check.sh [--live | --live-eval] [--no-project-tests]

Varsayılan kontrol ağsızdır ve model indirmez:
  - runtime.lock.toml strict validation
  - shell syntax ve Python AST
  - runtime helper birim testleri
  - varsa projenin live_model dışındaki pytest testleri

--live ayrıca kurulu/pinlenmiş modeli geçici llama-server ile açar, health ve
warm-up bekler, dört Türkçe komutla JSON Schema + non-thinking smoke eval yapar
ve sunucuyu her çıkış yolunda kapatır. --live model indirmez; önce
./setup_local_ai.sh çalıştırılmış olmalıdır.

--live-eval aynı smoke eval'den sonra checked-in Türkçe NLU corpus'unun tamamını
gerçek Qwen backend'iyle çalıştırır. Bu seçenek daha uzun sürebilir.
EOF
}

LIVE_MODE="none"
PROJECT_TESTS=1
while (($#)); do
    case "$1" in
        --live)
            LIVE_MODE="quick"
            ;;
        --live-eval)
            LIVE_MODE="full"
            ;;
        --no-project-tests)
            PROJECT_TESTS=0
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

enro_require_command bash
enro_require_command python3

enro_log "runtime.lock.toml doğrulanıyor"
python3 "$SCRIPT_DIR/scripts/runtime_lock.py" validate

enro_log "Shell syntax kontrol ediliyor"
while IFS= read -r shell_file; do
    bash -n "$shell_file"
done < <(
    find "$SCRIPT_DIR" -maxdepth 3 -type f -name '*.sh' -print | sort
)

enro_log "Python kaynakları AST ile kontrol ediliyor"
ENRO_CHECK_ROOT="$SCRIPT_DIR" PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import ast
import os
from pathlib import Path

root = Path(os.environ["ENRO_CHECK_ROOT"])
paths = sorted((root / "scripts").rglob("*.py"))
paths.extend(sorted((root / "src").rglob("*.py")))
for path in paths:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
print(f"OK: {len(paths)} Python dosyası")
PY

enro_log "Runtime script birim testleri çalıştırılıyor"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
    -s "$SCRIPT_DIR/scripts/tests" \
    -p 'test_*.py' \
    -v

if ((PROJECT_TESTS)) && [[ -d "$SCRIPT_DIR/tests" ]]; then
    TEST_PYTHON="$(command -v python3)"
    TEST_PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
    if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
        VENV_SITE_PACKAGES="$(
            "$SCRIPT_DIR/.venv/bin/python" -c \
                'import sysconfig; print(sysconfig.get_paths()["purelib"])'
        )"
        TEST_PYTHONPATH="$TEST_PYTHONPATH:$VENV_SITE_PACKAGES"
    fi
    if PYTHONPATH="$TEST_PYTHONPATH" "$TEST_PYTHON" -c 'import pytest, py_trees' >/dev/null 2>&1; then
        enro_log "Proje unit testleri çalıştırılıyor (live_model hariç)"
        PYTHONPATH="$TEST_PYTHONPATH" \
            PYTHONDONTWRITEBYTECODE=1 \
            "$TEST_PYTHON" -m pytest -q -m 'not live_model' "$SCRIPT_DIR/tests"
    else
        enro_log "pytest/py_trees test ortamı hazır değil; proje testleri atlandı (runtime testleri geçti)"
    fi
fi

if [[ "$LIVE_MODE" != "none" ]]; then
    enro_log "Kurulu model/runtime checksum'ları doğrulanıyor"
    "$SCRIPT_DIR/setup_local_ai.sh" --verify-only
    enro_log "Canlı structured-output değerlendirmesi başlatılıyor"
    "$SCRIPT_DIR/run_local_ai.sh" --exec -- \
        "$SCRIPT_DIR/scripts/run_live_eval.sh" "$LIVE_MODE"
fi

enro_log "Tüm seçili kontroller geçti"

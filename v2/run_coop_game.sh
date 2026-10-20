#!/usr/bin/env bash
set -Euo pipefail
ENRO_COOP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENRO_COOP_DEMO=0
ENRO_COOP_RULES=0
ENRO_COOP_RUNTIME=()
ENRO_COOP_ARGS=(--persona neseli --no-store)
while (($#)); do
    case "$1" in
        --demo) ENRO_COOP_DEMO=1; shift ;;
        --rules) ENRO_COOP_RULES=1; shift ;;
        --headless|--build|--no-setup|--no-warmup)
            ENRO_COOP_RUNTIME+=("$1"); shift ;;
        --) shift; ENRO_COOP_ARGS+=("$@"); break ;;
        -h|--help)
            echo "İki gamepad: ./start_coop_game.sh"
            echo "Klavye provası: ./start_coop_game.sh --demo --rules -- --keyboard"
            echo "Gerçek arena, klavye: ./start_coop_game.sh -- --keyboard"
            echo "Seçenekler: --demo --rules --headless --no-setup --no-warmup --build"
            echo "Oyun seçenekleri -- sonrasında: --persona neseli|leydi|sakar --pad1 PATH --pad2 PATH --mic1 ALSA --mic2 ALSA"
            exit 0 ;;
        *) ENRO_COOP_ARGS+=("$1"); shift ;;
    esac
done
export PYTHONPATH="$ENRO_COOP_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
ENRO_COOP_PYTHON="$ENRO_COOP_ROOT/.deps/game-python/bin/python"
[[ -x "$ENRO_COOP_PYTHON" ]] || ENRO_COOP_PYTHON=python3
if ! "$ENRO_COOP_PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
    echo "[hata] Masaüstü paneli için Python Tk gerekli (Ubuntu: python3-tk)." >&2
    exit 2
fi
if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    echo "[hata] Oyuncu paneli grafik oturum ister. --headless yalnız Gazebo penceresini kapatır." >&2
    exit 2
fi
while true; do
    if ((ENRO_COOP_DEMO)); then
        if ((ENRO_COOP_RULES)); then
            "$ENRO_COOP_PYTHON" -m enro_terminal --coop --backend rules "${ENRO_COOP_ARGS[@]}"
        else
            "$ENRO_COOP_ROOT/run_game.sh" -- --coop "${ENRO_COOP_ARGS[@]}"
        fi
    else
        ENRO_COOP_RULE_ARGS=()
        ((ENRO_COOP_RULES)) && ENRO_COOP_RULE_ARGS+=(--rules)
        "$ENRO_COOP_ROOT/run_sim_game.sh" --coop "${ENRO_COOP_RUNTIME[@]}" \
            "${ENRO_COOP_RULE_ARGS[@]}" -- "${ENRO_COOP_ARGS[@]}"
    fi
    ENRO_COOP_STATUS=$?
    [[ "$ENRO_COOP_STATUS" == 75 ]] || exit "$ENRO_COOP_STATUS"
    export ENRO_COOP_RESET_PROBE=1
    echo "[coop] Önceki oturum kapandı. Yeni ekip için dünya ve oyun yeniden kuruluyor."
done

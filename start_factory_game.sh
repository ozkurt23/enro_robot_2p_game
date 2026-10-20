#!/usr/bin/env bash
set -eo pipefail
FACTORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ ! -f /opt/ros/jazzy/setup.bash || ! -f "$FACTORY_ROOT/install/setup.bash" ]]; then
  echo "[hata] ROS 2 Jazzy veya bu deponun robot paketleri kurulmamış." >&2
  echo "Kurulum adımları: $FACTORY_ROOT/docs/INSTALLATION.md" >&2
  exit 1
fi
source /opt/ros/jazzy/setup.bash
source "$FACTORY_ROOT/install/setup.bash"
export PYTHONPATH="$FACTORY_ROOT/v2/src:$FACTORY_ROOT/factory${PYTHONPATH:+:$PYTHONPATH}"
if [[ "${1:-}" == "--practice" ]]; then
  shift
  exec /usr/bin/python3 "$FACTORY_ROOT/factory/launch.py" "$@"
fi
exec /usr/bin/python3 "$FACTORY_ROOT/factory/race_launch.py" "$@"

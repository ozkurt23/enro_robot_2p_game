#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# ENRO'nun desteklenen tek oyun girişi: native Gazebo + yerel Qwen +
# doğrulanmış persona/ROS case güvenlik katmanı.
workspace="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec "$workspace/v2/run_sim_game.sh" "$@"

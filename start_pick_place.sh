#!/usr/bin/env bash

# Gazebo + MoveIt + Pick & Place terminalini, dış kabukta ROS ortamını
# kaynaklamaya gerek bırakmadan başlatır.
set -e

workspace="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
launcher="$workspace/install/robot_arm_pick_place/lib/robot_arm_pick_place/start_pick_place.sh"

if [[ ! -x "$launcher" ]]; then
  echo "[hata] Kurulu başlatıcı bulunamadı." >&2
  echo "       Önce: cd \"$workspace\" && source /opt/ros/jazzy/setup.bash && colcon build --symlink-install" >&2
  exit 1
fi

export ROBOT_ARM_WS="$workspace"
exec "$launcher" "$@"

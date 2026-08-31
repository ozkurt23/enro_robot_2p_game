#!/usr/bin/env bash

# Gazebo + MoveIt + interaktif PP terminalini tek terminalden başlatır.
# Kendi ROS / workspace ortamını yükler; ayrı terminaller gerekmez.

workspace="${ROBOT_ARM_WS:-$HOME/S_Robot_Arm_V2_Moveit}"
if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
  echo "[hata] /opt/ros/jazzy/setup.bash bulunamadı." >&2
  exit 1
fi
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
if [[ ! -f "$workspace/install/setup.bash" ]]; then
  echo "[hata] $workspace/install/setup.bash bulunamadı; önce colcon build çalıştırın." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$workspace/install/setup.bash"
set -u

# Gazebo Transport ağ arayüzü bulamazsa "Exception sending a multicast
# message: Network is unreachable" uyarısını sürekli basıp terminali ve topic
# trafiğini boğabiliyor. Bu PP demosu tek makinede çalıştığı için discovery'yi
# localhost'a sabitlemek en deterministik seçenek.
export GZ_IP="${GZ_IP:-127.0.0.1}"
export IGN_IP="${IGN_IP:-127.0.0.1}"
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-LOCALHOST}"

lock_file="/tmp/s_robot_arm_v2_pp_${ROS_DOMAIN_ID:-0}.lock"
exec 9>"$lock_file"
if ! flock -n 9; then
  echo "[hata] Pick & Place sistemi bu ROS domaininde zaten çalışıyor." >&2
  echo "       Açık terminali kullanın veya orada Ctrl+C ile kapatın." >&2
  exit 2
fi

stack_patterns=(
  '^/opt/ros/jazzy/lib/moveit_ros_move_group/move_group'
  '^/opt/ros/jazzy/lib/rviz2/rviz2'
  '^/opt/ros/jazzy/lib/robot_state_publisher/robot_state_publisher'
  '^/opt/ros/jazzy/lib/ros_gz_bridge/parameter_bridge'
  'robot_arm_pick_place.*/pick_place_terminal.py'
  '^gz sim'
  '/opt/ros/jazzy/opt/gz_tools_vendor/bin/gz sim'
)

signal_stale_stack() {
  local signal="$1"
  local pattern
  for pattern in "${stack_patterns[@]}"; do
    pkill "-$signal" -f "$pattern" 2>/dev/null || true
  done
}

stale_stack_exists() {
  local pattern
  for pattern in "${stack_patterns[@]}"; do
    if pgrep -f "$pattern" >/dev/null; then
      return 0
    fi
  done
  return 1
}

# Eski sürümde terminal sert kapatıldıysa launch çocukları yetim kalabiliyordu.
# Aynı ROS domaininde ikinci move_group başlatmak yerine bunları önce temizle.
if stale_stack_exists; then
  echo "[start] Önceki oturumdan kalan ROS/Gazebo süreçleri temizleniyor..."
  signal_stale_stack INT
  for _ in {1..30}; do
    stale_stack_exists || break
    sleep 0.1
  done
  if stale_stack_exists; then
    signal_stale_stack TERM
    sleep 1
  fi
  if stale_stack_exists; then
    signal_stale_stack KILL
    sleep 0.5
  fi
fi

wait_for_controllers() {
  local deadline=$((SECONDS + 90))
  while (( SECONDS < deadline )); do
    local state
    state="$(ros2 control list_controllers 2>/dev/null || true)"
    if grep -q '^arm_controller.*active' <<<"$state" &&
       grep -q '^gripper_controller.*active' <<<"$state" &&
       grep -q '^joint_state_broadcaster.*active' <<<"$state"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_move_group() {
  local deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    if ros2 action info /move_action 2>/dev/null |
       grep -q 'Action servers: 1'; then
      return 0
    fi
    sleep 1
  done
  return 1
}

cleanup() {
  status=$?
  trap - EXIT INT TERM

  stop_process_group() {
    local pid="${1:-}"
    [[ -z "$pid" ]] && return
    if kill -0 "$pid" 2>/dev/null; then
      kill -INT -- "-$pid" 2>/dev/null || kill -INT "$pid" 2>/dev/null || true
      for _ in {1..30}; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
      done
    fi
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
      sleep 0.5
    fi
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
  }

  stop_process_group "${moveit_pid:-}"
  stop_process_group "${gazebo_pid:-}"
  exit "$status"
}
trap cleanup EXIT INT TERM

echo "[start] Gazebo başlatılıyor..."
gazebo_args=()
if [[ "${ROBOT_ARM_HEADLESS:-0}" == "1" ]]; then
  gazebo_args+=(headless:=true)
  echo "[start] Headless test modu etkin (Gazebo fiziği açık, GUI kapalı)."
fi
setsid ros2 launch robot_arm_description gazebo.launch.py "${gazebo_args[@]}" &
gazebo_pid=$!

if ! wait_for_controllers; then
  echo "[hata] Gazebo controller'ları 90 saniyede aktif olmadı." >&2
  exit 1
fi

echo "[start] MoveIt başlatılıyor..."
moveit_args=()
if [[ "${ROBOT_ARM_HEADLESS:-0}" == "1" ]]; then
  moveit_args+=(rviz:=false)
fi
setsid ros2 launch robot_arm_moveit_config moveit.launch.py "${moveit_args[@]}" &
moveit_pid=$!

if ! wait_for_move_group; then
  echo "[hata] MoveIt /move_action sunucusu 60 saniyede hazır olmadı." >&2
  exit 1
fi
echo "[start] Pick & Place terminali hazır; komutunuzu yazın (Ctrl+C: hepsini kapatır)."
ros2 run robot_arm_pick_place pick_place_terminal.py

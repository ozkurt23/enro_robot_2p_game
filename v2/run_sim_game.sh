#!/usr/bin/env bash
set -Eeo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
ROS_WS="$REPO_ROOT"
RUNTIME_DIR="$SCRIPT_DIR/.runtime"

SCENE="arena"
HEADLESS=0
BUILD_WS=0
RULES=0
NO_SETUP=0
NO_WARMUP=0
GAME_ARGS=()

usage() {
    cat <<'EOF'
Kullanım: ./run_sim_game.sh [seçenekler] [-- oyun seçenekleri]

Native Gazebo arayüzünü ve ENRO V2 terminal LLM'ini birlikte açar.
Reaktör 180 arayüzü, festival_game ve özel oyun kamerası kullanılmaz.

  --scene arena       Dört masa; orijinal Nav2 + kol/gripper hareketleri
  --scene grasp-cell  İki masa + sabit kol; /kavra gerçek kavrama skill'ini çağırır
  --headless          Gazebo fiziğini GUI olmadan çalıştır (test/CI)
  --build             ROS çalışma alanını önce yeniden derle
  --rules             Qwen yerine çevrimdışı rules backend kullan
  --no-setup          Eksik yerel AI dosyalarını indirme
  --no-warmup         Qwen warm-up isteğini atla
  -h, --help          Bu yardımı göster

Örnekler:
  ./run_sim_game.sh
  ./run_sim_game.sh --scene grasp-cell -- --persona samuray
  ./run_sim_game.sh --headless --rules -- --persona leydi --no-store
EOF
}

while (($#)); do
    case "$1" in
        --scene)
            [[ $# -ge 2 ]] || {
                echo "[hata] --scene arena veya grasp-cell ister." >&2
                exit 2
            }
            SCENE="$2"
            shift 2
            ;;
        --headless)
            HEADLESS=1
            shift
            ;;
        --build)
            BUILD_WS=1
            shift
            ;;
        --rules)
            RULES=1
            shift
            ;;
        --no-setup)
            NO_SETUP=1
            shift
            ;;
        --no-warmup)
            NO_WARMUP=1
            shift
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
            echo "[hata] Bilinmeyen sim seçeneği: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$SCENE" != "arena" && "$SCENE" != "grasp-cell" ]]; then
    echo "[hata] --scene yalnız arena veya grasp-cell olabilir: $SCENE" >&2
    exit 2
fi
if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
    echo "[hata] /opt/ros/jazzy/setup.bash bulunamadı." >&2
    exit 1
fi

# ROS setup scripts optional variables probe edebilir; nounset'i source
# işlemlerinden sonra etkinleştiriyoruz.
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash

if ((BUILD_WS)) || [[ ! -f "$ROS_WS/install/setup.bash" ]]; then
    echo "[0/4] ROS çalışma alanı derleniyor..."
    (
        cd -- "$ROS_WS"
        colcon build --symlink-install
    )
fi
if [[ ! -f "$ROS_WS/install/setup.bash" ]]; then
    echo "[hata] ROS install ortamı yok; --build ile tekrar deneyin." >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$ROS_WS/install/setup.bash"
set -u

# Tüm sim süreçlerini Fast-DDS snapshot uyumsuzluğundan bağımsız, proje-lokal
# CycloneDDS üzerinde çalıştır. Bu export'lar yalnız bu launcher ve çocukları
# için geçerlidir; sistem ROS kurulumu değiştirilmez.
"$SCRIPT_DIR/setup_ros_runtime.sh"
ROS_OVERLAY_PREFIX="$SCRIPT_DIR/.deps/ros-jazzy-cyclone-overlay/opt/ros/jazzy"
export LD_LIBRARY_PATH="$ROS_OVERLAY_PREFIX/lib:$ROS_OVERLAY_PREFIX/lib/x86_64-linux-gnu:/opt/ros/jazzy/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export RMW_IMPLEMENTATION="rmw_cyclonedds_cpp"

if [[ "$SCENE" == "grasp-cell" ]] &&
   { ! python3 -c 'import moveit_configs_utils' >/dev/null 2>&1 ||
     ! ros2 pkg prefix moveit_ros_move_group >/dev/null 2>&1; }; then
    echo "[hata] Fiziksel kavrama için MoveIt 2 kurulu değil." >&2
    echo "       Kurulum: sudo apt install ros-jazzy-moveit" >&2
    exit 1
fi
if [[ "$SCENE" == "arena" ]] &&
   { ! ros2 pkg prefix nav2_bringup >/dev/null 2>&1 ||
     ! ros2 pkg prefix nav2_bt_navigator >/dev/null 2>&1; }; then
    echo "[hata] Mobil arena için Nav2 kurulu değil." >&2
    echo "       Kurulum: sudo apt install ros-jazzy-navigation2 ros-jazzy-nav2-bringup" >&2
    exit 1
fi

export GZ_IP="${GZ_IP:-127.0.0.1}"
export IGN_IP="${IGN_IP:-127.0.0.1}"
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-LOCALHOST}"

mkdir -p -- "$RUNTIME_DIR"
SIM_LOG="$RUNTIME_DIR/native_gazebo_${SCENE}.log"
MOVEIT_LOG="$RUNTIME_DIR/moveit_grasp_cell.log"
SKILL_LOG="$RUNTIME_DIR/grasp_skill.log"
NAV2_LOG="$RUNTIME_DIR/nav2_native_arena.log"
CASE_LOG="$RUNTIME_DIR/original_mecanum_case.log"
STACK_STATE="$RUNTIME_DIR/native_stack_${ROS_DOMAIN_ID:-0}.groups"

lock_file="/tmp/enro_v2_native_gazebo_${ROS_DOMAIN_ID:-0}.lock"
exec 9>"$lock_file"
if ! flock -n 9; then
    echo "[hata] Bu ROS domaininde ENRO native Gazebo profili zaten açık." >&2
    exit 2
fi

gazebo_pid=""
moveit_pid=""
skill_pid=""
nav2_pid=""
case_pid=""

stop_session() {
    local pid="${1:-}"
    [[ -z "$pid" ]] && return 0
    if [[ ! "$pid" =~ ^[0-9]+$ ]] || ((pid <= 1)) || ((pid == $$)); then
        echo "[uyarı] Geçersiz süreç oturumu atlandı: $pid" >&2
        return 1
    fi

    # Inspect /proc rather than only the launch parent: Gazebo creates its own
    # server process group inside the same SID, and stale processes are no
    # longer children that this shell can wait(2).  The helper escalates
    # INT -> TERM -> KILL and confirms the complete session is empty.
    if ! python3 "$SCRIPT_DIR/scripts/stop_session.py" "$pid"; then
        echo "[uyarı] Süreç oturumu kapatılamadı; stale kayıt korunuyor: $pid" >&2
        return 1
    fi
    wait "$pid" 2>/dev/null || true
    return 0
}

session_matches_role() {
    local role="${1:-}"
    local pid="${2:-}"
    local processes=""
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    processes="$(
        ps -eo sid=,args= | awk -v wanted="$pid" '$1 == wanted {$1=""; print}'
    )"
    [[ -n "$processes" ]] || return 1
    case "$role" in
        gazebo_arena)
            grep -Eq 'mecanum_robot_description gazebo\.launch\.py|empty_robot_world\.sdf' <<<"$processes"
            ;;
        gazebo_grasp)
            grep -Fq 'robot_arm_description gazebo.launch.py' <<<"$processes"
            ;;
        moveit)
            grep -Fq 'robot_arm_moveit_config moveit.launch.py' <<<"$processes"
            ;;
        nav2)
            grep -Fq 'mecanum_robot_description navigation.launch.py' <<<"$processes"
            ;;
        original_case)
            grep -Eq 'mecanum_kinematics llm_agent|mecanum_original_case_server' <<<"$processes"
            ;;
        grasp_skill)
            grep -Fq 'pick_place_terminal.py' <<<"$processes"
            ;;
        *)
            return 1
            ;;
    esac
}

cleanup_stale_groups() {
    [[ -s "$STACK_STATE" ]] || return 0
    echo "[sistem] Önceki yarım kalmış ENRO oturumu temizleniyor..."
    local role=""
    local pid=""
    # The launcher intentionally removes ordinary space from global IFS so
    # user arguments stay intact.  Restore a strict registry-only separator.
    while IFS=$' \t' read -r role pid; do
        [[ -n "$role" && -n "$pid" ]] || continue
        if session_matches_role "$role" "$pid"; then
            stop_session "$pid"
        else
            echo "[uyarı] Stale kayıt doğrulanamadı; dokunulmadı: $role $pid" >&2
        fi
    done <"$STACK_STATE"
    : >"$STACK_STATE"
}

register_group() {
    local role="$1"
    local pid="$2"
    printf '%s\t%s\n' "$role" "$pid" >>"$STACK_STATE"
}

cleanup() {
    local status=$?
    local cleanup_failed=0
    trap - EXIT INT TERM HUP
    echo
    echo "[sistem] Native Gazebo ve ROS süreçleri kapatılıyor..."
    stop_session "$case_pid" || cleanup_failed=1
    stop_session "$skill_pid" || cleanup_failed=1
    stop_session "$nav2_pid" || cleanup_failed=1
    stop_session "$moveit_pid" || cleanup_failed=1
    stop_session "$gazebo_pid" || cleanup_failed=1
    if ((cleanup_failed == 0)); then
        rm -f -- "$STACK_STATE"
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM HUP

# A terminal window closed with its title-bar button sends SIGHUP.  Older
# launchers did not trap it, so their child sessions could survive after the
# lock owner disappeared.  A role-validated registry makes the next launch
# self-heal even after SIGKILL or a desktop/session crash.
cleanup_stale_groups
: >"$STACK_STATE"

wait_for_controllers() {
    python3 "$SCRIPT_DIR/scripts/ros_stack_probe.py" \
        --timeout 120 \
        --controller arm_controller \
        --controller gripper_controller \
        --controller joint_state_broadcaster
}

wait_for_action() {
    local action_name="$1"
    local kind=""
    case "$action_name" in
        /move_action) kind="moveit" ;;
        /navigate_to_pose) kind="nav2" ;;
        *) return 2 ;;
    esac
    python3 "$SCRIPT_DIR/scripts/ros_action_probe.py" \
        --kind "$kind" --name "$action_name" --timeout 90
}

wait_for_service() {
    local service_name="$1"
    local deadline=$((SECONDS + 30))
    while ((SECONDS < deadline)); do
        if ros2 service list --no-daemon --spin-time 1 -t 2>/dev/null |
           grep -F "$service_name [std_srvs/srv/Trigger]" >/dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}

headless_value="false"
((HEADLESS)) && headless_value="true"

if [[ "$SCENE" == "arena" ]]; then
    echo "[1/4] Native Gazebo arena açılıyor: dört masa + mobil robot"
    echo "      Reaktör/festival UI ve özel oyun kamerası devre dışı."
    python3 "$SCRIPT_DIR/scripts/session_exec.py" \
        ros2 launch mecanum_robot_description gazebo.launch.py \
        "headless:=$headless_value" 9>&- >"$SIM_LOG" 2>&1 &
    gazebo_pid=$!
    register_group gazebo_arena "$gazebo_pid"
else
    echo "[1/4] Native Gazebo kavrama hücresi açılıyor: iki masa + robot kol"
    python3 "$SCRIPT_DIR/scripts/session_exec.py" \
        ros2 launch robot_arm_description gazebo.launch.py \
        "headless:=$headless_value" 9>&- >"$SIM_LOG" 2>&1 &
    gazebo_pid=$!
    register_group gazebo_grasp "$gazebo_pid"
fi

echo "[2/4] Gazebo controller'ları bekleniyor..."
if ! wait_for_controllers; then
    echo "[hata] Controller'lar 120 saniyede hazır olmadı: $SIM_LOG" >&2
    exit 1
fi

if [[ "$SCENE" == "grasp-cell" ]]; then
    echo "[3/4] MoveIt açılıyor (RViz kapalı)..."
    python3 "$SCRIPT_DIR/scripts/session_exec.py" \
        ros2 launch robot_arm_moveit_config moveit.launch.py rviz:=false \
        9>&- >"$MOVEIT_LOG" 2>&1 &
    moveit_pid=$!
    register_group moveit "$moveit_pid"
    if ! wait_for_action /move_action; then
        echo "[hata] MoveIt /move_action hazır olmadı: $MOVEIT_LOG" >&2
        exit 1
    fi
    echo "      Doğrulanmış sabit-kol kavrama servisi açılıyor..."
    python3 "$SCRIPT_DIR/scripts/session_exec.py" \
        ros2 run robot_arm_pick_place pick_place_terminal.py \
        --ros-args -p terminal_enabled:=false 9>&- >"$SKILL_LOG" 2>&1 &
    skill_pid=$!
    register_group grasp_skill "$skill_pid"
    if ! wait_for_service /enro/grasp_workpiece; then
        echo "[hata] /enro/grasp_workpiece hazır olmadı: $SKILL_LOG" >&2
        exit 1
    fi
else
    echo "[3/4] Orijinal Nav2 açılıyor (SLAM açık, RViz kapalı)..."
    python3 "$SCRIPT_DIR/scripts/session_exec.py" \
        ros2 launch mecanum_robot_description navigation.launch.py \
        slam:=true rviz:=false 9>&- >"$NAV2_LOG" 2>&1 &
    nav2_pid=$!
    register_group nav2 "$nav2_pid"
    if ! wait_for_action /navigate_to_pose; then
        echo "[hata] Nav2 /navigate_to_pose hazır olmadı: $NAV2_LOG" >&2
        exit 1
    fi
    echo "      S_Mecanum_Wheel hareket servisleri Qwen'e bağlanıyor..."
    python3 "$SCRIPT_DIR/scripts/session_exec.py" \
        ros2 run mecanum_kinematics llm_agent --ros-args \
        -p use_sim_time:=true 9>&- >"$CASE_LOG" 2>&1 &
    case_pid=$!
    register_group original_case "$case_pid"
    for service in /enro/deliver_blue /enro/deliver_green /enro/deliver_red; do
        if ! wait_for_service "$service"; then
            echo "[hata] Orijinal hareket servisi hazır olmadı: $service ($CASE_LOG)" >&2
            exit 1
        fi
    done
fi

echo "[4/4] ENRO V2 terminali açılıyor..."
echo "============================================================"
echo "GÖRSEL: Yalnız native Gazebo arayüzü"
echo "LLM   : Ayrı terminal konuşması"
if [[ "$SCENE" == "grasp-cell" ]]; then
    echo "SKILL : /kavra ile gerçek kavrama + fiziksel lift testi"
else
    echo "SKILL : /mavi, /yeşil, /kırmızı, /hepsi; orijinal Nav2 + fiziksel kol/gripper"
fi
echo "============================================================"

RUNTIME_ARGS=()
((NO_SETUP)) && RUNTIME_ARGS+=(--no-setup)
((NO_WARMUP)) && RUNTIME_ARGS+=(--no-warmup)
# Gazebo, başka yerel AI/RL işleriyle aynı GPU'yu paylaşabilir. llama.cpp'nin
# mevcut VRAM'e sığan katman sayısını seçmesine izin ver; tek başına run_game
# lock dosyasındaki tam GPU offload profilini kullanmaya devam eder.
RUNTIME_ARGS+=(--gpu-layers auto)

((RULES)) && GAME_ARGS+=(--backend rules)
if [[ "$SCENE" == "grasp-cell" ]]; then
    GAME_ARGS+=(
        --simulation grasp-cell
        --grasp-service /enro/grasp_workpiece
    )
else
    GAME_ARGS+=(
        --simulation native-arena
        --delivery-service-prefix /enro/deliver_
    )
fi

if ((RULES)); then
    RULES_PYTHON="$(command -v python3)"
    if [[ -x "$SCRIPT_DIR/.deps/game-python/bin/python" ]]; then
        RULES_PYTHON="$SCRIPT_DIR/.deps/game-python/bin/python"
    fi
    if ! "$RULES_PYTHON" -c 'import py_trees' >/dev/null 2>&1; then
        echo "[hata] Rules test ortamında py_trees yok; ./setup_local_ai.sh çalıştırın." >&2
        exit 1
    fi
    export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
    "$RULES_PYTHON" -m enro_terminal "${GAME_ARGS[@]}"
else
    "$SCRIPT_DIR/run_game.sh" "${RUNTIME_ARGS[@]}" -- "${GAME_ARGS[@]}"
fi

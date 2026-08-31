#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DEPS_DIR="$SCRIPT_DIR/.deps"
OVERLAY_DIR="$DEPS_DIR/ros-jazzy-cyclone-overlay"
OVERLAY_PREFIX="$OVERLAY_DIR/opt/ros/jazzy"

if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
    echo "[hata] /opt/ros/jazzy/setup.bash bulunamadı." >&2
    exit 1
fi
set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
set -u

# Makinedeki Fast-DDS/Fast-CDR paketleri farklı tarihlerden geldiği için ENRO
# sim süreci resmî CycloneDDS RMW paketlerini proje-lokal bir overlay'de kullanır.
# /opt/ros ve apt veritabanı değiştirilmez.
PACKAGES=(
    "ros-jazzy-iceoryx-binding-c=2.0.6-1noble.20260225.140829"
    "ros-jazzy-iceoryx-hoofs=2.0.6-1noble.20260225.055330"
    "ros-jazzy-iceoryx-posh=2.0.6-1noble.20260225.135341"
    "ros-jazzy-cyclonedds=0.10.5-1noble.20260225.142613"
    "ros-jazzy-rmw-cyclonedds-cpp=2.2.3-1noble.20260615.123728"
)

declare -A EXPECTED_SHA256=(
    [ros-jazzy-iceoryx-binding-c_2.0.6-1noble.20260225.140829_amd64.deb]="2c9559c485470c2decd27f7f89fa91f007de90e0b81bba12c1c552e5b32c2ccb"
    [ros-jazzy-iceoryx-hoofs_2.0.6-1noble.20260225.055330_amd64.deb]="b38948b370b5263477e839181cda41fac6e2887b618b5a785f196701289e60e2"
    [ros-jazzy-iceoryx-posh_2.0.6-1noble.20260225.135341_amd64.deb]="2a89f4969959f43af4db7ad5eed22381f14ff6f2fa237f1909651d60fd5814b5"
    [ros-jazzy-cyclonedds_0.10.5-1noble.20260225.142613_amd64.deb]="d6a34a96a1cf2900f6b8c884d583df92bad88ffaa359e2788697f4d614112f47"
    [ros-jazzy-rmw-cyclonedds-cpp_2.2.3-1noble.20260615.123728_amd64.deb]="e008b7bdd84fecc15130bbd9f6ed5aaa4993992d66324efba2e3e9739f88bf8c"
)

validate_overlay() {
    [[ -f "$OVERLAY_DIR/.complete" ]] || return 1
    [[ -e "$OVERLAY_PREFIX/lib/librmw_cyclonedds_cpp.so" ]] || return 1
    [[ -e "$OVERLAY_PREFIX/lib/x86_64-linux-gnu/libddsc.so.0" ]] || return 1
    RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    LD_LIBRARY_PATH="${OVERLAY_PREFIX}/lib:${OVERLAY_PREFIX}/lib/x86_64-linux-gnu:/opt/ros/jazzy/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
        python3 - <<'PY' >/dev/null 2>&1
import rclpy

rclpy.init()
node = rclpy.create_node("enro_cyclone_overlay_probe")
node.destroy_node()
rclpy.shutdown()
PY
}

if validate_overlay; then
    echo "[ros-runtime] İzole CycloneDDS overlay hazır."
    exit 0
fi

if [[ -e "$OVERLAY_DIR" ]]; then
    echo "[hata] Eksik/bozuk ROS overlay bulundu: $OVERLAY_DIR" >&2
    echo "       Dizini elle inceleyip kaldırdıktan sonra tekrar çalıştırın." >&2
    exit 1
fi
command -v apt-get >/dev/null || {
    echo "[hata] apt-get bulunamadı; resmî ROS paketleri indirilemiyor." >&2
    exit 1
}
command -v dpkg-deb >/dev/null || {
    echo "[hata] dpkg-deb bulunamadı; ROS paketleri açılamıyor." >&2
    exit 1
}

mkdir -p -- "$DEPS_DIR"
temp_dir="$(mktemp -d "$DEPS_DIR/ros-jazzy-cyclone-overlay.tmp.XXXXXX")"
cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if [[ "$temp_dir" == "$DEPS_DIR"/ros-jazzy-cyclone-overlay.tmp.* ]]; then
        rm -rf -- "$temp_dir"
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM
mkdir -p -- "$temp_dir/packages" "$temp_dir/root"

echo "[ros-runtime] Resmî CycloneDDS Jazzy paketleri indiriliyor..."
(
    cd -- "$temp_dir/packages"
    apt-get download "${PACKAGES[@]}"
)

for package_file in "$temp_dir"/packages/*.deb; do
    filename="$(basename -- "$package_file")"
    expected="${EXPECTED_SHA256[$filename]:-}"
    if [[ -z "$expected" ]]; then
        echo "[hata] Beklenmeyen ROS paketi indirildi: $filename" >&2
        exit 1
    fi
    actual="$(sha256sum "$package_file" | awk '{print $1}')"
    if [[ "$actual" != "$expected" ]]; then
        echo "[hata] ROS paket checksum uyuşmazlığı: $filename" >&2
        exit 1
    fi
    dpkg-deb -x "$package_file" "$temp_dir/root"
done

mkdir -p -- "$temp_dir/root/packages"
mv -- "$temp_dir"/packages/*.deb "$temp_dir/root/packages/"
touch "$temp_dir/root/.complete"
mv -- "$temp_dir/root" "$OVERLAY_DIR"

if ! validate_overlay; then
    echo "[hata] CycloneDDS overlay doğrulamasını geçemedi." >&2
    exit 1
fi
echo "[ros-runtime] İzole CycloneDDS overlay kuruldu: $OVERLAY_DIR"

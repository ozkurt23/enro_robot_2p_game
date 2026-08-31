#!/usr/bin/env bash
# Install a project-local CycloneDDS RMW when the host ROS snapshot is mixed.
set -Eeuo pipefail
IFS=$'\n\t'

workspace="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
deps_dir="$workspace/.deps"
overlay_dir="$deps_dir/ros-jazzy-cyclone-overlay"
overlay_prefix="$overlay_dir/opt/ros/jazzy"

if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
  echo "[hata] /opt/ros/jazzy/setup.bash bulunamadı." >&2
  exit 1
fi
set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
set -u

packages=(
  "ros-jazzy-iceoryx-binding-c=2.0.6-1noble.20260225.140829"
  "ros-jazzy-iceoryx-hoofs=2.0.6-1noble.20260225.055330"
  "ros-jazzy-iceoryx-posh=2.0.6-1noble.20260225.135341"
  "ros-jazzy-cyclonedds=0.10.5-1noble.20260225.142613"
  "ros-jazzy-rmw-cyclonedds-cpp=2.2.3-1noble.20260615.123728"
)

declare -A expected_sha256=(
  [ros-jazzy-iceoryx-binding-c_2.0.6-1noble.20260225.140829_amd64.deb]="2c9559c485470c2decd27f7f89fa91f007de90e0b81bba12c1c552e5b32c2ccb"
  [ros-jazzy-iceoryx-hoofs_2.0.6-1noble.20260225.055330_amd64.deb]="b38948b370b5263477e839181cda41fac6e2887b618b5a785f196701289e60e2"
  [ros-jazzy-iceoryx-posh_2.0.6-1noble.20260225.135341_amd64.deb]="2a89f4969959f43af4db7ad5eed22381f14ff6f2fa237f1909651d60fd5814b5"
  [ros-jazzy-cyclonedds_0.10.5-1noble.20260225.142613_amd64.deb]="d6a34a96a1cf2900f6b8c884d583df92bad88ffaa359e2788697f4d614112f47"
  [ros-jazzy-rmw-cyclonedds-cpp_2.2.3-1noble.20260615.123728_amd64.deb]="e008b7bdd84fecc15130bbd9f6ed5aaa4993992d66324efba2e3e9739f88bf8c"
)

validate_overlay() {
  [[ -f "$overlay_dir/.complete" ]] || return 1
  [[ -e "$overlay_prefix/lib/librmw_cyclonedds_cpp.so" ]] || return 1
  [[ -e "$overlay_prefix/lib/x86_64-linux-gnu/libddsc.so.0" ]] || return 1
  RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  LD_LIBRARY_PATH="$overlay_prefix/lib:$overlay_prefix/lib/x86_64-linux-gnu:/opt/ros/jazzy/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    python3 - <<'PY' >/dev/null 2>&1
import rclpy

rclpy.init()
node = rclpy.create_node("enro_cyclone_runtime_probe")
node.destroy_node()
rclpy.shutdown()
PY
}

if validate_overlay; then
  echo "[ros-runtime] İzole CycloneDDS overlay hazır."
  exit 0
fi

if [[ -e "$overlay_dir" ]]; then
  echo "[hata] Eksik/bozuk ROS runtime overlay bulundu: $overlay_dir" >&2
  echo "       Dizini inceleyip kaldırdıktan sonra tekrar çalıştırın." >&2
  exit 1
fi

command -v apt-get >/dev/null || {
  echo "[hata] apt-get bulunamadı; CycloneDDS paketleri indirilemiyor." >&2
  exit 1
}
command -v dpkg-deb >/dev/null || {
  echo "[hata] dpkg-deb bulunamadı; CycloneDDS paketleri açılamıyor." >&2
  exit 1
}

mkdir -p -- "$deps_dir"
temp_dir="$(mktemp -d "$deps_dir/ros-jazzy-cyclone-overlay.tmp.XXXXXX")"
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ "$temp_dir" == "$deps_dir"/ros-jazzy-cyclone-overlay.tmp.* ]]; then
    rm -rf -- "$temp_dir"
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM
mkdir -p -- "$temp_dir/packages" "$temp_dir/root"

echo "[ros-runtime] Resmî CycloneDDS Jazzy paketleri indiriliyor..."
(
  cd -- "$temp_dir/packages"
  apt-get download "${packages[@]}"
)

for package_file in "$temp_dir"/packages/*.deb; do
  filename="$(basename -- "$package_file")"
  expected="${expected_sha256[$filename]:-}"
  actual="$(sha256sum "$package_file" | awk '{print $1}')"
  if [[ -z "$expected" || "$actual" != "$expected" ]]; then
    echo "[hata] ROS paketi checksum uyuşmazlığı: $filename" >&2
    exit 1
  fi
  dpkg-deb -x "$package_file" "$temp_dir/root"
done

mkdir -p -- "$temp_dir/root/packages"
mv -- "$temp_dir"/packages/*.deb "$temp_dir/root/packages/"
touch "$temp_dir/root/.complete"
mv -- "$temp_dir/root" "$overlay_dir"

if ! validate_overlay; then
  echo "[hata] CycloneDDS runtime overlay doğrulanamadı." >&2
  exit 1
fi
echo "[ros-runtime] İzole CycloneDDS overlay kuruldu: $overlay_dir"

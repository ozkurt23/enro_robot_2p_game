"""Read-only Gazebo arena contract and physical end-state probe.

The game must not treat a successful transport RPC as proof that a cube is on
the destination table.  This module deliberately performs no movement and has
no set-pose capability: it validates the checked-in SDF and can sample a model
pose from Gazebo's read-only ``gz model -p`` command.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Callable, Sequence
import xml.etree.ElementTree as ET

from .types import Color


WORLD_NAME = "empty_robot_world"
CUBE_SIZE_METERS = 0.05
CUBE_MODELS = {
    Color.BLUE: "blue_cube",
    Color.GREEN: "green_cube",
    Color.RED: "red_cube",
}
CUBE_STARTS = {
    Color.BLUE: (3.0, 0.053, 0.675),
    Color.GREEN: (-0.06, 3.0, 0.675),
    Color.RED: (-3.0, -0.077, 0.675),
}
MAIN_TABLE_MODEL = "table_stack"
MAIN_TABLE_CENTER = (0.0, -3.0)
MAIN_TABLE_HALF_EXTENT = 0.30
MAIN_TABLE_CUBE_Z_RANGE = (0.60, 0.78)


class SimulationContractError(RuntimeError):
    """Raised when checked-in or live simulation state violates the contract."""


@dataclass(frozen=True, slots=True)
class ModelPose:
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in (self.x, self.y, self.z)
        ):
            raise SimulationContractError("model pozu üç sonlu sayı olmalı")

    def distance(self, other: "ModelPose") -> float:
        return math.sqrt(
            (self.x - other.x) ** 2
            + (self.y - other.y) ** 2
            + (self.z - other.z) ** 2
        )


@dataclass(frozen=True, slots=True)
class LivePoseVerification:
    color: Color
    samples: tuple[ModelPose, ...]
    stable: bool
    on_main_table: bool
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.color, Color):
            raise SimulationContractError("verification color bir Color olmalı")
        if (
            not isinstance(self.samples, tuple)
            or len(self.samples) < 2
            or not all(isinstance(sample, ModelPose) for sample in self.samples)
        ):
            raise SimulationContractError(
                "verification en az iki typed ModelPose örneği taşımalı"
            )
        if not isinstance(self.stable, bool) or not isinstance(self.on_main_table, bool):
            raise SimulationContractError("verification predicate alanları bool olmalı")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise SimulationContractError("verification detail boş olmayan string olmalı")

    @property
    def verified(self) -> bool:
        return self.stable and self.on_main_table


def default_world_path() -> Path:
    repository_root = Path(__file__).resolve().parents[3]
    return repository_root / "src/mecanum_robot_description/worlds/empty_robot_world.sdf"


def _float_tuple(text: str | None, *, count: int, where: str) -> tuple[float, ...]:
    if text is None:
        raise SimulationContractError(f"{where}: değer eksik")
    try:
        values = tuple(float(item) for item in text.split())
    except ValueError as exc:
        raise SimulationContractError(f"{where}: sayı listesi değil") from exc
    if len(values) != count or not all(math.isfinite(item) for item in values):
        raise SimulationContractError(f"{where}: {count} sonlu sayı bekleniyordu")
    return values


def _models(world: ET.Element) -> dict[str, ET.Element]:
    result: dict[str, ET.Element] = {}
    for model in world.findall("model"):
        name = model.get("name")
        if not name or name in result:
            raise SimulationContractError("world: model adları dolu ve benzersiz olmalı")
        result[name] = model
    return result


def _model_pose(model: ET.Element, where: str) -> tuple[float, ...]:
    return _float_tuple(model.findtext("pose"), count=6, where=f"{where}.pose")


def _first_box_size(model: ET.Element, kind: str, where: str) -> tuple[float, ...]:
    element = model.find(f"./link/{kind}/geometry/box/size")
    return _float_tuple(
        element.text if element is not None else None,
        count=3,
        where=f"{where}.{kind}.box.size",
    )


def validate_arena_world(path: Path | None = None) -> None:
    """Validate names, poses and geometry consumed by terminal/sim tests."""

    selected = (path or default_world_path()).resolve()
    try:
        root = ET.parse(selected).getroot()
    except (OSError, ET.ParseError) as exc:
        raise SimulationContractError(f"arena SDF okunamadı: {selected}: {exc}") from exc
    world = root.find("world")
    if world is None or world.get("name") != WORLD_NAME:
        raise SimulationContractError(f"world adı {WORLD_NAME!r} olmalı")
    models = _models(world)

    required = {MAIN_TABLE_MODEL, *(CUBE_MODELS.values())}
    missing = sorted(required - set(models))
    if missing:
        raise SimulationContractError("arena modelleri eksik: " + ", ".join(missing))

    table = models[MAIN_TABLE_MODEL]
    table_pose = _model_pose(table, MAIN_TABLE_MODEL)
    if not math.isclose(table_pose[0], MAIN_TABLE_CENTER[0], abs_tol=1e-9) or not math.isclose(
        table_pose[1], MAIN_TABLE_CENTER[1], abs_tol=1e-9
    ):
        raise SimulationContractError("ana masa merkezi terminal sözleşmesiyle uyuşmuyor")
    table_size = _first_box_size(table, "collision", MAIN_TABLE_MODEL)
    if not math.isclose(table_size[0] / 2.0, MAIN_TABLE_HALF_EXTENT, abs_tol=1e-9) or not math.isclose(
        table_size[1] / 2.0, MAIN_TABLE_HALF_EXTENT, abs_tol=1e-9
    ):
        raise SimulationContractError("ana masa sınırları terminal sözleşmesiyle uyuşmuyor")

    for color, model_name in CUBE_MODELS.items():
        model = models[model_name]
        pose = _model_pose(model, model_name)
        expected_pose = CUBE_STARTS[color]
        if any(
            not math.isclose(actual, expected, abs_tol=1e-9)
            for actual, expected in zip(pose[:3], expected_pose, strict=True)
        ):
            raise SimulationContractError(
                f"{model_name}: başlangıç pozu terminal sözleşmesiyle uyuşmuyor"
            )
        collision_size = _first_box_size(model, "collision", model_name)
        visual_size = _first_box_size(model, "visual", model_name)
        expected_size = (CUBE_SIZE_METERS,) * 3
        if collision_size != expected_size or visual_size != expected_size:
            raise SimulationContractError(
                f"{model_name}: collision ve visual küp boyutu {CUBE_SIZE_METERS:.3f} m olmalı"
            )
        if (model.findtext("static") or "false").strip().casefold() == "true":
            raise SimulationContractError(f"{model_name}: taşınabilir küp static olamaz")


_POSE_PATTERN = re.compile(
    r"Pose\s*\[\s*XYZ\s*\(m\)\s*\]\s*\[\s*RPY\s*\(rad\)\s*\]:"
    r"\s*\n\s*\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]"
)


def parse_gz_model_pose(output: str) -> ModelPose:
    match = _POSE_PATTERN.search(output)
    if match is None:
        raise SimulationContractError("Gazebo model pozu ayrıştırılamadı")
    pose = ModelPose(*(float(match.group(index)) for index in range(1, 4)))
    if not all(math.isfinite(item) for item in (pose.x, pose.y, pose.z)):
        raise SimulationContractError("Gazebo model pozu sonlu değil")
    return pose


def read_gazebo_model_pose(
    model_name: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ModelPose:
    if model_name not in CUBE_MODELS.values():
        raise SimulationContractError(f"izin verilmeyen Gazebo model adı: {model_name}")
    executable = shutil.which("gz")
    if executable is None:
        raise SimulationContractError("Gazebo `gz` aracı bulunamadı")
    try:
        completed = runner(
            [executable, "model", "-m", model_name, "-p"],
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SimulationContractError(f"Gazebo model pozu okunamadı: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        suffix = detail[-1] if detail else f"çıkış kodu {completed.returncode}"
        raise SimulationContractError(f"Gazebo model pozu okunamadı: {suffix}")
    return parse_gz_model_pose(completed.stdout)


def pose_is_on_main_table(pose: ModelPose) -> bool:
    return (
        abs(pose.x - MAIN_TABLE_CENTER[0]) <= MAIN_TABLE_HALF_EXTENT
        and abs(pose.y - MAIN_TABLE_CENTER[1]) <= MAIN_TABLE_HALF_EXTENT
        and MAIN_TABLE_CUBE_Z_RANGE[0] <= pose.z <= MAIN_TABLE_CUBE_Z_RANGE[1]
    )


def verify_live_delivery(
    color: Color,
    *,
    samples: int = 5,
    sample_interval_seconds: float = 0.25,
    maximum_drift_meters: float = 0.01,
    reader: Callable[[str], ModelPose] = read_gazebo_model_pose,
    sleeper: Callable[[float], None] = time.sleep,
) -> LivePoseVerification:
    """Observe a cube repeatedly; never mutate Gazebo or retry the action."""

    if samples < 2:
        raise ValueError("fiziksel kararlılık için en az iki örnek gerekir")
    if sample_interval_seconds < 0.0 or maximum_drift_meters < 0.0:
        raise ValueError("örnek aralığı ve drift sınırı negatif olamaz")
    model_name = CUBE_MODELS[color]
    observed: list[ModelPose] = []
    for index in range(samples):
        observed.append(reader(model_name))
        if index + 1 < samples:
            sleeper(sample_interval_seconds)
    stable = max(
        first.distance(second)
        for first, second in zip(observed, observed[1:], strict=False)
    ) <= maximum_drift_meters
    on_table = all(pose_is_on_main_table(pose) for pose in observed)
    if stable and on_table:
        detail = (
            f"{color.value} küp ana masa sınırında {samples} örnek boyunca kararlı"
        )
    elif not on_table:
        detail = f"{color.value} küp ana masa sınırında doğrulanmadı"
    else:
        detail = f"{color.value} küp kararlı değil; fiziksel hareket sürüyor olabilir"
    return LivePoseVerification(color, tuple(observed), stable, on_table, detail)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ENRO arena SDF sözleşmesini ve isteğe bağlı canlı küp son durumunu doğrula."
    )
    parser.add_argument("--world", type=Path, default=default_world_path())
    parser.add_argument("--live-color", choices=[color.value for color in Color])
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--sample-interval", type=float, default=0.25)
    args = parser.parse_args(argv)
    try:
        validate_arena_world(args.world)
        print(f"OK: arena sözleşmesi doğrulandı: {args.world}")
        if args.live_color:
            result = verify_live_delivery(
                Color(args.live_color),
                samples=args.samples,
                sample_interval_seconds=args.sample_interval,
            )
            print(("OK: " if result.verified else "HATA: ") + result.detail)
            if not result.verified:
                return 1
        return 0
    except (OSError, SimulationContractError, ValueError) as exc:
        print(f"HATA: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

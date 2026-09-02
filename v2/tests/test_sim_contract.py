"""The terminal's arena assumptions match SDF and live checks are read-only."""

from __future__ import annotations

from pathlib import Path
import ast
import subprocess

import pytest

from enro_terminal.sim_contract import (
    CUBE_SIZE_METERS,
    ModelPose,
    SimulationContractError,
    default_world_path,
    parse_gz_model_pose,
    pose_is_on_main_table,
    read_gazebo_model_pose,
    validate_arena_world,
    verify_live_delivery,
)
from enro_terminal.types import Color


GZ_OUTPUT = """Name: blue_cube
Pose [ XYZ (m) ] [ RPY (rad) ]:
[  0.010000  -2.980000  0.630000 ] [ 0.000000  0.000000  0.000000 ]
"""


def test_checked_in_arena_matches_the_versioned_terminal_contract():
    validate_arena_world()
    assert default_world_path().is_file()
    assert CUBE_SIZE_METERS == 0.05


def test_physics_demo_uses_the_real_arena_cube_size():
    demo_path = default_world_path().parents[3] / "v2/scripts/blue_to_main_demo.py"
    module = ast.parse(demo_path.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "BLUE_CUBE_SIZE"
            for target in node.targets
        )
    )
    assert ast.literal_eval(assignment.value) == CUBE_SIZE_METERS


def test_contract_rejects_geometry_drift_without_touching_the_real_world(tmp_path):
    changed = tmp_path / "changed.sdf"
    changed.write_text(
        default_world_path().read_text(encoding="utf-8").replace(
            "<size>0.05 0.05 0.05</size>",
            "<size>0.10 0.10 0.10</size>",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(SimulationContractError, match="[a-z]+_cube.*boyutu"):
        validate_arena_world(changed)


def test_gz_pose_parser_accepts_the_current_cli_shape_and_rejects_noise():
    assert parse_gz_model_pose(GZ_OUTPUT) == ModelPose(0.01, -2.98, 0.63)
    with pytest.raises(SimulationContractError, match="ayrıştırılamadı"):
        parse_gz_model_pose("success=true")


def test_pose_and_verification_domain_objects_reject_malformed_evidence():
    with pytest.raises(SimulationContractError, match="üç sonlu sayı"):
        ModelPose(float("nan"), -3.0, 0.63)

    from enro_terminal.sim_contract import LivePoseVerification

    with pytest.raises(SimulationContractError, match="en az iki"):
        LivePoseVerification(
            Color.BLUE,
            (ModelPose(0.0, -3.0, 0.63),),
            True,
            True,
            "yetersiz örnek",
        )


@pytest.mark.parametrize(
    ("pose", "expected"),
    [
        (ModelPose(0.0, -3.0, 0.63), True),
        (ModelPose(0.30, -2.70, 0.78), True),
        (ModelPose(0.31, -3.0, 0.63), False),
        (ModelPose(0.0, -2.69, 0.63), False),
        (ModelPose(0.0, -3.0, 0.90), False),
    ],
)
def test_main_table_predicate_has_explicit_xyz_boundaries(pose, expected):
    assert pose_is_on_main_table(pose) is expected


def test_live_verifier_requires_both_table_bounds_and_stability():
    stable = iter(
        (
            ModelPose(0.0, -3.0, 0.63),
            ModelPose(0.002, -3.001, 0.631),
            ModelPose(0.001, -3.0, 0.630),
        )
    )
    verified = verify_live_delivery(
        Color.BLUE,
        samples=3,
        reader=lambda _: next(stable),
        sleeper=lambda _: None,
    )
    moving = iter(
        (
            ModelPose(0.0, -3.0, 0.63),
            ModelPose(0.02, -3.0, 0.63),
        )
    )
    unverified = verify_live_delivery(
        Color.BLUE,
        samples=2,
        reader=lambda _: next(moving),
        sleeper=lambda _: None,
    )

    assert verified.verified
    assert not unverified.verified
    assert unverified.on_main_table
    assert not unverified.stable


def test_live_reader_uses_an_allowlisted_argv_without_shell(monkeypatch):
    monkeypatch.setattr("enro_terminal.sim_contract.shutil.which", lambda _: "/usr/bin/gz")
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=GZ_OUTPUT, stderr="")

    assert read_gazebo_model_pose("blue_cube", runner=runner) == ModelPose(
        0.01, -2.98, 0.63
    )
    assert calls[0][0] == ["/usr/bin/gz", "model", "-m", "blue_cube", "-p"]
    assert "shell" not in calls[0][1]
    with pytest.raises(SimulationContractError, match="izin verilmeyen"):
        read_gazebo_model_pose("$(touch /tmp/not-allowed)", runner=runner)


def test_default_world_path_stays_inside_the_repository_workspace():
    expected_suffix = Path(
        "src/mecanum_robot_description/worlds/empty_robot_world.sdf"
    )
    assert str(default_world_path()).endswith(str(expected_suffix))

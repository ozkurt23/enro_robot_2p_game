#!/usr/bin/env python3
"""Wait for the exact ros2_control controllers required by ENRO simulation."""

from __future__ import annotations

import argparse
import time

import rclpy
from controller_manager_msgs.srv import ListControllers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--controller",
        action="append",
        dest="controllers",
        required=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1.0 <= args.timeout <= 300.0:
        raise SystemExit("--timeout 1..300 saniye olmalı")

    required = set(args.controllers)
    rclpy.init()
    node = rclpy.create_node("enro_controller_probe")
    client = node.create_client(ListControllers, "/controller_manager/list_controllers")
    deadline = time.monotonic() + args.timeout
    last_states: dict[str, str] = {}
    try:
        while rclpy.ok() and time.monotonic() < deadline:
            if not client.wait_for_service(timeout_sec=0.5):
                continue
            future = client.call_async(ListControllers.Request())
            rclpy.spin_until_future_complete(node, future, timeout_sec=2.0)
            if not future.done() or future.result() is None:
                continue
            last_states = {
                controller.name: controller.state
                for controller in future.result().controller
            }
            if all(last_states.get(name) == "active" for name in required):
                print(
                    "CONTROLLERS_READY "
                    + " ".join(f"{name}=active" for name in sorted(required))
                )
                return 0
            time.sleep(0.25)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    summary = ", ".join(
        f"{name}={last_states.get(name, 'missing')}" for name in sorted(required)
    )
    print(f"CONTROLLERS_NOT_READY {summary}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


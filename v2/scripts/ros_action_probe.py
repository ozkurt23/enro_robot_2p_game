#!/usr/bin/env python3
"""Wait for one typed ROS action server without the ros2cli daemon cache."""

from __future__ import annotations

import argparse

import rclpy
from rclpy.action import ActionClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", required=True, choices=("moveit", "nav2"))
    parser.add_argument("--name", required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    if args.kind == "moveit":
        from moveit_msgs.action import MoveGroup

        action_type = MoveGroup
    else:
        from nav2_msgs.action import NavigateToPose

        action_type = NavigateToPose

    rclpy.init()
    node = rclpy.create_node("enro_action_readiness_probe")
    try:
        client = ActionClient(node, action_type, args.name)
        ready = client.wait_for_server(timeout_sec=args.timeout)
        if ready:
            print(f"ACTION_READY kind={args.kind} name={args.name}", flush=True)
            return 0
        print(f"ACTION_TIMEOUT kind={args.kind} name={args.name}", flush=True)
        return 1
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())

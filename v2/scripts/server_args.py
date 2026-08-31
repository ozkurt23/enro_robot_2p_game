#!/usr/bin/env python3
"""Build the exact llama-server argv for the pinned runtime.

The output is NUL-delimited so the supervising shell never reparses quoting.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from runtime_lock import DEFAULT_LOCK, load_lock


def _gpu_layers(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {"all", "auto"}:
        return normalized
    try:
        count = int(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "gpu layers; all, auto veya negatif olmayan tamsayı olmalı"
        ) from exc
    if count < 0:
        raise argparse.ArgumentTypeError("gpu layers negatif olamaz")
    return str(count)


def build_server_args(
    lock: dict,
    model_path: Path,
    *,
    gpu_layers: str | None = None,
) -> list[str]:
    server = lock["server"]
    args = [
        "--model", str(model_path),
        "--alias", server["alias"],
        "--host", server["host"],
        "--port", str(server["port"]),
        "--ctx-size", str(server["ctx_size"]),
        "--parallel", str(server["parallel"]),
        "--batch-size", str(server["batch_size"]),
        "--ubatch-size", str(server["ubatch_size"]),
        "--n-gpu-layers", gpu_layers or server["gpu_layers"],
        "--flash-attn", server["flash_attention"],
        "--cache-type-k", server["cache_type_k"],
        "--cache-type-v", server["cache_type_v"],
    ]
    if server["jinja"]:
        args.append("--jinja")
    args.extend(["--reasoning", server["reasoning"]])
    if not server["mmproj"]:
        args.append("--no-mmproj")
    if not server["webui"]:
        args.append("--no-webui")
    if not server["slots_endpoint"]:
        args.append("--no-slots")
    if server["offline"]:
        args.append("--offline")
    return args


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument(
        "--gpu-layers",
        type=_gpu_layers,
        default=None,
        help="lock profilini bu süreç için all, auto veya N ile geçersiz kıl",
    )
    parser.add_argument(
        "--format", choices=("nul", "lines"), default="nul",
        help="lines yalnız insan denetimi içindir",
    )
    args = parser.parse_args(argv)
    values = build_server_args(
        load_lock(args.lock.resolve()),
        args.model.resolve(),
        gpu_layers=args.gpu_layers,
    )
    if args.format == "nul":
        for value in values:
            sys.stdout.buffer.write(value.encode("utf-8") + b"\0")
    else:
        for value in values:
            print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

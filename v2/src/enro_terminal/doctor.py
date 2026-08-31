"""Read-only installation diagnostics."""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import sys
import tomllib

from .llm_client import LlamaCppClient, LlamaCppConfig, LlmError
from .persona_config import PersonaConfigError, load_persona_catalog
from .types import PersonaId


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="enro-terminal-doctor")
    parser.add_argument("--llm-url", default=None)
    parser.add_argument("--require-server", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    failures = 0
    print(f"Python       : {platform.python_version()} ({sys.executable})")
    supported = sys.version_info >= (3, 12)
    print(f"Python >=3.12: {'OK' if supported else 'HATA'}")
    failures += not supported
    py_trees_ok = importlib.util.find_spec("py_trees") is not None
    print(f"py_trees     : {'OK' if py_trees_ok else 'EKSİK'}")
    failures += not py_trees_ok
    print(f"nvidia-smi   : {shutil.which('nvidia-smi') or 'bulunamadı'}")

    try:
        persona_count = len(load_persona_catalog())
        print(f"persona TOML : OK ({persona_count}/{len(PersonaId)})")
    except PersonaConfigError as exc:
        print(f"persona TOML : HATA ({exc})")
        failures += 1

    root = Path(__file__).resolve().parents[2]
    try:
        lock = tomllib.loads((root / "runtime.lock.toml").read_text(encoding="utf-8"))
        llama = lock["llama_cpp"]
        model = lock["model"]
        local_server = Path(
            os.environ.get(
                "ENRO_LLAMA_SERVER_BIN",
                root / ".deps" / llama["extract_dir"] / llama["server_relpath"],
            )
        )
        local_model = Path(
            os.environ.get("ENRO_MODEL_PATH", root / ".models" / model["file"])
        )
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        print(f"runtime lock : HATA ({exc})")
        failures += 1
        local_server = root / ".deps" / "<geçersiz>" / "llama-server"
        local_model = root / ".models" / "<geçersiz>.gguf"
    server_file_ok = local_server.is_file()
    model_file_ok = local_model.is_file()
    print(f"llama-server : {local_server} {'OK' if server_file_ok else 'EKSİK'}")
    print(f"model        : {local_model} {'OK' if model_file_ok else 'EKSİK'}")
    failures += not server_file_ok
    failures += not model_file_ok

    config = LlamaCppConfig.from_environment(base_url=args.llm_url)
    try:
        client = LlamaCppClient(config)
        health = client.health()
        models = client.model_ids() if health else ()
        print(f"sunucu       : {'HAZIR' if health else 'HAZIR DEĞİL'} {models}")
    except LlmError as exc:
        print(f"sunucu       : kapalı ({exc})")
        if args.require_server:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

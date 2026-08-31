#!/usr/bin/env python3
"""Load and strictly validate the pinned local-AI runtime manifest.

Shell entrypoints consume ``env0`` instead of sourcing TOML or evaluating text.
The NUL-delimited protocol keeps paths and URLs as data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlparse


V2_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = V2_ROOT / "runtime.lock.toml"
HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z")


class LockError(ValueError):
    """The runtime lock is incomplete, unsafe, or internally inconsistent."""


def _fail(message: str) -> NoReturn:
    raise LockError(message)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{name}: TOML tablosu bekleniyordu")
    return value


def _required(table: dict[str, Any], keys: set[str], name: str) -> None:
    missing = keys - set(table)
    extra = set(table) - keys
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append("eksik=" + ",".join(sorted(missing)))
        if extra:
            details.append("fazla=" + ",".join(sorted(extra)))
        _fail(f"{name}: " + "; ".join(details))


def _string(table: dict[str, Any], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        _fail(f"{where}.{key}: boş olmayan string bekleniyordu")
    if "\x00" in value or "\n" in value or "\r" in value:
        _fail(f"{where}.{key}: kontrol karakteri içeremez")
    return value


def _positive_int(table: dict[str, Any], key: str, where: str) -> int:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(f"{where}.{key}: pozitif integer bekleniyordu")
    return value


def _bool(table: dict[str, Any], key: str, where: str) -> bool:
    value = table.get(key)
    if not isinstance(value, bool):
        _fail(f"{where}.{key}: bool bekleniyordu")
    return value


def _safe_name(value: str, where: str) -> None:
    if not SAFE_NAME.fullmatch(value) or value in {".", ".."}:
        _fail(f"{where}: güvenli tek yol bileşeni olmalı")


def _https_url(value: str, where: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        _fail(f"{where}: kimlik bilgisi içermeyen https URL bekleniyordu")
    if parsed.query or parsed.fragment:
        _fail(f"{where}: mutable query/fragment içermemeli")


def load_lock(path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LockError(f"runtime lock okunamadı: {path}: {exc}") from exc

    _required(data, {"schema_version", "llama_cpp", "model", "server", "python"}, "root")
    if data["schema_version"] != 1:
        _fail("schema_version: yalnız sürüm 1 destekleniyor")

    llama = _mapping(data["llama_cpp"], "llama_cpp")
    model = _mapping(data["model"], "model")
    server = _mapping(data["server"], "server")
    python = _mapping(data["python"], "python")

    _required(
        llama,
        {
            "release", "version", "commit", "backend", "asset_name",
            "asset_url", "asset_sha256", "asset_size", "extract_dir",
            "server_relpath", "cli_relpath", "bench_relpath",
            "attestation_url",
        },
        "llama_cpp",
    )
    _required(
        model,
        {
            "base_repo", "base_revision", "repo", "revision", "file",
            "url", "sha256", "size", "quantization", "license",
            "text_only",
        },
        "model",
    )
    _required(
        server,
        {
            "host", "port", "api_base_path", "health_path", "alias",
            "ctx_size", "parallel", "batch_size", "ubatch_size",
            "gpu_layers", "flash_attention", "cache_type_k",
            "cache_type_v", "jinja", "reasoning", "mmproj", "webui",
            "slots_endpoint", "offline", "health_timeout_seconds",
            "warmup_timeout_seconds", "shutdown_timeout_seconds",
        },
        "server",
    )
    _required(python, {"version", "venv_dir", "wheels"}, "python")

    release = _string(llama, "release", "llama_cpp")
    version = _string(llama, "version", "llama_cpp")
    commit = _string(llama, "commit", "llama_cpp")
    backend = _string(llama, "backend", "llama_cpp")
    asset_name = _string(llama, "asset_name", "llama_cpp")
    asset_url = _string(llama, "asset_url", "llama_cpp")
    asset_sha = _string(llama, "asset_sha256", "llama_cpp")
    extract_dir = _string(llama, "extract_dir", "llama_cpp")
    if not HEX_40.fullmatch(commit):
        _fail("llama_cpp.commit: 40 haneli küçük-hex bekleniyordu")
    if not HEX_64.fullmatch(asset_sha):
        _fail("llama_cpp.asset_sha256: 64 haneli küçük-hex bekleniyordu")
    if backend != "vulkan":
        _fail("llama_cpp.backend: bu profil yalnız vulkan kabul eder")
    if version != "v0.2.0" or release != "b10566":
        _fail("llama_cpp: denetlenmiş v0.2.0/b10566 pini değişmiş")
    for key in ("asset_name", "extract_dir", "server_relpath", "cli_relpath", "bench_relpath"):
        _safe_name(_string(llama, key, "llama_cpp"), f"llama_cpp.{key}")
    _https_url(asset_url, "llama_cpp.asset_url")
    _https_url(_string(llama, "attestation_url", "llama_cpp"), "llama_cpp.attestation_url")
    if f"/releases/download/{release}/{asset_name}" not in asset_url:
        _fail("llama_cpp.asset_url: release ve asset adıyla eşleşmiyor")
    if extract_dir != f"llama-{release}":
        _fail("llama_cpp.extract_dir: resmî arşiv köküyle eşleşmiyor")
    _positive_int(llama, "asset_size", "llama_cpp")

    base_revision = _string(model, "base_revision", "model")
    revision = _string(model, "revision", "model")
    model_file = _string(model, "file", "model")
    model_url = _string(model, "url", "model")
    model_sha = _string(model, "sha256", "model")
    if not HEX_40.fullmatch(base_revision) or not HEX_40.fullmatch(revision):
        _fail("model revision alanları 40 haneli küçük-hex olmalı")
    if not HEX_64.fullmatch(model_sha):
        _fail("model.sha256: 64 haneli küçük-hex bekleniyordu")
    _safe_name(model_file, "model.file")
    _https_url(model_url, "model.url")
    if "/resolve/main/" in model_url or f"/resolve/{revision}/{model_file}" not in model_url:
        _fail("model.url: immutable revision ve dosya adıyla eşleşmiyor")
    if _string(model, "quantization", "model") != "Q4_K_M":
        _fail("model.quantization: denetlenmiş Q4_K_M pini değişmiş")
    if not _bool(model, "text_only", "model"):
        _fail("model.text_only: MVP için true olmalı")
    _positive_int(model, "size", "model")

    if _string(server, "host", "server") != "127.0.0.1":
        _fail("server.host: yalnız loopback 127.0.0.1 kabul edilir")
    port = _positive_int(server, "port", "server")
    if port > 65535:
        _fail("server.port: 1..65535 aralığında olmalı")
    for key in (
        "ctx_size", "parallel", "batch_size", "ubatch_size",
        "health_timeout_seconds", "warmup_timeout_seconds",
        "shutdown_timeout_seconds",
    ):
        _positive_int(server, key, "server")
    if server["parallel"] != 1:
        _fail("server.parallel: tek oyunculu MVP için 1 olmalı")
    if _string(server, "gpu_layers", "server") != "all":
        _fail("server.gpu_layers: tam offload için all olmalı")
    if _string(server, "flash_attention", "server") not in {"auto", "on", "off"}:
        _fail("server.flash_attention: auto/on/off olmalı")
    for key in ("cache_type_k", "cache_type_v"):
        if _string(server, key, "server") not in {"f16", "bf16", "q8_0"}:
            _fail(f"server.{key}: beklenmeyen KV cache türü")
    if not _bool(server, "jinja", "server"):
        _fail("server.jinja: Qwen template için true olmalı")
    if _string(server, "reasoning", "server") != "off":
        _fail("server.reasoning: NLU profili için off olmalı")
    for key in ("mmproj", "webui", "slots_endpoint"):
        if _bool(server, key, "server"):
            _fail(f"server.{key}: text-only dar profil için false olmalı")
    if not _bool(server, "offline", "server"):
        _fail("server.offline: runtime ağ erişimini kapatmak için true olmalı")
    for key in ("api_base_path", "health_path"):
        value = _string(server, key, "server")
        if not value.startswith("/") or ".." in value or "//" in value:
            _fail(f"server.{key}: güvenli absolute URL path olmalı")
    _safe_name(_string(server, "alias", "server"), "server.alias")

    if _string(python, "version", "python") != "3.12":
        _fail("python.version: MVP runtime için 3.12 olmalı")
    if _string(python, "venv_dir", "python") != ".deps/game-python":
        _fail("python.venv_dir: izole .deps/game-python olmalı")
    wheels = python.get("wheels")
    if not isinstance(wheels, list):
        _fail("python.wheels: array-of-tables bekleniyordu")
    required_wheels = {
        "pyparsing": "3.2.3",
        "pydot": "4.0.1",
        "py_trees": "2.5.0",
    }
    seen_wheels: dict[str, str] = {}
    for index, raw_wheel in enumerate(wheels):
        wheel = _mapping(raw_wheel, f"python.wheels[{index}]")
        _required(wheel, {"name", "version", "file", "url", "sha256", "size"}, f"python.wheels[{index}]")
        name = _string(wheel, "name", f"python.wheels[{index}]")
        version_value = _string(wheel, "version", f"python.wheels[{index}]")
        file_name = _string(wheel, "file", f"python.wheels[{index}]")
        url = _string(wheel, "url", f"python.wheels[{index}]")
        sha = _string(wheel, "sha256", f"python.wheels[{index}]")
        _safe_name(file_name, f"python.wheels[{index}].file")
        if not file_name.endswith(".whl"):
            _fail(f"python.wheels[{index}].file: yalnız wheel kabul edilir")
        _https_url(url, f"python.wheels[{index}].url")
        if urlparse(url).hostname != "files.pythonhosted.org" or not url.endswith("/" + file_name):
            _fail(f"python.wheels[{index}].url: immutable PyPI file URL bekleniyordu")
        if not HEX_64.fullmatch(sha):
            _fail(f"python.wheels[{index}].sha256: 64 haneli küçük-hex bekleniyordu")
        _positive_int(wheel, "size", f"python.wheels[{index}]")
        if name in seen_wheels:
            _fail(f"python.wheels: yinelenen paket: {name}")
        seen_wheels[name] = version_value
    if seen_wheels != required_wheels:
        _fail(f"python.wheels: beklenen pin seti değişmiş: {seen_wheels!r}")

    return data


def shell_environment(data: dict[str, Any]) -> dict[str, str]:
    llama = data["llama_cpp"]
    model = data["model"]
    server = data["server"]
    python = data["python"]

    def scalar(value: Any) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value)

    mapping = {
        "ENRO_LOCK_SCHEMA_VERSION": data["schema_version"],
        "ENRO_LLAMA_RELEASE": llama["release"],
        "ENRO_LLAMA_VERSION": llama["version"],
        "ENRO_LLAMA_COMMIT": llama["commit"],
        "ENRO_LLAMA_BACKEND": llama["backend"],
        "ENRO_LLAMA_ASSET_NAME": llama["asset_name"],
        "ENRO_LLAMA_ASSET_URL": llama["asset_url"],
        "ENRO_LLAMA_ASSET_SHA256": llama["asset_sha256"],
        "ENRO_LLAMA_ASSET_SIZE": llama["asset_size"],
        "ENRO_LLAMA_EXTRACT_DIR": llama["extract_dir"],
        "ENRO_LLAMA_SERVER_RELPATH": llama["server_relpath"],
        "ENRO_LLAMA_CLI_RELPATH": llama["cli_relpath"],
        "ENRO_LLAMA_BENCH_RELPATH": llama["bench_relpath"],
        "ENRO_LLAMA_ATTESTATION_URL": llama["attestation_url"],
        "ENRO_MODEL_BASE_REPO": model["base_repo"],
        "ENRO_MODEL_BASE_REVISION": model["base_revision"],
        "ENRO_MODEL_REPO": model["repo"],
        "ENRO_MODEL_REVISION": model["revision"],
        "ENRO_MODEL_FILE": model["file"],
        "ENRO_MODEL_URL": model["url"],
        "ENRO_MODEL_SHA256": model["sha256"],
        "ENRO_MODEL_SIZE": model["size"],
        "ENRO_MODEL_QUANTIZATION": model["quantization"],
        "ENRO_SERVER_HOST": server["host"],
        "ENRO_SERVER_PORT": server["port"],
        "ENRO_SERVER_API_BASE_PATH": server["api_base_path"],
        "ENRO_SERVER_HEALTH_PATH": server["health_path"],
        "ENRO_SERVER_ALIAS": server["alias"],
        "ENRO_SERVER_CTX_SIZE": server["ctx_size"],
        "ENRO_SERVER_PARALLEL": server["parallel"],
        "ENRO_SERVER_BATCH_SIZE": server["batch_size"],
        "ENRO_SERVER_UBATCH_SIZE": server["ubatch_size"],
        "ENRO_SERVER_GPU_LAYERS": server["gpu_layers"],
        "ENRO_SERVER_FLASH_ATTENTION": server["flash_attention"],
        "ENRO_SERVER_CACHE_TYPE_K": server["cache_type_k"],
        "ENRO_SERVER_CACHE_TYPE_V": server["cache_type_v"],
        "ENRO_SERVER_JINJA": server["jinja"],
        "ENRO_SERVER_REASONING": server["reasoning"],
        "ENRO_SERVER_MMPROJ": server["mmproj"],
        "ENRO_SERVER_WEBUI": server["webui"],
        "ENRO_SERVER_SLOTS_ENDPOINT": server["slots_endpoint"],
        "ENRO_SERVER_OFFLINE": server["offline"],
        "ENRO_SERVER_HEALTH_TIMEOUT": server["health_timeout_seconds"],
        "ENRO_SERVER_WARMUP_TIMEOUT": server["warmup_timeout_seconds"],
        "ENRO_SERVER_SHUTDOWN_TIMEOUT": server["shutdown_timeout_seconds"],
        "ENRO_PYTHON_VERSION": python["version"],
        "ENRO_PYTHON_VENV_DIR": python["venv_dir"],
    }
    return {key: scalar(value) for key, value in mapping.items()}


def _get_dotted(data: dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            _fail(f"bilinmeyen lock anahtarı: {dotted}")
        current = current[part]
    if isinstance(current, (dict, list)):
        _fail(f"scalar lock anahtarı bekleniyordu: {dotted}")
    return current


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="lock'u doğrula")
    subparsers.add_parser("env0", help="shell için NUL-delimited key/value yaz")
    subparsers.add_parser("wheels0", help="pinli wheel alanlarını NUL-delimited yaz")
    subparsers.add_parser("json", help="doğrulanmış lock'u JSON yaz")
    get_parser = subparsers.add_parser("get", help="tek bir dotted scalar alan yaz")
    get_parser.add_argument("key")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = load_lock(args.lock.resolve())
        if args.command == "validate":
            print(f"OK: {args.lock.resolve()}")
        elif args.command == "env0":
            for key, value in shell_environment(data).items():
                sys.stdout.buffer.write(key.encode("ascii") + b"\0")
                sys.stdout.buffer.write(value.encode("utf-8") + b"\0")
        elif args.command == "wheels0":
            for wheel in data["python"]["wheels"]:
                for field in ("name", "version", "file", "url", "sha256", "size"):
                    sys.stdout.buffer.write(str(wheel[field]).encode("utf-8") + b"\0")
        elif args.command == "json":
            json.dump(data, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
            sys.stdout.write("\n")
        elif args.command == "get":
            value = _get_dotted(data, args.key)
            if isinstance(value, bool):
                print("true" if value else "false")
            else:
                print(value)
        return 0
    except LockError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import io
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
V2_ROOT = SCRIPTS.parent
sys.path.insert(0, os.fspath(SCRIPTS))

from local_ai_probe import completion_payload  # noqa: E402
from runtime_lock import DEFAULT_LOCK, load_lock, shell_environment  # noqa: E402
from safe_extract_tar import UnsafeArchive, extract_verified_archive  # noqa: E402
from server_args import build_server_args  # noqa: E402
from stop_session import _session_members  # noqa: E402


class RuntimeLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lock = load_lock(DEFAULT_LOCK)

    def test_supply_chain_pins_are_immutable(self) -> None:
        llama = self.lock["llama_cpp"]
        model = self.lock["model"]
        self.assertEqual(llama["release"], "b10566")
        self.assertEqual(llama["version"], "v0.2.0")
        self.assertEqual(llama["commit"], "bb4caa7540188872173c44d161602d9271386413")
        self.assertEqual(
            llama["asset_sha256"],
            "773b3445348b5527dfe1601a7a37d9cf0e144a1023eee115351334bdb851b164",
        )
        self.assertNotIn("/latest/", llama["asset_url"])
        self.assertNotIn("/resolve/main/", model["url"])
        self.assertIn(model["revision"], model["url"])
        self.assertEqual(
            model["sha256"],
            "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8",
        )

    def test_shell_environment_contains_only_scalar_enro_names(self) -> None:
        environment = shell_environment(self.lock)
        self.assertGreater(len(environment), 30)
        self.assertTrue(all(name.startswith("ENRO_") for name in environment))
        self.assertTrue(all(isinstance(value, str) for value in environment.values()))
        self.assertTrue(all("\x00" not in value and "\n" not in value for value in environment.values()))

    def test_python_runtime_wheels_are_fully_pinned(self) -> None:
        self.assertEqual(self.lock["python"]["venv_dir"], ".deps/game-python")
        wheels = {wheel["name"]: wheel for wheel in self.lock["python"]["wheels"]}
        self.assertEqual(
            {name: wheel["version"] for name, wheel in wheels.items()},
            {"pyparsing": "3.2.3", "pydot": "4.0.1", "py_trees": "2.5.0"},
        )
        for wheel in wheels.values():
            self.assertTrue(wheel["url"].startswith("https://files.pythonhosted.org/"))
            self.assertTrue(wheel["url"].endswith("/" + wheel["file"]))
            self.assertEqual(len(wheel["sha256"]), 64)
            self.assertGreater(wheel["size"], 0)

    def test_server_profile_is_loopback_text_only_and_offline(self) -> None:
        model_path = V2_ROOT / ".models" / self.lock["model"]["file"]
        args = build_server_args(self.lock, model_path)

        def value_after(flag: str) -> str:
            return args[args.index(flag) + 1]

        self.assertEqual(value_after("--host"), "127.0.0.1")
        self.assertEqual(value_after("--reasoning"), "off")
        self.assertEqual(value_after("--n-gpu-layers"), "all")
        self.assertIn("--jinja", args)
        self.assertIn("--no-mmproj", args)
        self.assertIn("--no-webui", args)
        self.assertIn("--no-slots", args)
        self.assertIn("--offline", args)
        self.assertNotIn("--tools", args)
        self.assertNotIn("--agent", args)
        self.assertNotIn("-hf", args)
        self.assertNotIn("--mmproj", args)

        auto_args = build_server_args(self.lock, model_path, gpu_layers="auto")
        self.assertEqual(
            auto_args[auto_args.index("--n-gpu-layers") + 1],
            "auto",
        )

    def test_probe_uses_a_flat_strict_schema(self) -> None:
        payload = completion_payload("test-model", "mavi cismi getir", structured=True)
        response_format = payload["response_format"]
        schema = response_format["json_schema"]["schema"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), {"operation", "color"})
        serialized = repr(schema)
        for unsupported in ("$ref", "oneOf", "anyOf", "prefixItems", "patternProperties"):
            self.assertNotIn(unsupported, serialized)


class SafeExtractionTests(unittest.TestCase):
    def _archive_with_member(self, archive: Path, member_name: str) -> None:
        content = b"runtime-test\n"
        with tarfile.open(archive, "w:gz") as bundle:
            root = tarfile.TarInfo("llama-b10566")
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            bundle.addfile(root)
            member = tarfile.TarInfo(member_name)
            member.size = len(content)
            member.mode = 0o755
            bundle.addfile(member, io.BytesIO(content))

    def test_extracts_expected_single_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            archive = temp / "runtime.tar.gz"
            destination = temp / "extract"
            destination.mkdir()
            self._archive_with_member(archive, "llama-b10566/llama-server")
            root = extract_verified_archive(archive, destination, "llama-b10566")
            self.assertEqual((root / "llama-server").read_bytes(), b"runtime-test\n")

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            archive = temp / "bad.tar.gz"
            destination = temp / "extract"
            destination.mkdir()
            self._archive_with_member(archive, "llama-b10566/../../escape")
            with self.assertRaises(UnsafeArchive):
                extract_verified_archive(archive, destination, "llama-b10566")
            self.assertFalse((temp / "escape").exists())

    def test_rejects_another_top_level_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            archive = temp / "bad-root.tar.gz"
            destination = temp / "extract"
            destination.mkdir()
            self._archive_with_member(archive, "not-llama/llama-server")
            with self.assertRaises(UnsafeArchive):
                extract_verified_archive(archive, destination, "llama-b10566")


class SessionSupervisorTests(unittest.TestCase):
    def test_current_process_is_found_in_its_real_session(self) -> None:
        self.assertIn(os.getpid(), _session_members(os.getsid(0)))

    def test_impossible_process_session_is_empty(self) -> None:
        self.assertEqual(_session_members(2_147_483_647), ())


if __name__ == "__main__":
    unittest.main()

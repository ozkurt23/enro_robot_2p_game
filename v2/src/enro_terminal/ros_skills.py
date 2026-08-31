"""Small, dependency-free bridge to operator-triggered ROS skills.

The local-Qwen environment intentionally does not import rclpy.  ROS skills run
in the ROS Jazzy workspace and are invoked through the typed ``ros2 service``
CLI.  This keeps the LLM runtime isolated while preserving a strict service
allowlist: no model output is ever interpolated into a shell command.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
import subprocess
from typing import Callable


_ROS_SERVICE_NAME = re.compile(r"^/[A-Za-z][A-Za-z0-9_/]*$")
_SUCCESS = re.compile(r"\bsuccess\s*[=:]\s*(?:True|true)\b")
_MESSAGE = re.compile(r"\bmessage\s*=\s*(['\"])(.*?)\1", re.DOTALL)


@dataclass(frozen=True, slots=True)
class SkillCall:
    success: bool
    message: str


def _call_trigger(
    service_name: str,
    *,
    timeout_seconds: float,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    label: str,
) -> SkillCall:
    """Call one already-validated Trigger service without shell expansion."""
    if shutil.which("ros2") is None:
        return SkillCall(False, "ros2 komutu bulunamadı; ROS Jazzy ortamı yüklü değil.")

    command = [
        "ros2",
        "service",
        "call",
        service_name,
        "std_srvs/srv/Trigger",
        "{}",
    ]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SkillCall(
            False,
            f"{label} {timeout_seconds:.0f} saniyede sonuçlanmadı.",
        )
    except OSError as exc:
        return SkillCall(False, f"{label} çağrılamadı: {exc}")

    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    if completed.returncode != 0:
        detail = output.splitlines()[-1] if output else f"çıkış kodu {completed.returncode}"
        return SkillCall(False, f"{label} servis çağrısı başarısız: {detail}")

    success = bool(_SUCCESS.search(output))
    match = _MESSAGE.search(output)
    message = match.group(2) if match else f"{label} sonuç döndürdü."
    if not success and match is None:
        message = f"{label} servisinden doğrulanabilir başarı yanıtı alınamadı."
    return SkillCall(success, message)


class GraspSkillClient:
    """Call the single allowlisted ``std_srvs/Trigger`` grasp service."""

    def __init__(
        self,
        service_name: str = "/enro/grasp_workpiece",
        *,
        timeout_seconds: float = 180.0,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        if not _ROS_SERVICE_NAME.fullmatch(service_name):
            raise ValueError("Geçersiz mutlak ROS servis adı")
        if not 1.0 <= timeout_seconds <= 600.0:
            raise ValueError("ROS skill timeout'u 1..600 saniye olmalı")
        self.service_name = service_name
        self.timeout_seconds = timeout_seconds
        self._runner = runner

    def grasp(self) -> SkillCall:
        return _call_trigger(
            self.service_name,
            timeout_seconds=self.timeout_seconds,
            runner=self._runner,
            label="Kavrama skill'i",
        )


class DeliverySkillClient:
    """Allowlisted colored-object delivery services used after policy approval."""

    COLORS = frozenset({"blue", "green", "red"})

    def __init__(
        self,
        service_prefix: str = "/enro/deliver_",
        *,
        timeout_seconds: float = 360.0,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        services = {
            color: f"{service_prefix}{color}" for color in self.COLORS
        }
        if not all(_ROS_SERVICE_NAME.fullmatch(name) for name in services.values()):
            raise ValueError("Geçersiz teslimat ROS servis öneki")
        if not 1.0 <= timeout_seconds <= 600.0:
            raise ValueError("ROS teslimat timeout'u 1..600 saniye olmalı")
        self.services = services
        self.timeout_seconds = timeout_seconds
        self._runner = runner

    def deliver(self, color: str) -> SkillCall:
        normalized = color.strip().casefold()
        if normalized not in self.COLORS:
            return SkillCall(False, f"İzin verilmeyen teslimat rengi: {color}")
        return _call_trigger(
            self.services[normalized],
            timeout_seconds=self.timeout_seconds,
            runner=self._runner,
            label=f"{normalized} fiziksel taşıma case'i",
        )

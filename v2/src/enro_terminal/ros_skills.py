"""Small, dependency-free bridge to operator-triggered ROS skills.

The local-Qwen environment intentionally does not import rclpy.  ROS skills run
in the ROS Jazzy workspace and are invoked through the typed ``ros2 service``
CLI.  This keeps the LLM runtime isolated while preserving a strict service
allowlist: no model output is ever interpolated into a shell command.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import shutil
import subprocess
from typing import Callable


_ROS_SERVICE_NAME = re.compile(
    r"^/[A-Za-z][A-Za-z0-9_]*(?:/[A-Za-z][A-Za-z0-9_]*)*$"
)
_TRIGGER_RESPONSE = re.compile(
    r"\b(?:[A-Za-z_][A-Za-z0-9_.]*\.)?Trigger_Response\s*\(\s*"
    r"success\s*=\s*(True|False)\s*,\s*"
    r"message\s*=\s*(['\"])(.*?)\2\s*\)",
    re.IGNORECASE | re.DOTALL,
)


class SkillEvidence(str, Enum):
    """What the terminal itself observed at the ROS boundary.

    A successful ``std_srvs/Trigger`` response is an acknowledgement from the
    service.  It is deliberately not named "physical verification": this
    process has no independent Gazebo pose/contact telemetry.
    """

    NONE = "none"
    TRIGGER_RESPONSE = "trigger_response"


@dataclass(frozen=True, slots=True)
class SkillCall:
    success: bool
    message: str
    evidence: SkillEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise TypeError("SkillCall.success bool olmalı")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("SkillCall.message boş olmayan string olmalı")
        evidence = self.evidence
        if evidence is None:
            # Keep the two-argument constructor source-compatible for test
            # doubles and older callers while making its evidence explicit.
            evidence = (
                SkillEvidence.TRIGGER_RESPONSE
                if self.success
                else SkillEvidence.NONE
            )
            object.__setattr__(self, "evidence", evidence)
        elif not isinstance(evidence, SkillEvidence):
            raise TypeError("SkillCall.evidence SkillEvidence olmalı")
        if self.success and evidence is not SkillEvidence.TRIGGER_RESPONSE:
            raise ValueError("Başarılı skill çağrısı Trigger yanıtı kanıtı ister")
        if not self.success and evidence is not SkillEvidence.NONE:
            raise ValueError("Başarısız skill çağrısı başarı kanıtı taşıyamaz")

    @property
    def independently_physically_verified(self) -> bool:
        """No current CLI Trigger bridge observes physical state itself."""

        return False


def _call_trigger(
    service_name: str,
    *,
    timeout_seconds: float,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    label: str,
) -> SkillCall:
    """Call one already-validated Trigger service without shell expansion."""
    if shutil.which("ros2") is None:
        return SkillCall(
            False,
            "ros2 komutu bulunamadı; ROS Jazzy ortamı yüklü değil.",
            SkillEvidence.NONE,
        )

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
            SkillEvidence.NONE,
        )
    except OSError as exc:
        return SkillCall(
            False,
            f"{label} çağrılamadı: {exc}",
            SkillEvidence.NONE,
        )
    except Exception as exc:
        # A custom runner is injectable for tests, and subprocess text decoding
        # can also fail.  Neither should escape as an apparent game success.
        return SkillCall(
            False,
            f"{label} yürütücüsü beklenmeyen hata verdi: {type(exc).__name__}: {exc}",
            SkillEvidence.NONE,
        )

    if not isinstance(completed, subprocess.CompletedProcess):
        return SkillCall(
            False,
            f"{label} yürütücüsü CompletedProcess döndürmedi.",
            SkillEvidence.NONE,
        )
    if (
        isinstance(completed.returncode, bool)
        or not isinstance(completed.returncode, int)
        or not isinstance(completed.stdout, str)
        or not isinstance(completed.stderr, str)
    ):
        return SkillCall(
            False,
            f"{label} yürütücüsü geçersiz subprocess sonucu döndürdü.",
            SkillEvidence.NONE,
        )

    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    if completed.returncode != 0:
        detail = output.splitlines()[-1] if output else f"çıkış kodu {completed.returncode}"
        return SkillCall(
            False,
            f"{label} servis çağrısı başarısız: {detail}",
            SkillEvidence.NONE,
        )

    responses = tuple(_TRIGGER_RESPONSE.finditer(output))
    if len(responses) != 1:
        return SkillCall(
            False,
            f"{label} servisinden tek ve doğrulanabilir bir Trigger_Response alınamadı.",
            SkillEvidence.NONE,
        )
    response = responses[0]
    success = response.group(1).casefold() == "true"
    message = response.group(3)
    if not message.strip():
        message = f"{label} boş mesajla sonuç döndürdü."
    if not success:
        return SkillCall(False, message, SkillEvidence.NONE)
    return SkillCall(True, message, SkillEvidence.TRIGGER_RESPONSE)


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
            return SkillCall(
                False,
                f"İzin verilmeyen teslimat rengi: {color}",
                SkillEvidence.NONE,
            )
        return _call_trigger(
            self.services[normalized],
            timeout_seconds=self.timeout_seconds,
            runner=self._runner,
            label=f"{normalized} fiziksel taşıma case'i",
        )

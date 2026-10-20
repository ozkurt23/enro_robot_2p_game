"""Two-player authority and mission state, independent of GUI/ROS devices."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import time

from .executor import MockExecution
from .types import ActionKind, ActionReceipt, ActionResult, Color, ExecutionStatus


class Phase(str, Enum):
    LOBBY = "Hazırlık"
    PLAY = "Sahada"
    THINK = "Robot düşünüyor"
    REVIEW = "İki oyuncunun onayı bekleniyor"
    AUTO = "Otomatik taşıma"
    PAUSED = "Duraklatıldı"
    FAULT = "Görevli kontrolü / yeni tur gerekiyor"
    WON = "Şenlik hazır!"


@dataclass(frozen=True)
class Mission:
    color: Color
    symbol: str
    name: str
    station: tuple[float, float]


MISSIONS = (
    Mission(Color.BLUE, "⚡", "Güç modülü", (1.85, 0.0)),
    Mission(Color.GREEN, "◆", "Kontrol modülü", (0.0, 1.85)),
    Mission(Color.RED, "●", "Açılış modülü", (-1.85, 0.0)),
)


def axis(value: float, deadzone: float = 0.18) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0.0
    value = max(-1.0, min(1.0, value))
    return 0.0 if abs(value) <= deadzone else math.copysign(
        (abs(value) - deadzone) / (1 - deadzone), value
    )


class ProposalExecutor:
    """NLU/policy can propose one action; it cannot touch a robot or score."""
    def __init__(self):
        self.actions = []

    def run(self, action, *, expected_color):
        self.actions.append(action)
        return MockExecution(
            ActionReceipt("coop-preview", action),
            ActionResult("coop-preview", action, ExecutionStatus.FAILED,
                         "İki oyuncunun fiziksel onayı bekleniyor"),
            ("Öneri kaydedildi; henüz yürütülmedi.",),
        )

    def cancel_all(self):
        self.actions.clear()
        return ("Öneri temizlendi.",)


class CoopSession:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.phase = Phase.LOBBY
        self.ready = set()
        self.connected = set()
        self.index = 0
        self.selection = 0
        self.order = 0
        self.selected = None
        self.approvals = set()
        self.epoch = 0
        self.corrections = 0
        self.hints = 0
        self.active_seconds = 0.0
        self.started = clock()
        self.robot_pose = None
        self.pose_stamp = -math.inf
        self.neutral_required = True
        self.message = "İki oyuncu A ile hazır olsun. İlk tur öğreticili ve süresizdir."

    @property
    def driver(self):
        return self.index % 2

    @property
    def coordinator(self):
        return 1 - self.driver

    @property
    def mission(self):
        return MISSIONS[min(self.index, len(MISSIONS) - 1)]

    def set_phase(self, phase):
        now = self.clock()
        if self.phase in (Phase.PLAY, Phase.REVIEW):
            self.active_seconds += max(0, now - self.started)
        self.started = now
        self.phase = phase

    def connect(self, player):
        if player not in (0, 1):
            raise ValueError("Oyuncu 0 veya 1 olmalı")
        self.connected.add(player)

    def disconnect(self, player):
        self.connected.discard(player)
        self.ready.discard(player)
        if self.phase not in (Phase.LOBBY, Phase.WON, Phase.FAULT):
            self.pause()
            self.message = "Oyun kolu ayrıldı. Tekrar bağlayın; iki oyuncu A ile devam etsin."

    def pose(self, x, y, yaw):
        if all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y, yaw)):
            self.robot_pose = (x, y, yaw)
            self.pose_stamp = self.clock()

    def near(self, mission=None):
        mission = mission or MISSIONS[self.selection]
        return (self.robot_pose is not None and self.clock() - self.pose_stamp < 0.7
                and math.dist(self.robot_pose[:2], mission.station) <= 0.85)

    def velocity(self, player, x, y, yaw):
        if (self.phase != Phase.PLAY or player != self.driver
                or self.connected != {0, 1} or self.robot_pose is None
                or self.clock() - self.pose_stamp >= .7):
            return (0.0, 0.0, 0.0)
        values = (axis(x), axis(y), axis(yaw))
        if self.neutral_required:
            if values == (0.0, 0.0, 0.0):
                self.neutral_required = False
            return (0.0, 0.0, 0.0)
        return (values[0] * 0.22, values[1] * 0.22, values[2] * 0.35)

    def choose(self, player, delta):
        if self.phase != Phase.PLAY:
            return
        if player == self.driver:
            self.selection = (self.selection + delta) % 3
            self.selected = None
        elif player == self.coordinator:
            self.order = (self.order + delta) % 3

    def confirm(self, player):
        if player not in self.connected:
            return False
        if self.phase in (Phase.LOBBY, Phase.PAUSED):
            self.ready.add(player)
            if self.ready == {0, 1} and self.connected == {0, 1}:
                self.ready.clear()
                self.set_phase(Phase.PLAY)
                self.neutral_required = True
                self.message = "Saha: istasyona yaklaş, parçayı A ile seç. Koordinatör: siparişi seç, X ile anlat."
            return False
        if self.phase == Phase.PLAY and player == self.driver:
            if not self.near():
                self.message = "Seçilen istasyonun yaklaşma halkasına girin."
                return False
            self.selected = MISSIONS[self.selection].color
            self.message = f"Saha seçimi: {self.selected.turkish}. Koordinatör görevi X ile iletsin."
        elif self.phase == Phase.REVIEW:
            self.approvals.add(player)
            if self.approvals == {0, 1}:
                if not self.near(self.mission):
                    self.back(player)
                    self.message = "Robot istasyondan uzaklaştı veya konumu güncel değil. Yeniden seçin."
                    return False
                self.set_phase(Phase.AUTO)
                self.message = "Robot kontrolü otomatik beceride. Menü: iptal ve görevli reset'i."
                return True
        return False

    def begin_plan(self, player, *, conversational=False):
        if self.phase != Phase.PLAY or player != self.coordinator:
            return None
        if not conversational and (self.selected != self.mission.color or MISSIONS[self.order].color != self.selected):
            self.corrections += 1
            self.message = "Sipariş ve saha seçimi uyuşmuyor. Simgeleri birlikte kontrol edin."
            return None
        if not conversational and not self.near(self.mission):
            self.message = "Robot seçilen istasyona yakın ve konumu güncel olmalı."
            return None
        self.epoch += 1
        self.approvals.clear()
        self.set_phase(Phase.THINK)
        self.message = "Görev yorumlanıyor; robot bekliyor."
        return self.epoch

    def accept_plan(self, epoch, actions, reply):
        if epoch != self.epoch or self.phase != Phase.THINK:
            return False
        self.message = reply
        valid = (len(actions) == 1 and actions[0].kind == ActionKind.DELIVER_OBJECT
                 and actions[0].color == self.mission.color
                 and actions[0].destination == "main_table"
                 and self.selected == self.mission.color
                 and MISSIONS[self.order].color == self.selected
                 and self.near(self.mission))
        self.set_phase(Phase.REVIEW if valid else Phase.PLAY)
        if valid:
            self.message += " Hareket henüz başlamadı: iki oyuncu da A ile onaylasın."
        if not valid:
            if actions:
                self.message += " Ortak görev için doğru saha/sipariş seçimi ve istasyona yakınlık gerekiyor."
                self.corrections += 1
            self.neutral_required = True
        return valid

    def finish(self, epoch, success, detail):
        if epoch != self.epoch or self.phase != Phase.AUTO:
            return False
        self.message = detail
        if not success:
            self.set_phase(Phase.FAULT)
            return False
        self.index += 1
        self.epoch += 1
        self.selected = None
        self.approvals.clear()
        self.neutral_required = True
        self.selection = self.order = min(self.index, 2)
        self.set_phase(Phase.WON if self.index == 3 else Phase.PLAY)
        if self.phase == Phase.PLAY:
            self.message = "Teslimat doğrulandı! Roller değişti; iki oyuncu da analogları bırakıp yeni görevine geçsin."
        return True

    def back(self, player):
        if player not in self.connected:
            return
        if self.phase in (Phase.PLAY, Phase.REVIEW, Phase.THINK):
            self.epoch += 1
            self.selected = None
            self.approvals.clear()
            self.neutral_required = True
            self.set_phase(Phase.PLAY)
            self.message = "Seçim geri alındı."

    def pause(self):
        if self.phase in (Phase.WON, Phase.FAULT):
            return
        automatic = self.phase == Phase.AUTO
        self.epoch += 1
        self.approvals.clear()
        self.selected = None
        self.ready.clear()
        self.neutral_required = True
        self.set_phase(Phase.FAULT if automatic else Phase.PAUSED)
        self.message = ("Taşıma iptal ediliyor. Fiziksel durum için yeni tur/reset gerekiyor."
                        if automatic else "Devam etmek için iki oyuncu da A'ya bassın.")

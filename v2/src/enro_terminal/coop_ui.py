"""Native two-player festival panel; Tk stays responsive during model/ROS work."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk

from .coop import CoopSession, MISSIONS, Phase, ProposalExecutor
from .coop_input import Pad
from .coop_speech import Speech
from .dialogue import CanonicalActor, QwenPersonaActor
from .game import TerminalGame
from .llm_client import LlamaCppClient, LlamaCppConfig
from .nlu import QwenNlu, RuleNlu
from .types import MockAction, ActionKind, PersonaId

BG, PANEL, TEXT, MUTED = "#101923", "#1b2a38", "#eef5fa", "#afc3d1"
GOLD, CYAN = "#ffd166", "#64d8e8"
COLORS = ("#62b0ff", "#58d5a0", "#ff7c89")


class Panel:
    def __init__(self, args):
        self.args = args
        self.session = CoopSession()
        self.root = tk.Tk()
        self.root.title("ENRO • Şenliği Kurtar! • İki oyuncu")
        self.root.geometry("1180x830")
        self.root.minsize(1000, 740)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.events = queue.Queue()
        self.exit_code = 0
        self.closed = False
        self.bridge = None
        self.bridge_ready = args.simulation == "mock"
        self.planning = False
        self.speech_busy = False
        self.keys = set()
        self.pads = [Pad(args.pad1), Pad(args.pad2)]
        if os.path.realpath(args.pad1) == os.path.realpath(args.pad2):
            raise ValueError("İki oyuncu aynı gamepad'i kullanamaz")
        self.last_scan = 0.
        self.menu_axes = [False, False]
        self.last_tick = time.monotonic()
        self.demo_pose = [0., 0., 0.]
        self.view_zoom = 1.
        self.hint_level = 0
        self.smoke_cancelled = False
        self.smoke_halted = False
        self.suppress_heartbeat = False
        self.transcript_owner = None
        self.root_dir = Path(__file__).resolve().parents[2]
        self.speech = Speech(
            args.whisper_bin or self.root_dir / ".deps/whisper.cpp/build/bin/whisper-cli",
            args.whisper_model or self.root_dir / ".models/ggml-base.bin",
            (args.mic1, args.mic2))
        executor = ProposalExecutor()
        if args.backend == "qwen":
            client = LlamaCppClient(LlamaCppConfig.from_environment(
                base_url=args.llm_url, model=args.llm_model, timeout_seconds=12.))
            nlu, actor = QwenNlu(client, seed=args.seed or 180), QwenPersonaActor(client, seed=args.seed or 180)
        else:
            nlu, actor = RuleNlu(), CanonicalActor()
        persona = {"leydi": PersonaId.LEYDI_SERVO, "leydi_servo": PersonaId.LEYDI_SERVO,
                   "sakar": PersonaId.SAKAR}.get(args.persona, PersonaId.NESELI)
        self.game = TerminalGame(persona=persona, nlu=nlu, actor=actor, executor=executor,
                                 timeout_seconds=86400., clock=lambda: 0., store=None)
        self.build()
        if args.keyboard or args.coop_smoke:
            self.session.connect(0)
            self.session.connect(1)
        if args.simulation == "native-arena":
            self.bridge = subprocess.Popen(
                ["/usr/bin/python3", "-m", "enro_terminal.coop_ros"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
            threading.Thread(target=self.read_bridge, daemon=True).start()
        self.root.bind("<KeyPress>", self.key_down)
        self.root.bind("<KeyRelease>", self.key_up)
        self.root.bind("<FocusOut>", lambda _: self.root.after(50, self.check_focus))
        self.root.after(50, self.tick)
        if args.coop_smoke:
            self.smoke_started = time.monotonic()
            self.root.after(300, self.smoke)

    def label(self, parent, text="", size=12, color=TEXT, **kwargs):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=color,
                        font=("DejaVu Sans", size), **kwargs)

    def button(self, parent, text, command, accent=False):
        return tk.Button(parent, text=text, command=command, bg=GOLD if accent else "#304759",
                         fg=BG if accent else TEXT, activebackground=CYAN,
                         relief="flat", bd=0, padx=12, pady=9,
                         font=("DejaVu Sans", 10, "bold"), cursor="hand2")

    def build(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 8))
        self.label(header, "ENRO  /  ŞENLİĞİ KURTAR!", 23, GOLD).pack(side="left")
        self.badge = self.label(header, "", 10, CYAN)
        self.badge.pack(side="right")
        self.label(self.root, "Biriniz sahayı, diğeriniz siparişi yönetiyor. Üç modülü birlikte ulaştırın.",
                   11, MUTED).pack(anchor="w", padx=26)
        self.status = self.label(self.root, "", 14, CYAN, anchor="w")
        self.status.pack(fill="x", padx=26, pady=12)
        content = tk.Frame(self.root, bg=BG)
        content.pack(fill="both", expand=True, padx=24)
        self.cards = []
        self.card_labels = []
        for player in range(2):
            card = tk.Frame(content, bg=PANEL, padx=18, pady=16)
            card.grid(row=0, column=player, sticky="nsew", padx=(0, 6) if player == 0 else (6, 0))
            content.columnconfigure(player, weight=1)
            title = self.label(card, "", 17, GOLD)
            title.pack(anchor="w")
            device = self.label(card, "", 9, MUTED, wraplength=460, anchor="w")
            device.pack(anchor="w", pady=(4, 12))
            body = self.label(card, "", 12, TEXT, justify="left", anchor="nw", wraplength=460, height=5)
            body.pack(fill="x")
            controls = tk.Frame(card, bg=PANEL)
            controls.pack(fill="x", pady=(8, 0))
            for text, event in (("◀ LB", "previous"), ("A Onay", "confirm"),
                                ("B Geri", "back"), ("RB ▶", "next")):
                self.button(controls, text, lambda p=player, e=event: self.action(p, e),
                            event == "confirm").pack(side="left", padx=3)
            controls2 = tk.Frame(card, bg=PANEL)
            controls2.pack(fill="x", pady=(8, 0))
            self.button(controls2, "X Görevi anlat", lambda p=player: self.action(p, "request")).pack(side="left", padx=3)
            self.button(controls2, "Y İpucu", lambda p=player: self.action(p, "hint")).pack(side="left", padx=3)
            talk = self.button(controls2, "LT Konuş", lambda: None)
            talk.pack(side="left", padx=3)
            talk.bind("<ButtonPress-1>", lambda _, p=player: self.action(p, "talk", True))
            talk.bind("<ButtonRelease-1>", lambda _, p=player: self.action(p, "talk", False))
            self.cards.append(card)
            self.card_labels.append((title, device, body))
        content.rowconfigure(1, weight=1)
        self.map = tk.Canvas(content, bg="#13222c", highlightthickness=0, height=180)
        self.map.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=12)
        self.message = self.label(self.root, "", 12, TEXT, wraplength=1100, justify="left", anchor="w", height=3)
        self.message.pack(fill="x", padx=26)
        self.chat = tk.Frame(self.root, bg=BG)
        self.chat.pack(fill="x", padx=24, pady=8)
        self.draft = tk.StringVar()
        self.entry = tk.Entry(self.chat, textvariable=self.draft, font=("DejaVu Sans", 12),
                              bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, ipady=10, padx=(0, 8))
        self.entry.bind("<Return>", lambda _: self.request(self.session.coordinator))
        self.entry.bind("<FocusIn>", lambda _: self.keys.clear())
        self.button(self.chat, "Koordinatör: gönder", lambda: self.request(self.session.coordinator), True).pack(side="left")
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=24, pady=(0, 12))
        self.button(footer, "Menü • Duraklat / iptal", self.pause).pack(side="left")
        self.button(footer, "Görevli • Yeni ekip / dünya reset", self.restart).pack(side="left", padx=8)
        self.footer = self.label(footer, "", 9, MUTED)
        self.footer.pack(side="right")
        # Reserve bottom controls before giving remaining space to the radar.
        footer.pack_configure(side="bottom", before=content)
        self.chat.pack_configure(side="bottom", before=content)
        self.message.pack_configure(side="bottom", before=content)

    def check_focus(self):
        if not self.closed and self.root.focus_displayof() is None:
            self.keys.clear()
            if self.session.phase in (Phase.PLAY, Phase.REVIEW, Phase.THINK, Phase.AUTO):
                self.pause()

    def key_down(self, event):
        if event.widget is self.entry or not self.args.keyboard:
            return
        key = event.keysym.lower()
        if key in self.keys:
            return
        self.keys.add(key)
        mapping = {"f": (0, "confirm"), "g": (0, "back"), "r": (0, "request"),
                   "c": (0, "hint"), "z": (0, "previous"), "x": (0, "next"),
                   "m": (1, "confirm"), "b": (1, "back"), "n": (1, "request"),
                   "h": (1, "hint"), "u": (1, "previous"), "i": (1, "next")}
        if key == "space":
            self.pause()
        elif key in mapping:
            self.action(*mapping[key])

    def key_up(self, event):
        self.keys.discard(event.keysym.lower())

    def action(self, player, action, pressed=True):
        if self.closed or player not in self.session.connected:
            return
        if action == "talk":
            self.voice(player, pressed)
            return
        if not pressed:
            return
        s = self.session
        if action == "pause":
            self.pause()
        elif action == "confirm":
            if not self.bridge_ready:
                s.message = "Robot köprüsü hazırlanıyor."
            elif s.confirm(player):
                self.deliver()
        elif action == "back":
            s.back(player)
        elif action in ("next", "previous"):
            s.choose(player, 1 if action == "next" else -1)
        elif action == "request":
            self.request(player)
        elif action == "hint":
            s.hints += 1
            self.hint_level += 1
            s.message = ("Saha ile siparişin simgesini eşleştirin." if self.hint_level % 3 == 1
                         else f"Aranan modül: {s.mission.name}, işareti {s.mission.symbol}." if self.hint_level % 3 == 2
                         else f"{s.mission.color.turkish.capitalize()} parçayı seçin; ana masaya teslim edilecek.")

    def request(self, player):
        if self.planning or player != self.session.coordinator:
            return
        if self.speech.recording:
            self.session.message = "Önce konuşma düğmesini bırakıp dökümü kontrol edin."
            return
        text = self.draft.get().strip()
        epoch = self.session.begin_plan(player, conversational=bool(text))
        if epoch is None:
            return
        self.planning = True
        if not text:
            text = ("Evet, onaylıyorum." if self.game.persona_state.pending_confirmation
                    else f"Lütfen {self.session.mission.color.turkish} cismi ana masaya getir.")
        # Each worker has a separate state; paused/old model results cannot mutate a new turn.
        candidate = copy.deepcopy(self.game)
        candidate.executor = ProposalExecutor()
        self.draft.set("")
        def work():
            try:
                if text.startswith("/"):
                    raise ValueError("Oyuncu metninde operatör komutu kullanılmaz.")
                turn = candidate.process(text[:500])
                # Multi-action special shortcuts are never two-player delivery plans.
                actions = turn.decision.actions if turn.decision else ()
                self.events.put(("plan", epoch, candidate, actions, turn.reply))
            except Exception as exc:
                self.events.put(("plan_error", epoch, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def send(self, data):
        if not self.bridge:
            return
        if self.suppress_heartbeat and data.get("op") == "drive":
            return
        try:
            self.bridge.stdin.write(json.dumps(data) + "\n")
            self.bridge.stdin.flush()
        except (BrokenPipeError, OSError):
            self.session.set_phase(Phase.FAULT)
            self.session.message = "Robot köprüsü kapandı; yeni ekip/reset ile yeniden başlatın."

    def read_bridge(self):
        try:
            for line in self.bridge.stdout:
                self.events.put(("bridge", json.loads(line)))
        except Exception as exc:
            self.events.put(("bridge", {"event": "error", "message": str(exc)}))
        self.events.put(("bridge", {"event": "error", "message": "ROS köprüsü bağlantısı kapandı."}))

    def deliver(self):
        s = self.session
        if self.bridge:
            self.send({"op": "drive", "mode": "idle", "velocity": [0, 0, 0]})
            self.send({"op": "deliver", "id": s.epoch, "color": s.mission.color.value})
        else:
            epoch = s.epoch
            self.root.after(1200, lambda: self.events.put(("bridge", {
                "event": "result", "id": epoch, "success": True,
                "message": "PROVA: sahte teslimat tamamlandı; Gazebo hareketi yok."})))

    def voice(self, player, pressed):
        if player != self.session.coordinator or self.session.phase != Phase.PLAY:
            return
        if pressed:
            if self.speech_busy:
                return
            try:
                self.speech.start(player)
                self.session.message = "Dinliyorum (en çok 12 sn). LT'yi bırakınca metin gelecek; X ile gönderebilirsiniz."
                recorder = self.speech.recording
                self.root.after(12500, lambda p=player, r=recorder:
                                self.voice(p, False) if self.speech.recording is r else None)
            except Exception as exc:
                self.session.message = str(exc)
        elif self.speech.player == player:
            self.speech_busy = True
            epoch = self.session.epoch
            def transcribe():
                try:
                    text = self.speech.finish(player)
                    self.events.put(("voice", epoch, player, text))
                except Exception as exc:
                    self.events.put(("voice_error", str(exc)))
            threading.Thread(target=transcribe, daemon=True).start()

    def pause(self):
        if self.closed:
            return
        automatic = self.session.phase == Phase.AUTO
        self.session.pause()
        self.keys.clear()
        self.speech.close()
        if automatic:
            self.send({"op": "cancel"})
        self.send({"op": "drive", "mode": "idle", "velocity": [0, 0, 0]})

    def process_events(self):
        for _ in range(100):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind, *data = event
            s = self.session
            if kind == "plan":
                self.planning = False
                epoch, candidate, actions, reply = data
                if epoch == s.epoch and s.phase == Phase.THINK:
                    self.game = candidate
                    s.accept_plan(epoch, actions, reply)
            elif kind == "plan_error":
                self.planning = False
                epoch, detail = data
                s.accept_plan(epoch, (), "Yanıt alınamadı; tekrar deneyin. " + detail)
            elif kind == "voice":
                self.speech_busy = False
                epoch, player, text = data
                if epoch == s.epoch and player == s.coordinator and s.phase == Phase.PLAY:
                    self.draft.set(text)
                    s.message = "Duyduğum metni kontrol edin; X veya Gönder ile iletin."
            elif kind == "voice_error":
                self.speech_busy = False
                s.message = "Ses alınamadı; hazır görev kullanabilirsiniz. " + data[0]
            elif kind == "bridge":
                msg = data[0]
                typ = msg.get("event")
                if typ == "ready":
                    self.bridge_ready = True
                elif typ == "pose":
                    s.pose(msg["x"], msg["y"], msg["yaw"])
                elif typ == "stage" and s.phase == Phase.AUTO:
                    s.message = msg["message"]
                elif typ == "result":
                    color = s.mission.color
                    if s.finish(msg["id"], msg["success"] is True, msg["message"]):
                        self.game._apply_success(MockAction(ActionKind.DELIVER_OBJECT, color, "main_table"))
                        self.hint_level = 0
                elif typ == "error":
                    self.bridge_ready = False
                    s.epoch += 1
                    s.set_phase(Phase.FAULT)
                    s.message = msg["message"]
                elif typ == "cancel":
                    s.epoch += 1
                    s.set_phase(Phase.FAULT)
                    s.message = msg["message"]
                elif typ == "halted":
                    self.smoke_halted = msg.get("verified") is True
                    s.message = msg["message"] + " Yeni tur için görevli reset'i kullanın."

    def tick(self):
        if self.closed:
            return
        now = time.monotonic()
        dt = min(.1, now - self.last_tick)
        self.last_tick = now
        s = self.session
        self.process_events()
        if not (self.args.keyboard or self.args.coop_smoke):
            for player, pad in enumerate(self.pads):
                if pad.fd is None and now - self.last_scan > 1.:
                    if pad.open():
                        s.connect(player)
                        s.neutral_required = True
                was_connected = pad.fd is not None
                for action, pressed in pad.poll():
                    self.action(player, action, pressed)
                menu_axis = pad.axes.get(0, 0.)
                if player == s.coordinator and abs(menu_axis) > .65 and not self.menu_axes[player]:
                    s.choose(player, 1 if menu_axis > 0 else -1)
                self.menu_axes[player] = abs(menu_axis) > .35
                if was_connected and pad.fd is None:
                    automatic = s.phase == Phase.AUTO
                    s.disconnect(player)
                    self.speech.close()
                    if automatic:
                        self.send({"op": "cancel"})
            if now - self.last_scan > 1.:
                self.last_scan = now
        values = self.pads[s.driver].velocity()
        if self.args.keyboard:
            k = set() if self.root.focus_get() is self.entry else self.keys
            up, down, left, right, ccw, cw = (("w", "s", "a", "d", "q", "e") if s.driver == 0
                                               else ("up", "down", "left", "right", "j", "k"))
            values = (float(up in k) - float(down in k), float(left in k) - float(right in k),
                      float(ccw in k) - float(cw in k))
        if self.args.coop_smoke and s.phase == Phase.PLAY and not s.neutral_required and s.robot_pose:
            x, y, yaw = s.robot_pose
            tx, ty = s.mission.station
            dx, dy = tx - x, ty - y
            values = (max(-1., min(1., 3*(dx*math.cos(yaw)+dy*math.sin(yaw)))),
                      max(-1., min(1., 3*(-dx*math.sin(yaw)+dy*math.cos(yaw)))), 0.)
        velocity = s.velocity(s.driver, *values)
        self.send({"op": "drive", "mode": "manual" if s.phase == Phase.PLAY else "idle",
                   "velocity": velocity})
        if not self.bridge:
            x, y, yaw = self.demo_pose
            vx, vy, wz = velocity
            self.demo_pose = [x+(vx*math.cos(yaw)-vy*math.sin(yaw))*dt,
                              y+(vx*math.sin(yaw)+vy*math.cos(yaw))*dt, yaw+wz*dt]
            s.pose(*self.demo_pose)
        self.render()
        self.root.after(50, self.tick)

    def render(self):
        s = self.session
        self.badge["text"] = (("GAZEBO • CANLI" if self.bridge else "PROVA • FİZİKSEL HAREKET YOK")
                              + ("  /  QWEN" if self.args.backend == "qwen" else "  /  SABİT REPLİK"))
        self.status["text"] = f"{s.phase.value}   ·   {s.index}/3 teslimat   ·   {self.game.persona.display_name}"
        self.message["text"] = s.message
        for p, (title, device, body) in enumerate(self.card_labels):
            driver = p == s.driver
            title["text"] = (f"OYUNCU {p+1}  /  {'SAHA' if driver else 'KOORDİNATÖR'}"
                             + ("  ✓" if p in s.ready else ""))
            device["text"] = ("KLAVYE / OTOMATİK PROVA" if self.args.keyboard or self.args.coop_smoke else
                              self.pads[p].name if p in s.connected else
                              "Gamepad bekleniyor: " + self.pads[p].path + " — " + self.pads[p].error)
            if s.phase == Phase.LOBBY:
                body["text"] = ("1. İkiniz de A ile hazır olun.\n2. Saha: sol analog sürüş, sağ analog dönüş.\n"
                                "3. LB/RB seç, A ile işaretle.\n4. Koordinatör: X ile görevi anlat.\n5. İkiniz de A ile taşıma onayı verin.")
            elif s.phase == Phase.WON:
                body["text"] = ("Üç modül yerinde. Şenlik hazır!\nBirlikte tamamladınız.\n"
                                f"İpucu: {s.hints}   Düzeltme: {s.corrections}\nYeni ekip için görevli reset'i kullanın.")
            elif s.phase == Phase.AUTO:
                next_task = MISSIONS[s.index + 1].name if s.index < 2 else "Ortak kutlama"
                body["text"] = (f"{s.mission.name} → ANA MASA\n"
                                "Kontrol otomatik robot becerisinde.\nAnalog sürüş bu aşamada kapalı.\n"
                                f"Sıradaki: {next_task}\nTeslimat bitince rolleriniz değişecek.")
            elif driver:
                selected = MISSIONS[s.selection]
                body["text"] = (f"Saha seçici: {selected.symbol} {selected.color.turkish.upper()}\n"
                                "Konum: sağ MAVİ • üst YEŞİL • sol KIRMIZI\n"
                                f"Yaklaşma: {'Hazır — A ile seç' if s.near() else 'Halkaya sür'}\n"
                                f"Seçilen: {s.selected.turkish if s.selected else 'henüz yok'}\n"
                                f"Onayınız: {'✓' if p in s.approvals else 'A bekleniyor'}")
            else:
                body["text"] = (f"Gereken: {s.mission.symbol} {s.mission.name}\n"
                                "Hedef: ANA MASA\n"
                                f"Sipariş seçici: {MISSIONS[s.order].name}\n"
                                "LB/RB seç • X anlat • LT bas-konuş\n"
                                f"Onayınız: {'✓' if p in s.approvals else 'A bekleniyor'}")
            if self.pads[p].dual_action and not (self.args.keyboard or self.args.coop_smoke):
                body["text"] = (body["text"].replace("LB/RB", "5/6").replace("LT", "7")
                                .replace("X ile", "1 ile").replace("X anlat", "1 anlat")
                                .replace("A ile", "2 ile").replace("A bekleniyor", "2 bekleniyor"))
        self.footer["text"] = ("P1 WASD/QE · F/R | P2 Oklar/JK · M/N" if self.args.keyboard else
                               "A onay • B geri • X anlat • Y ipucu • Menü duraklat")
        if not self.args.keyboard and any(pad.dual_action for pad in self.pads):
            self.footer["text"] = "Logitech: 2 onay • 3 geri • 1 anlat • 4 ipucu • 5/6 seç • 7 konuş • 9/10 duraklat"
        self.draw_map()

    def draw_map(self):
        canvas = self.map
        canvas.delete("all")
        w, h = max(canvas.winfo_width(), 600), max(canvas.winfo_height(), 220)
        scale = min((w-220)/8, (h-50)/8) * self.view_zoom
        cx, cy = w/2, h/2
        def xy(x, y):
            return cx+x*scale, cy-y*scale
        canvas.create_text(16, 14, text="SAHA RADARI • robot konumu / yaklaşma halkaları", anchor="w", fill=MUTED,
                           font=("DejaVu Sans", 10))
        for i, m in enumerate(MISSIONS):
            x, y = xy(*m.station)
            radius = .85*scale
            canvas.create_oval(x-radius, y-radius, x+radius, y+radius, outline=COLORS[i], dash=(3, 4))
            tx, ty = xy(*((3, 0), (0, 3), (-3, 0))[i])
            canvas.create_rectangle(tx-15, ty-12, tx+15, ty+12, fill=COLORS[i], outline="")
            canvas.create_text(tx, ty, text=m.symbol, fill=BG)
            canvas.create_text(tx, ty+24, text=m.color.turkish.upper() + (" ✓" if i < self.session.index else ""),
                               fill=COLORS[i], font=("DejaVu Sans", 9, "bold"))
        x, y = xy(0, -3)
        canvas.create_rectangle(x-25, y-10, x+25, y+10, fill=GOLD, outline="")
        canvas.create_text(x+40, y, text="ANA MASA", anchor="w", fill=GOLD)
        if self.session.robot_pose:
            x0, y0, yaw = self.session.robot_pose
            x, y = xy(x0, y0)
            canvas.create_oval(x-8, y-8, x+8, y+8, fill=TEXT, outline="")
            canvas.create_line(x, y, x+16*math.cos(yaw), y-16*math.sin(yaw), fill=CYAN, width=3, arrow="last")

    def smoke(self):
        if self.closed:
            return
        s = self.session
        if self.args.coop_scenario in ("cancel", "watchdog") and self.smoke_cancelled:
            if self.smoke_halted and s.index == 0 and s.phase == Phase.FAULT:
                print("COOP_CANCEL_OK: scenario=" + self.args.coop_scenario +
                      "; no manifest advance; canceled targets and physical halt verified", flush=True)
                self.close()
                return
            if time.monotonic() - self.smoke_started < 120:
                self.root.after(300, self.smoke)
                return
        if time.monotonic() - self.smoke_started > 600 or s.phase == Phase.FAULT:
            print("COOP_SMOKE_FAILED: " + s.message, flush=True)
            self.exit_code = 1
            self.close()
            return
        if s.phase == Phase.WON:
            print("COOP_SMOKE_OK: 3 deliveries, dual approvals, role swaps; mode=" + self.args.simulation, flush=True)
            self.close()
            return
        if self.args.coop_scenario == "reset" and s.index == 1:
            if os.environ.get("ENRO_COOP_RESET_PROBE") != "1":
                print("COOP_RESET_REQUESTED: one delivery; restart entire owned world", flush=True)
                self.restart()
                return
            print("COOP_RESET_OK: fresh world delivered blue again", flush=True)
            self.close()
            return
        if self.bridge_ready:
            if s.phase == Phase.LOBBY:
                self.action(0, "confirm")
                self.action(1, "confirm")
            elif s.phase == Phase.PLAY and s.near(s.mission):
                self.action(s.driver, "confirm")
                self.action(s.coordinator, "request")
            elif s.phase == Phase.REVIEW:
                self.action(0, "confirm")
                self.action(1, "confirm")
            elif (s.phase == Phase.AUTO and self.args.coop_scenario in ("cancel", "watchdog")
                  and s.message == "Kavrama ve kaldırma" and not self.smoke_cancelled):
                self.smoke_cancelled = True
                if self.args.coop_scenario == "watchdog":
                    self.suppress_heartbeat = True
                else:
                    self.root.after(800, self.pause)
        self.root.after(300, self.smoke)

    def restart(self):
        self.exit_code = 75  # Wrapper closes owned processes and starts a fresh world.
        self.close()

    def close(self):
        if self.closed:
            return
        self.pause()
        self.closed = True
        self.speech.close()
        for pad in self.pads:
            pad.close()
        if self.bridge:
            try:
                self.bridge.stdin.close()
                self.bridge.wait(timeout=15.)
            except (OSError, subprocess.TimeoutExpired):
                self.bridge.terminate()
                try:
                    self.bridge.wait(timeout=3.)
                except subprocess.TimeoutExpired:
                    self.bridge.kill()
                    self.bridge.wait()
        self.root.destroy()


def run(args):
    if args.simulation not in ("mock", "native-arena"):
        print("İki oyunculu panel yalnız arena veya prova profiliyle çalışır", file=sys.stderr)
        return 2
    if args.persona not in ("random", "neseli", "neşeli", "leydi", "leydi_servo", "sakar"):
        print("İki oyunculu ilk sürüm: --persona neseli, leydi veya sakar", file=sys.stderr)
        return 2
    if args.coop_smoke and args.coop_scenario != "full" and args.simulation != "native-arena":
        print("İptal/watchdog/reset kabul testi gerçek native-arena profili ister", file=sys.stderr)
        return 2
    panel = Panel(args)
    panel.root.mainloop()
    return panel.exit_code

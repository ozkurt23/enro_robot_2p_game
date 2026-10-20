"""Linux joydev input; mappings use kernel semantic codes, not device indices."""
import array
import fcntl
import os
import struct

BUTTONS = {0x130: "confirm", 0x131: "back", 0x133: "request",
           0x134: "hint", 0x136: "previous", 0x137: "next",
           0x13a: "pause", 0x13b: "pause", 0x138: "talk"}
EVENT = struct.Struct("IhBB")
# Dual Action (046d:c216): numbered face buttons 1=west, 2=south,
# 3=east, 4=north. Its right stick is ABS_Z, not an analog trigger.
DUAL_ACTION_BUTTONS = {
    0x120: "request", 0x121: "confirm", 0x122: "back", 0x123: "hint",
    0x124: "previous", 0x125: "next", 0x126: "talk",
    0x128: "pause", 0x129: "pause",
}


class Pad:
    def __init__(self, path):
        self.path = path
        self.fd = None
        self.name = path
        self.axes = {}
        self.buttons = {}
        self.error = "Bağlı değil"
        self.axis_map = array.array("B", [0] * 64)
        self.button_map = array.array("H", [0] * 512)
        self.select_profile()

    def select_profile(self):
        self.dual_action = ("logitech" in self.name.lower()
                            and "dual action" in self.name.lower()
                            and set(range(0x120, 0x12c)).issubset(self.button_map)
                            and {0, 1, 2, 5}.issubset(self.axis_map))
        self.actions = DUAL_ACTION_BUTTONS if self.dual_action else BUTTONS
        self.turn_axis = 2 if self.dual_action else 3
        self.talk_axis = None if self.dual_action else 2

    def open(self):
        try:
            self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
            fcntl.ioctl(self.fd, 0x80406a32, self.axis_map, True)
            fcntl.ioctl(self.fd, 0x84006a34, self.button_map, True)
            name = bytearray(128)
            fcntl.ioctl(self.fd, 0x80806a13, name, True)
            self.name = name.split(b"\0", 1)[0].decode(errors="replace")
            self.select_profile()
            self.error = ""
            return True
        except OSError as exc:
            self.close()
            self.error = str(exc)
            return False

    def decode(self, raw):
        _, value, kind, number = EVENT.unpack(raw)
        initial = bool(kind & 0x80)
        kind &= 0x7f
        if kind == 2 and number < len(self.axis_map):
            code = self.axis_map[number]
            previous = self.axes.get(code, 0.)
            self.axes[code] = max(-1., value / 32767.)
            # D-pad selects without steering. Trigger supports push-to-talk.
            if not initial and code == 16 and abs(previous) < .5 and abs(value) > 16000:
                return ("next" if value > 0 else "previous", True)
            if not initial and code == self.talk_axis:
                old, new = previous > .5, self.axes[code] > .5
                if old != new:
                    return ("talk", new)
        elif kind == 1 and number < len(self.button_map):
            code = self.button_map[number]
            old = self.buttons.get(code, False)
            self.buttons[code] = bool(value)
            if not initial and old != bool(value) and code in self.actions:
                return (self.actions[code], bool(value))
        return None

    def poll(self):
        events = []
        if self.fd is None:
            return events
        try:
            for _ in range(128):
                raw = os.read(self.fd, EVENT.size)
                if len(raw) != EVENT.size:
                    raise OSError("Oyun kolu bağlantısı kapandı")
                event = self.decode(raw)
                if event:
                    events.append(event)
        except BlockingIOError:
            pass
        except OSError as exc:
            self.close()
            self.error = str(exc)
        return events

    def velocity(self):
        return (-self.axes.get(1, 0.), -self.axes.get(0, 0.), -self.axes.get(self.turn_axis, 0.))

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
        self.fd = None
        self.axes.clear()
        self.buttons.clear()

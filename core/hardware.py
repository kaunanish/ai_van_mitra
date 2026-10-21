"""
Hardware <-> software bridge.

Production: an Arduino Nano / ESP32 on USB serial sends one line per event:
    BTN_DOWN   BTN_UP   PRESENCE_ON   PRESENCE_OFF
and accepts commands:
    LED:IDLE  LED:GREETING  LED:READY  LED:LISTENING  LED:THINKING  LED:SPEAKING
A background thread reads the serial port and pushes every event to the browser over
Server-Sent Events (SSE). The browser reports each state change back (POST /api/state)
and we forward it to the Arduino so the LED ring colour always matches the screen.

Demo: no Arduino. The browser's keyboard handler (Spacebar / P) posts the SAME event
names to /api/hw, which go through the SAME broadcast path. So the demo exercises the
production code; only the source of the event differs.
"""
import json
import logging
import queue
import threading
import time

import config

log = logging.getLogger("van_mitra.hw")

VALID_EVENTS = {"BTN_DOWN", "BTN_UP", "PRESENCE_ON", "PRESENCE_OFF"}
VALID_STATES = {"IDLE", "GREETING", "READY", "LISTENING", "THINKING", "SPEAKING"}


class EventBus:
    """Fan-out of events to every connected browser (normally exactly one kiosk page)."""

    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def publish(self, event, source):
        msg = json.dumps({"event": event, "source": source, "t": time.time()})
        with self._lock:
            for q in list(self._subs):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def clients(self):
        with self._lock:
            return len(self._subs)


bus = EventBus()


class SerialBridge:
    def __init__(self, port, baud):
        self.port, self.baud = port, baud
        self.ser = None
        self.connected = False
        self.last_state = "IDLE"
        self._wlock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, name="serial", daemon=True).start()

    def _run(self):
        import serial  # pyserial
        while True:
            try:
                self.ser = serial.Serial(self.port, self.baud, timeout=1)
                self.connected = True
                log.info("Serial connected on %s", self.port)
                time.sleep(2)  # Arduino resets when the port opens
                self.send_state(self.last_state)
                while True:
                    line = self.ser.readline().decode(errors="ignore").strip().upper()
                    if line in VALID_EVENTS:
                        bus.publish(line, "serial")
            except Exception as e:  # noqa: BLE001
                if self.connected:
                    log.warning("Serial lost (%s), retrying...", e)
                self.connected = False
                try:
                    if self.ser:
                        self.ser.close()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(3)

    def send_state(self, state):
        self.last_state = state
        if not self.connected:
            return
        try:
            with self._wlock:
                self.ser.write(f"LED:{state}\n".encode())
        except Exception as e:  # noqa: BLE001
            log.warning("Serial write failed: %s", e)


bridge = SerialBridge(config.SERIAL_PORT, config.SERIAL_BAUD) if config.SERIAL_PORT else None


def start():
    if bridge:
        bridge.start()
    else:
        log.info("No SERIAL_PORT set -> demo mode (keyboard: hold SPACE = button, P = person)")


def set_state(state):
    if bridge:
        bridge.send_state(state)


def status():
    if not bridge:
        return {"ok": True, "mode": "demo (keyboard)", "detail": "SPACE = button, P = person"}
    return {"ok": bridge.connected, "mode": "serial", "detail": f"{config.SERIAL_PORT} {'connected' if bridge.connected else 'not connected'}"}

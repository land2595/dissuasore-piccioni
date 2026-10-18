"""Scheduler: riproduce un verso casuale a intervalli casuali dentro le fasce orarie attive."""
import logging
import random
import threading
import time
from datetime import datetime

log = logging.getLogger("dissuasore.scheduler")


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_active_window(cfg: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if now.weekday() not in cfg["days"]:
        return False
    cur = now.hour * 60 + now.minute
    for w in cfg["windows"]:
        start, end = _minutes(w["start"]), _minutes(w["end"])
        if start <= end:
            if start <= cur < end:
                return True
        elif cur >= start or cur < end:  # fascia a cavallo della mezzanotte
            return True
    return False


class Scheduler:
    def __init__(self, store, player):
        self.store = store
        self.player = player
        self.next_play_at: float | None = None
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def reschedule(self):
        """Da chiamare quando cambia la configurazione."""
        self.next_play_at = None
        self._wake.set()

    def _random_delay(self, cfg) -> float:
        lo = max(5, int(cfg["min_interval_sec"]))
        hi = max(lo, int(cfg["max_interval_sec"]))
        return random.uniform(lo, hi)

    def _run(self):
        while True:
            self._wake.clear()
            try:
                self._tick()
            except Exception:  # noqa: BLE001
                log.exception("Errore nello scheduler")
            self._wake.wait(5)

    def _tick(self):
        cfg = self.store.get_config()
        if not cfg["enabled"] or not in_active_window(cfg):
            self.next_play_at = None
            return
        now = time.time()
        if self.next_play_at is None:
            self.next_play_at = now + self._random_delay(cfg)
            return
        if now < self.next_play_at or self.player.busy:
            return
        sound = self.player.pick_random()
        if sound:
            log.info("Riproduzione programmata: %s", sound)
            self.player.play(sound, "automatica")
        self.next_play_at = time.time() + self._random_delay(cfg)

    def status(self) -> dict:
        cfg = self.store.get_config()
        return {
            "enabled": cfg["enabled"],
            "in_window": in_active_window(cfg),
            "next_play_at": self.next_play_at,
        }

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
        self.session_end: float | None = None
        self._forced = False  # sessione avviata a mano: ignora orari e interruttore
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def reschedule(self):
        """Da chiamare quando cambia la configurazione."""
        self.next_play_at = None
        self.session_end = None
        self._forced = False
        self._wake.set()

    @property
    def in_session(self) -> bool:
        return self.session_end is not None or self._forced

    def start_session_now(self):
        self.session_end = None
        self.next_play_at = time.time()
        self._forced = True
        self._wake.set()

    def end_session(self):
        """Chiude la sessione in corso e programma la prossima dopo la pausa normale."""
        self.session_end = None
        self._forced = False
        self.next_play_at = time.time() + self._random_delay(self.store.get_config())

    @staticmethod
    def _uniform(cfg, lo_key, hi_key, minimum=0) -> float:
        lo = max(minimum, int(cfg[lo_key]))
        hi = max(lo, int(cfg[hi_key]))
        return random.uniform(lo, hi)

    def _random_delay(self, cfg) -> float:
        return self._uniform(cfg, "min_interval_sec", "max_interval_sec", 5)

    def _run(self):
        while True:
            self._wake.clear()
            try:
                self._tick()
            except Exception:  # noqa: BLE001
                log.exception("Errore nello scheduler")
            wait = 5.0
            if self.next_play_at is not None:
                wait = min(wait, max(0.2, self.next_play_at - time.time()))
            self._wake.wait(wait)

    def _tick(self):
        cfg = self.store.get_config()
        if not self._forced and (not cfg["enabled"] or not in_active_window(cfg)):
            self.next_play_at = None
            self.session_end = None
            return
        now = time.time()
        if self.next_play_at is None:
            self.next_play_at = now + self._random_delay(cfg)
            return
        if now < self.next_play_at or self.player.busy:
            return
        if self.session_end is None and int(cfg["session_max_sec"]) > 0:
            self.session_end = now + self._uniform(cfg, "session_min_sec", "session_max_sec")
            log.info("Inizio sessione fino alle %s", time.strftime("%H:%M:%S", time.localtime(self.session_end)))
        sound = self.player.pick_random()
        if sound:
            log.info("Riproduzione programmata: %s", sound)
            self.player.play(sound, "manuale (sessione)" if self._forced else "automatica")
        gap = self._uniform(cfg, "gap_min_sec", "gap_max_sec", 1)
        now = time.time()
        if sound and self.session_end is not None and now + gap < self.session_end:
            self.next_play_at = now + gap
        else:
            self.end_session()

    def status(self) -> dict:
        cfg = self.store.get_config()
        return {
            "enabled": cfg["enabled"],
            "in_window": in_active_window(cfg),
            "next_play_at": self.next_play_at,
            "in_session": self.in_session,
            "session_end": self.session_end,
            "forced": self._forced,
        }

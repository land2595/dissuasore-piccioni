"""Persistenza: configurazione (JSON) e registro riproduzioni (SQLite)."""
import json
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_CONFIG = {
    "enabled": True,
    # Fasce orarie attive, formato HH:MM. Una fascia può attraversare la mezzanotte.
    "windows": [{"start": "06:00", "end": "20:00"}],
    # Giorni attivi: 0 = lunedì ... 6 = domenica
    "days": [0, 1, 2, 3, 4, 5, 6],
    "min_interval_sec": 300,
    "max_interval_sec": 900,
    "volume": 80,
    "audio_device": "plughw:CARD=Headphones,DEV=0",
    "mixer_control": "PCM",
    "mixer_card": "Headphones",
    "max_play_sec": 0,
    "disabled_sounds": [],
}


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.sounds_dir = data_dir / "sounds"
        self.sounds_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = data_dir / "config.json"
        self._lock = threading.Lock()
        self._db = sqlite3.connect(data_dir / "log.db", check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS plays ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts REAL NOT NULL, sound TEXT NOT NULL, trigger TEXT NOT NULL,"
            " ok INTEGER NOT NULL, duration REAL, error TEXT)"
        )
        self._db.commit()

    # --- configurazione ---
    def get_config(self) -> dict:
        with self._lock:
            cfg = dict(DEFAULT_CONFIG)
            if self.config_path.exists():
                try:
                    cfg.update(json.loads(self.config_path.read_text()))
                except (ValueError, OSError):
                    pass
            return cfg

    def update_config(self, changes: dict) -> dict:
        cfg = self.get_config()
        cfg.update({k: v for k, v in changes.items() if k in DEFAULT_CONFIG})
        with self._lock:
            tmp = self.config_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cfg, indent=2))
            tmp.replace(self.config_path)
        return cfg

    # --- registro ---
    def log_play(self, sound, trigger, ok, duration=None, error=None):
        with self._lock:
            self._db.execute(
                "INSERT INTO plays (ts, sound, trigger, ok, duration, error) VALUES (?,?,?,?,?,?)",
                (time.time(), sound, trigger, int(ok), duration, error),
            )
            self._db.commit()

    def recent(self, limit=50):
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, sound, trigger, ok, duration, error FROM plays ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        keys = ("ts", "sound", "trigger", "ok", "duration", "error")
        return [dict(zip(keys, r)) for r in rows]

    def stats(self):
        now = time.localtime()
        midnight = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))
        with self._lock:
            today = self._db.execute(
                "SELECT COUNT(*) FROM plays WHERE ok=1 AND ts>=?", (midnight,)
            ).fetchone()[0]
            week = self._db.execute(
                "SELECT COUNT(*) FROM plays WHERE ok=1 AND ts>=?", (time.time() - 7 * 86400,)
            ).fetchone()[0]
            total = self._db.execute("SELECT COUNT(*) FROM plays WHERE ok=1").fetchone()[0]
            errors = self._db.execute(
                "SELECT COUNT(*) FROM plays WHERE ok=0 AND ts>=?", (midnight,)
            ).fetchone()[0]
            per_sound = self._db.execute(
                "SELECT sound, COUNT(*) FROM plays WHERE ok=1 GROUP BY sound ORDER BY 2 DESC"
            ).fetchall()
            hourly = self._db.execute(
                "SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER), COUNT(*)"
                " FROM plays WHERE ok=1 AND ts>=? GROUP BY 1",
                (time.time() - 7 * 86400,),
            ).fetchall()
        hours = [0] * 24
        for h, c in hourly:
            hours[h] = c
        return {
            "today": today,
            "week": week,
            "total": total,
            "errors_today": errors,
            "per_sound": {s: c for s, c in per_sound},
            "hourly_week": hours,
        }

    def clear_log(self):
        with self._lock:
            self._db.execute("DELETE FROM plays")
            self._db.commit()

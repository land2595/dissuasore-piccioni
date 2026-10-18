"""Riproduzione audio tramite ALSA (aplay / mpg123 / ogg123) e volume tramite amixer."""
import logging
import os
import random
import shutil
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("dissuasore.player")

SUPPORTED = {".mp3", ".wav", ".ogg"}
DRY_RUN = os.environ.get("DISSUASORE_DRY_RUN", "0") == "1"


def build_command(path: Path, device: str) -> list[str]:
    ext = path.suffix.lower()
    if ext == ".wav":
        return ["aplay", "-q", "-D", device, str(path)]
    if ext == ".mp3":
        return ["mpg123", "-q", "-o", "alsa", "-a", device, str(path)]
    if ext == ".ogg":
        return ["ogg123", "-q", "-d", "alsa", "-o", f"dev:{device}", str(path)]
    raise ValueError(f"Formato non supportato: {ext}")


class Player:
    def __init__(self, store):
        self.store = store
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self.current: dict | None = None
        self._last_sound: str | None = None

    # --- elenco suoni ---
    def list_sounds(self) -> list[dict]:
        cfg = self.store.get_config()
        out = []
        for p in sorted(self.store.sounds_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in SUPPORTED:
                out.append({
                    "name": p.name,
                    "size": p.stat().st_size,
                    "enabled": p.name not in cfg["disabled_sounds"],
                })
        return out

    def pick_random(self) -> str | None:
        names = [s["name"] for s in self.list_sounds() if s["enabled"]]
        if not names:
            return None
        # Evita di ripetere lo stesso verso due volte di fila (riduce l'assuefazione)
        if len(names) > 1 and self._last_sound in names:
            names.remove(self._last_sound)
        return random.choice(names)

    # --- volume ---
    def set_volume(self, percent: int) -> str | None:
        cfg = self.store.get_config()
        if DRY_RUN or not shutil.which("amixer"):
            return None
        cmd = ["amixer", "-q", "-c", str(cfg["mixer_card"]), "sset", cfg["mixer_control"], f"{int(percent)}%"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip()
            log.warning("amixer fallito: %s", msg)
            return msg
        return None

    # --- riproduzione ---
    @property
    def busy(self) -> bool:
        return self.current is not None

    def play(self, name: str, trigger: str = "manuale") -> dict:
        """Riproduce un file in modo bloccante. Restituisce l'esito."""
        path = self.store.sounds_dir / name
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            return {"ok": False, "error": "File non trovato"}
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error": "Riproduzione già in corso"}
        cfg = self.store.get_config()
        start = time.time()
        error = None
        try:
            self.current = {"sound": name, "trigger": trigger, "started": start}
            self.set_volume(cfg["volume"])
            timeout = cfg["max_play_sec"] or None
            if DRY_RUN:
                time.sleep(min(2, timeout or 2))
            else:
                cmd = build_command(path, cfg["audio_device"])
                log.info("Eseguo: %s", " ".join(cmd))
                self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                try:
                    _, err = self._proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    self._proc.terminate()
                    _, err = self._proc.communicate()
                rc = self._proc.returncode
                # rc negativo = interrotto da noi (stop o durata massima): non è un errore
                if rc and rc > 0:
                    error = (err or "").strip()[-300:] or f"codice di uscita {rc}"
        except FileNotFoundError as e:
            error = f"Programma mancante: {e.filename}"
        except Exception as e:  # noqa: BLE001
            error = str(e)
        finally:
            duration = round(time.time() - start, 1)
            self._proc = None
            self.current = None
            self._last_sound = name
            self._lock.release()
        self.store.log_play(name, trigger, error is None, duration, error)
        if error:
            log.error("Errore riproducendo %s: %s", name, error)
        return {"ok": error is None, "error": error, "duration": duration}

    def play_async(self, name: str, trigger: str = "manuale") -> bool:
        if self.busy:
            return False
        threading.Thread(target=self.play, args=(name, trigger), daemon=True).start()
        return True

    def stop(self) -> bool:
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            return True
        return False


def list_alsa_devices() -> str:
    if not shutil.which("aplay"):
        return "aplay non disponibile"
    r = subprocess.run(["aplay", "-L"], capture_output=True, text=True)
    r2 = subprocess.run(["aplay", "-l"], capture_output=True, text=True)
    return (r2.stdout + r2.stderr + "\n" + r.stdout).strip()

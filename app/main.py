"""Dissuasore piccioni: API web + interfaccia."""
import base64
import logging
import math
import os
import re
import secrets
import socket
import struct
import time
import wave
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .player import SUPPORTED, Player, list_alsa_devices
from .scheduler import Scheduler, _minutes
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
WEB_USER = os.environ.get("WEB_USER", "")
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "")
STATIC_DIR = Path(__file__).parent / "static"

store = Store(DATA_DIR)
player = Player(store)
scheduler = Scheduler(store, player)
STARTED_AT = time.time()
TEST_TONE = DATA_DIR / "test-tone.wav"

app = FastAPI(title="Dissuasore piccioni")


def _make_test_tone():
    if TEST_TONE.exists():
        return
    rate = 22050
    with wave.open(str(TEST_TONE), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 880 * i / rate)))
            for i in range(rate)
        )
        w.writeframes(frames)


@app.on_event("startup")
def _startup():
    _make_test_tone()
    scheduler.start()


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if WEB_USER and WEB_PASSWORD:
        ok = False
        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            try:
                user, _, pwd = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(user, WEB_USER) and secrets.compare_digest(pwd, WEB_PASSWORD)
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Dissuasore"'})
    return await call_next(request)


def _safe_name(name: str) -> str:
    base = Path(name).name
    stem, ext = os.path.splitext(base)
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._") or "suono"
    return f"{stem[:80]}{ext.lower()}"


def _sound_path(name: str) -> Path:
    path = store.sounds_dir / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "Suono non trovato")
    return path


# --- stato ---
@app.get("/api/status")
def status():
    cur = player.current
    return {
        **scheduler.status(),
        "playing": cur,
        "server_time": time.time(),
        "uptime_sec": round(time.time() - STARTED_AT),
        "hostname": socket.gethostname(),
        "sound_count": len(player.list_sounds()),
        "stats": store.stats(),
    }


# --- riproduzione ---
class PlayRequest(BaseModel):
    name: str | None = None


@app.post("/api/play")
def play(req: PlayRequest):
    name = req.name or player.pick_random()
    if not name:
        raise HTTPException(400, "Nessun suono disponibile")
    _sound_path(name)
    if not player.play_async(name, "manuale"):
        raise HTTPException(409, "Riproduzione già in corso")
    return {"ok": True, "sound": name}


@app.post("/api/stop")
def stop():
    return {"stopped": player.stop()}


@app.post("/api/test-audio")
def test_audio():
    """Riproduce un beep di 1 secondo per verificare il dispositivo audio (non registrato nelle statistiche)."""
    import subprocess
    from .player import DRY_RUN
    if DRY_RUN:
        return {"ok": True, "mixer_error": None, "dry_run": True}
    cfg = store.get_config()
    err = player.set_volume(cfg["volume"])
    try:
        r = subprocess.run(["aplay", "-q", "-D", cfg["audio_device"], str(TEST_TONE)],
                           capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e), "mixer_error": err}
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or "errore aplay").strip(), "mixer_error": err}
    return {"ok": True, "mixer_error": err}


@app.get("/api/devices")
def devices():
    return {"output": list_alsa_devices()}


# --- suoni ---
@app.get("/api/sounds")
def sounds():
    stats = store.stats()["per_sound"]
    return [{**s, "plays": stats.get(s["name"], 0)} for s in player.list_sounds()]


@app.post("/api/sounds")
async def upload(files: list[UploadFile] = File(...)):
    saved, errors = [], []
    for f in files:
        name = _safe_name(f.filename or "")
        if Path(name).suffix not in SUPPORTED:
            errors.append(f"{f.filename}: formato non supportato (usa mp3, wav o ogg)")
            continue
        data = await f.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            errors.append(f"{f.filename}: file troppo grande (max {MAX_UPLOAD_MB} MB)")
            continue
        dest = store.sounds_dir / name
        n = 1
        while dest.exists():
            dest = store.sounds_dir / f"{Path(name).stem}-{n}{Path(name).suffix}"
            n += 1
        dest.write_bytes(data)
        saved.append(dest.name)
    return {"saved": saved, "errors": errors}


@app.get("/api/sounds/{name}/file")
def sound_file(name: str):
    return FileResponse(_sound_path(name))


class SoundPatch(BaseModel):
    enabled: bool


@app.patch("/api/sounds/{name}")
def patch_sound(name: str, body: SoundPatch):
    path = _sound_path(name)
    disabled = set(store.get_config()["disabled_sounds"])
    if body.enabled:
        disabled.discard(path.name)
    else:
        disabled.add(path.name)
    store.update_config({"disabled_sounds": sorted(disabled)})
    return {"ok": True}


@app.delete("/api/sounds/{name}")
def delete_sound(name: str):
    path = _sound_path(name)
    if player.current and player.current["sound"] == path.name:
        player.stop()
    path.unlink()
    disabled = [n for n in store.get_config()["disabled_sounds"] if n != path.name]
    store.update_config({"disabled_sounds": disabled})
    return {"ok": True}


# --- configurazione ---
class Window(BaseModel):
    start: str
    end: str


class ConfigIn(BaseModel):
    enabled: bool | None = None
    windows: list[Window] | None = None
    days: list[int] | None = None
    min_interval_sec: int | None = None
    max_interval_sec: int | None = None
    volume: int | None = None
    audio_device: str | None = None
    mixer_control: str | None = None
    mixer_card: str | None = None
    max_play_sec: int | None = None


@app.get("/api/config")
def get_config():
    return store.get_config()


@app.put("/api/config")
def put_config(body: ConfigIn):
    changes = body.model_dump(exclude_none=True)
    if "windows" in changes:
        for w in changes["windows"]:
            for k in ("start", "end"):
                if not re.fullmatch(r"\d{1,2}:\d{2}", w[k]) or _minutes(w[k]) >= 24 * 60:
                    raise HTTPException(400, f"Orario non valido: {w[k]}")
    if "days" in changes and any(d not in range(7) for d in changes["days"]):
        raise HTTPException(400, "Giorni non validi")
    if "volume" in changes:
        changes["volume"] = max(0, min(100, changes["volume"]))
    cfg = {**store.get_config(), **changes}
    if cfg["min_interval_sec"] < 5 or cfg["max_interval_sec"] < cfg["min_interval_sec"]:
        raise HTTPException(400, "Intervallo non valido: minimo ≥ 5 s e massimo ≥ minimo")
    cfg = store.update_config(changes)
    scheduler.reschedule()
    return cfg


# --- registro ---
@app.get("/api/log")
def get_log(limit: int = 50):
    return store.recent(max(1, min(limit, 500)))


@app.delete("/api/log")
def clear_log():
    store.clear_log()
    return {"ok": True}


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

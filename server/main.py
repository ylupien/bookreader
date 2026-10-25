"""BookReader : convertit des documents en livres audio avec XTTS-v2."""
import hashlib
import hmac
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path

import torch
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import chapters as chap
from . import export, tts_engine, winutil
from .extract import SUPPORTED, detect_language, extract_document

# Electron fournit toujours DATA_DIR ; le repli sert aux essais en ligne de commande
DATA_DIR = Path(os.environ.get("DATA_DIR") or Path(os.environ.get("APPDATA", ".")) / "BookReader")
API_TOKEN = os.environ.get("BOOKREADER_TOKEN", "")
BOOKS_DIR = DATA_DIR / "books"
PREVIEW_DIR = DATA_DIR / "previews"
VOICES_DIR = DATA_DIR / "voices"
for _d in (BOOKS_DIR, PREVIEW_DIR, VOICES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD = 100 * 1024 * 1024
MAX_SAMPLE = 25 * 1024 * 1024
LANGUAGES = ("fr", "en")
MODES = ("single", "chapters")
EXPORT_KINDS = {"zip": "chapitres.zip", "m4b": "livre.m4b"}

# Voix mises en avant pour chaque langue (toutes les voix parlent FR et EN)
RECOMMENDED = {
    "fr": [("Ana Florence", "Femme · posée"), ("Claribel Dervla", "Femme · douce"), ("Damien Black", "Homme · grave")],
    "en": [("Claribel Dervla", "Femme · douce"), ("Daisy Studious", "Femme · claire"), ("Andrew Chipper", "Homme · chaleureux")],
}
# Identifiants de la version précédente
LEGACY_IDS = {
    "fr-ana": "Ana Florence", "fr-claribel": "Claribel Dervla", "fr-damien": "Damien Black",
    "en-claribel": "Claribel Dervla", "en-daisy": "Daisy Studious", "en-andrew": "Andrew Chipper",
}

PREVIEW_TEXT = {
    "en": "Hello, and welcome. Sit back, relax, and let me read your book to you.",
    "fr": "Bonjour et bienvenue. Installez-vous confortablement, je vais vous lire votre livre.",
}

app = FastAPI(title="BookReader")


@app.middleware("http")
async def require_token(request, call_next):
    """Seule la fenêtre Electron (qui ajoute l'en-tête) peut parler au serveur local."""
    if API_TOKEN and not hmac.compare_digest(request.headers.get("x-bookreader-token", ""), API_TOKEN):
        return PlainTextResponse("Accès refusé", status_code=403)
    return await call_next(request)


# --- Voix --------------------------------------------------------------------

def slug(name: str) -> str:
    return "b-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


_builtin_by_id: dict[str, str] = {}


def builtin_ids() -> dict[str, str]:
    if not _builtin_by_id:
        _builtin_by_id.update({slug(n): n for n in tts_engine.builtin_speakers()})
    return _builtin_by_id


def custom_voices() -> list[dict]:
    out = []
    for p in VOICES_DIR.glob("*.json"):
        try:
            out.append(json.loads(p.read_text("utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return sorted(out, key=lambda v: v["created"])


def resolve_voice(voice_id: str) -> str:
    """Convertit les anciens identifiants vers le format actuel."""
    return slug(LEGACY_IDS[voice_id]) if voice_id in LEGACY_IDS else voice_id


def voice_name(voice_id: str) -> str:
    voice_id = resolve_voice(voice_id)
    if voice_id in builtin_ids():
        return builtin_ids()[voice_id]
    p = VOICES_DIR / f"{voice_id}.json"
    if re.fullmatch(r"c-[0-9a-f]{12}", voice_id) and p.exists():
        return json.loads(p.read_text("utf-8"))["name"]
    raise HTTPException(400, "Voix inconnue")


def get_latents(voice_id: str):
    voice_id = resolve_voice(voice_id)
    if voice_id in builtin_ids():
        return tts_engine.builtin_latents(builtin_ids()[voice_id])
    p = VOICES_DIR / f"{voice_id}.pt"
    if re.fullmatch(r"c-[0-9a-f]{12}", voice_id) and p.exists():
        data = torch.load(p, map_location="cpu", weights_only=True)
        return data["gpt_cond_latent"], data["speaker_embedding"]
    raise HTTPException(400, "Voix inconnue (supprimée ?)")


def save_custom_voice(name: str, kind: str, latents, info: str) -> dict:
    voice_id = "c-" + uuid.uuid4().hex[:12]
    torch.save({"gpt_cond_latent": latents[0], "speaker_embedding": latents[1]}, VOICES_DIR / f"{voice_id}.pt")
    meta = {"id": voice_id, "name": name.strip()[:40] or "Ma voix", "kind": kind, "info": info, "created": time.time()}
    (VOICES_DIR / f"{voice_id}.json").write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    return meta


def parse_settings(raw: str | None) -> dict:
    try:
        return tts_engine.clean_settings(json.loads(raw) if raw else None)
    except (ValueError, TypeError):
        raise HTTPException(400, "Réglages invalides")


def check_common(language: str, speed: float) -> None:
    if language not in LANGUAGES:
        raise HTTPException(400, "Langue non supportée")
    if not 0.7 <= speed <= 1.3:
        raise HTTPException(400, "Vitesse invalide (0.7 à 1.3)")


# --- Stockage des livres -----------------------------------------------------

_meta_lock = threading.RLock()


def book_dir(book_id: str) -> Path:
    d = BOOKS_DIR / book_id
    # Empêche toute traversée de répertoire
    if d.parent != BOOKS_DIR or not d.is_dir():
        raise HTTPException(404, "Livre introuvable")
    return d


def read_meta(d: Path) -> dict:
    return json.loads((d / "meta.json").read_text("utf-8"))


def write_meta(d: Path, meta: dict) -> None:
    with _meta_lock:
        tmp = d / "meta.json.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
        winutil.replace(tmp, d / "meta.json")


def update_meta(d: Path, **fields) -> dict:
    with _meta_lock:
        meta = read_meta(d)
        meta.update(fields)
        write_meta(d, meta)
        return meta


# --- Chapitres et exports ----------------------------------------------------

def read_paragraphs(d: Path) -> list[str]:
    return (d / "text.txt").read_text("utf-8").split("\n\n")


def load_chapters(d: Path) -> list[dict]:
    """Chapitres du livre ; détectés à la volée pour les livres créés avant cette fonction."""
    p = d / "chapters.json"
    if p.exists():
        return json.loads(p.read_text("utf-8"))
    found = chap.detect(read_paragraphs(d))
    p.write_text(json.dumps(found, ensure_ascii=False), "utf-8")
    return found


def invalidate_exports(d: Path) -> None:
    """Les exports deviennent obsolètes (nouvel audio ou chapitres modifiés)."""
    with _meta_lock:
        meta = read_meta(d)
        meta["export_rev"] = meta.get("export_rev", 0) + 1
        meta["exports"] = {}
        write_meta(d, meta)
    for f in EXPORT_KINDS.values():
        (d / f).unlink(missing_ok=True)


def set_export(d: Path, kind: str, **fields) -> None:
    with _meta_lock:
        meta = read_meta(d)
        meta.setdefault("exports", {}).setdefault(kind, {}).update(fields)
        write_meta(d, meta)


export_jobs: "queue.Queue[tuple[str, str, int]]" = queue.Queue()


def queue_export(d: Path, kind: str) -> None:
    rev = read_meta(d).get("export_rev", 0)
    set_export(d, kind, status="pending", progress=0.0, error=None, rev=rev)
    export_jobs.put((d.name, kind, rev))


def run_export(book_id: str, kind: str, rev: int) -> None:
    d = BOOKS_DIR / book_id
    if not d.is_dir() or read_meta(d).get("export_rev", 0) != rev:
        return  # livre supprimé ou export devenu obsolète
    try:
        meta = public_meta(read_meta(d))
        set_export(d, kind, status="working", progress=0.0)
        chs = load_chapters(d)
        timings = json.loads((d / "timings.json").read_text("utf-8"))
        ranges = chap.time_ranges(chs, timings, meta["duration"])
        artist = f"BookReader · {meta['voice_name']}"
        last = [0.0]

        def progress(x: float) -> None:
            if x - last[0] >= 0.02 or x >= 1:
                last[0] = x
                set_export(d, kind, progress=round(x, 3))

        out = d / EXPORT_KINDS[kind]
        builder = export.build_zip if kind == "zip" else export.build_m4b
        builder(d / "audio.mp3", out, meta["title"], artist, chs, ranges, progress)
        if read_meta(d).get("export_rev", 0) != rev:
            out.unlink(missing_ok=True)  # chapitres modifiés pendant l'export
            return
        set_export(d, kind, status="ready", progress=1.0, size=out.stat().st_size)
    except Exception as e:  # noqa: BLE001
        if d.is_dir() and read_meta(d).get("export_rev", 0) == rev:
            set_export(d, kind, status="error", error=str(e)[:300])


def export_worker() -> None:
    while True:
        job = export_jobs.get()
        try:
            run_export(*job)
        finally:
            export_jobs.task_done()


def public_meta(meta: dict) -> dict:
    """Complète les métadonnées des livres créés par l'ancienne version."""
    meta = dict(meta)
    meta["voice"] = resolve_voice(meta["voice"])
    if "voice_name" not in meta:
        try:
            meta["voice_name"] = voice_name(meta["voice"])
        except HTTPException:
            meta["voice_name"] = meta["voice"]
    meta.setdefault("settings", tts_engine.clean_settings(None))
    meta.setdefault("mode", "single")
    meta.setdefault("exports", {})
    return meta


# --- File de conversion (un seul worker : le GPU traite un livre à la fois) --

jobs: "queue.Queue[str]" = queue.Queue()
cancelled: set[str] = set()


def _status_after_cancel(d: Path) -> dict:
    ready = (d / "audio.mp3").exists() and (d / "timings.json").exists()
    return {"status": "done" if ready else "draft", "progress": 1.0 if ready else 0.0, "error": None}


RESULT_FIELDS = ("voice", "voice_name", "language", "speed", "settings", "mode", "started_at")


def conversion_snapshot(meta: dict, duration: float, finished: float) -> dict:
    """Réglages réellement utilisés pour l'audio qui vient d'être produit (sauvegardés avec lui)."""
    snap = {k: meta.get(k) for k in RESULT_FIELDS}
    snap.update(duration=duration, finished_at=finished)
    return snap


def archive_current(d: Path) -> None:
    """Range l'audio actuel (avec ses exports, ses minutages et ses chapitres) dans versions/<id>/, avec ses métadonnées.
    Appelé juste avant qu'une nouvelle conversion le remplace : chaque conversion est conservée."""
    audio = d / "audio.mp3"
    if not audio.exists():
        return
    meta = read_meta(d)
    res = meta.get("result") or {k: meta.get(k) for k in RESULT_FIELDS} | {
        "duration": meta.get("duration"), "finished_at": meta.get("finished_at")}
    created = res.get("finished_at") or audio.stat().st_mtime
    vid = f"{int(created)}-{uuid.uuid4().hex[:4]}"
    vdir = d / "versions" / vid
    vdir.mkdir(parents=True)

    def keep(src: Path, name: str, move: bool = True) -> None:
        if not src.exists():
            return
        try:
            (shutil.move if move else shutil.copy2)(src, vdir / name)
        except PermissionError:   # fichier en cours de lecture (Windows) : copie, l'original sera remplacé ensuite
            shutil.copy2(src, vdir / name)

    keep(audio, "audio.mp3")
    keep(d / "timings.json", "timings.json")
    keep(d / "chapters.json", "chapters.json", move=False)
    sizes = {}
    for kind, fname in EXPORT_KINDS.items():
        keep(d / fname, fname)
        if (vdir / fname).exists():
            sizes[kind] = (vdir / fname).stat().st_size
    info = {"id": vid, "title": meta.get("title"), "created": created, "voice": res.get("voice"), "voice_name": res.get("voice_name"),
            "language": res.get("language"), "speed": res.get("speed"), "settings": res.get("settings"), "mode": res.get("mode"),
            "duration": res.get("duration"), "started_at": res.get("started_at"), "finished_at": res.get("finished_at"),
            "paragraphs": len(read_paragraphs(d)), "size": (vdir / "audio.mp3").stat().st_size if (vdir / "audio.mp3").exists() else 0,
            "exports": sizes}
    (vdir / "version.json").write_text(json.dumps(info, ensure_ascii=False), "utf-8")


def convert(book_id: str) -> None:
    d = BOOKS_DIR / book_id
    if not d.is_dir() or book_id in cancelled:   # supprimé ou annulé pendant l'attente
        cancelled.discard(book_id)
        return
    tmp_mp3 = d / "audio.tmp.mp3"
    ffmpeg = None
    aborted = False
    try:
        meta = public_meta(read_meta(d))
        settings = tts_engine.clean_settings(meta.get("settings"))
        latents = get_latents(meta["voice"])
        paragraphs = read_paragraphs(d)
        skip = chap.excluded_paragraphs(load_chapters(d), len(paragraphs)) if meta.get("mode") == "chapters" else set()
        rate = tts_engine.SAMPLE_RATE
        total_chars = max(1, sum(len(p) for i, p in enumerate(paragraphs) if i not in skip))
        done_chars = 0
        update_meta(d, status="processing", progress=0.0, error=None, started_at=time.time(), finished_at=None)

        ffmpeg = winutil.popen(
            [winutil.FFMPEG, "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1",
             "-i", "-", "-codec:a", "libmp3lame", "-b:a", "64k", str(tmp_mp3)],
            stdin=subprocess.PIPE,
        )
        pause = b"\x00\x00" * int(rate * settings["paragraph_pause"])
        samples = 0
        timings = []  # début (secondes) de chaque paragraphe, pour le surlignage
        last_save = 0.0
        for i, para in enumerate(paragraphs):
            if book_id in cancelled:
                raise InterruptedError
            timings.append(round(samples / rate, 3))
            if i in skip:
                continue  # chapitre décoché : pas synthétisé
            spoke = False
            for pcm in tts_engine.synthesize(para, latents, meta["language"], meta["speed"], settings):
                if book_id in cancelled:   # vérifié à chaque phrase : un long paragraphe ne retarde pas l'annulation
                    raise InterruptedError
                ffmpeg.stdin.write(pcm)
                samples += len(pcm) // 2
                spoke = True
            if spoke:  # un paragraphe sans rien à dire (« © », « [1] ») ne fabrique pas de silence
                ffmpeg.stdin.write(pause)
                samples += len(pause) // 2
            done_chars += len(para)
            # Progression au nombre de caractères : plus fiable pour estimer le temps restant
            if time.time() - last_save > 1 or i == len(paragraphs) - 1:
                update_meta(d, progress=done_chars / total_chars)
                last_save = time.time()
        ffmpeg.stdin.close()
        if ffmpeg.wait() != 0:
            raise RuntimeError("Échec de l'encodage MP3 (ffmpeg)")
        archive_current(d)   # la version précédente (régénération) est conservée, jamais écrasée
        winutil.replace(tmp_mp3, d / "audio.mp3")
        (d / "timings.json").write_text(json.dumps(timings), "utf-8")
        invalidate_exports(d)
        finished = time.time()
        meta = update_meta(d, status="done", progress=1.0, duration=round(samples / rate, 1), finished_at=finished,
                           result=conversion_snapshot(read_meta(d), round(samples / rate, 1), finished))
        if meta.get("mode") == "chapters":
            queue_export(d, "zip")
            queue_export(d, "m4b")
    except InterruptedError:
        aborted = True
    except Exception as e:  # noqa: BLE001
        tmp_mp3.unlink(missing_ok=True)
        if d.is_dir():
            msg = e.detail if isinstance(e, HTTPException) else str(e)
            update_meta(d, status="error", error=msg)
    finally:
        if ffmpeg and ffmpeg.poll() is None:
            ffmpeg.kill()
        if ffmpeg:
            ffmpeg.wait()   # libère le fichier avant de le supprimer (Windows)
        if aborted:
            tmp_mp3.unlink(missing_ok=True)
            if d.is_dir():  # annulée (pas supprimée) : brouillon, ou « prêt » si une version précédente existe
                update_meta(d, **_status_after_cancel(d))
        cancelled.discard(book_id)


def worker() -> None:
    tts_engine.load()  # chargement du modèle (~30 s) dès le démarrage
    while True:
        book_id = jobs.get()
        try:
            convert(book_id)
        finally:
            jobs.task_done()


@app.on_event("startup")
def startup() -> None:
    # Reprend les conversions interrompues par un redémarrage
    for d in sorted(BOOKS_DIR.iterdir(), key=lambda p: p.stat().st_mtime):
        try:
            meta = read_meta(d)
            if meta.get("status") in ("queued", "processing"):
                update_meta(d, status="queued", progress=0.0)
                jobs.put(d.name)
            for kind, ex in (meta.get("exports") or {}).items():
                if ex.get("status") in ("pending", "working"):
                    queue_export(d, kind)
        except Exception:  # noqa: BLE001
            continue
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=export_worker, daemon=True).start()


# --- API : voix --------------------------------------------------------------

@app.get("/api/config")
def get_config():
    return {
        "device": tts_engine.device(),
        "formats": sorted(SUPPORTED),
        "defaults": tts_engine.DEFAULT_SETTINGS,
        "limits": tts_engine.LIMITS,
    }


@app.get("/api/voices")
def list_voices():
    ids = builtin_ids()  # attend le chargement du modèle si nécessaire
    return {
        "recommended": {lang: [{"id": slug(n), "desc": desc} for n, desc in items]
                        for lang, items in RECOMMENDED.items()},
        "builtin": [{"id": i, "name": n} for i, n in sorted(ids.items(), key=lambda x: x[1])],
        "custom": custom_voices(),
    }


def _write_wav(path: Path, pcm_chunks) -> None:
    """Écrit du PCM 16 bits mono dans un WAV (fichier temporaire puis remplacement)."""
    tmp = path.with_suffix(".tmp")
    try:
        with wave.open(str(tmp), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(tts_engine.SAMPLE_RATE)
            for pcm in pcm_chunks:
                wav.writeframes(pcm)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    winutil.replace(tmp, path)


@app.get("/api/voices/{voice_id}/preview")
def preview_voice(
    voice_id: str,
    lang: str = "fr",
    speed: float = 1.0,
    text: str = Query("", max_length=300),
    settings: str = "",
):
    check_common(lang, speed)
    st = parse_settings(settings)
    voice_id = resolve_voice(voice_id)
    voice_name(voice_id)  # valide l'identifiant
    text = text.strip() or PREVIEW_TEXT[lang]
    key = hashlib.sha1(json.dumps([lang, speed, text, st], sort_keys=True).encode()).hexdigest()[:16]
    path = PREVIEW_DIR / f"{voice_id}_{key}.wav"
    if not path.exists():
        _write_wav(path, tts_engine.synthesize(text, get_latents(voice_id), lang, speed, st))
    return FileResponse(path, media_type="audio/wav")


def _audio_duration(path: Path) -> float:
    out = winutil.run([winutil.FFPROBE, "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


@app.post("/api/voices/clone")
async def clone_voice(name: str = Form(...), files: list[UploadFile] = File(...)):
    if not 1 <= len(files) <= 5:
        raise HTTPException(400, "Entre 1 et 5 enregistrements")
    samples = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_SAMPLE:
            raise HTTPException(413, "Enregistrement trop volumineux (max 25 Mo)")
        samples.append((f.filename, data))
    # ffmpeg + calcul GPU : hors de la boucle asynchrone pour ne pas bloquer le serveur
    return await run_in_threadpool(_clone_sync, name, samples)


def _clone_sync(name: str, samples: list[tuple[str, bytes]]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        wavs, total = [], 0.0
        for i, (filename, data) in enumerate(samples):
            src, dst = Path(tmp) / f"in{i}", Path(tmp) / f"ref{i}.wav"
            src.write_bytes(data)
            # Conversion en WAV mono 22 kHz, normalisé, 60 s max
            r = winutil.run([winutil.FFMPEG, "-y", "-loglevel", "error", "-i", str(src), "-t", "60",
                                "-ac", "1", "-ar", "22050", "-af", "loudnorm", str(dst)], capture_output=True)
            if r.returncode != 0:
                raise HTTPException(400, f"Fichier audio illisible : {filename}")
            total += _audio_duration(dst)
            wavs.append(str(dst))
        if total < 5:
            raise HTTPException(400, "Enregistrement trop court : il faut au moins 5 secondes (idéalement 15 à 30 s).")
        latents = tts_engine.clone_latents(wavs)
    return save_custom_voice(name, "clone", latents, f"Clonée · {round(total)} s d'audio")


@app.post("/api/voices/mix")
def mix_voice(name: str = Form(...), voice_a: str = Form(...), voice_b: str = Form(...),
              weight: float = Form(0.5)):
    if not 0.0 <= weight <= 1.0:
        raise HTTPException(400, "Proportion invalide")
    a, b = resolve_voice(voice_a), resolve_voice(voice_b)
    if a == b:
        raise HTTPException(400, "Choisissez deux voix différentes")
    latents = tts_engine.mix_latents(get_latents(a), get_latents(b), weight)
    pct = round(weight * 100)
    return save_custom_voice(name, "mix", latents, f"Mélange · {pct} % {voice_name(a)} + {100 - pct} % {voice_name(b)}")


@app.delete("/api/voices/{voice_id}")
def delete_voice(voice_id: str):
    if not re.fullmatch(r"c-[0-9a-f]{12}", voice_id):
        raise HTTPException(400, "Seules les voix personnalisées peuvent être supprimées")
    for p in [VOICES_DIR / f"{voice_id}.pt", VOICES_DIR / f"{voice_id}.json", *PREVIEW_DIR.glob(f"{voice_id}_*.wav")]:
        p.unlink(missing_ok=True)
    return {"ok": True}


# --- API : livres ------------------------------------------------------------

@app.post("/api/books")
async def create_book(
    file: UploadFile = File(...),
    voice: str = Form(...),
    language: str = Form(...),
    speed: float = Form(1.0),
    settings: str = Form(""),
    mode: str = Form("single"),
):
    check_common(language, speed)
    if mode not in MODES:
        raise HTTPException(400, "Mode invalide")
    st = parse_settings(settings)
    name = voice_name(voice)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Fichier trop volumineux (max 100 Mo)")
    try:
        text, structural = await run_in_threadpool(extract_document, file.filename or "", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Impossible de lire le fichier : {e}")
    if not text.strip():
        raise HTTPException(400, "Aucun texte trouvé (PDF scanné ? un OCR serait nécessaire).")

    book_id = uuid.uuid4().hex[:12]
    d = BOOKS_DIR / book_id
    d.mkdir()
    (d / "text.txt").write_text(text, "utf-8")
    found = chap.detect(text.split("\n\n"), structural)
    (d / "chapters.json").write_text(json.dumps(found, ensure_ascii=False), "utf-8")
    meta = {
        "id": book_id,
        "title": Path(file.filename or "document").stem,
        "filename": file.filename,
        "voice": resolve_voice(voice),
        "voice_name": name,
        "language": language,
        "detected_language": detect_language(text),
        "speed": speed,
        "settings": st,
        "mode": mode,
        "chapter_count": len(found),
        "chars": len(text),
        # Rien n'est converti à l'upload : l'utilisateur écoute un échantillon, ajuste la voix et les
        # réglages (et vérifie les chapitres), puis lance la conversion avec /start
        "status": "draft",
        "progress": 0.0,
        "created": time.time(),
        "error": None,
    }
    write_meta(d, meta)
    return meta


@app.get("/api/books")
def list_books():
    books = []
    for d in BOOKS_DIR.iterdir():
        try:
            books.append(public_meta(read_meta(d)))
        except Exception:  # noqa: BLE001
            continue
    return sorted(books, key=lambda b: b["created"], reverse=True)


@app.get("/api/books/{book_id}")
def get_book(book_id: str):
    return public_meta(read_meta(book_dir(book_id)))


@app.get("/api/books/{book_id}/text", response_class=PlainTextResponse)
def get_text(book_id: str):
    return (book_dir(book_id) / "text.txt").read_text("utf-8")


@app.get("/api/books/{book_id}/timings")
def get_timings(book_id: str):
    p = book_dir(book_id) / "timings.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else []


@app.get("/api/books/{book_id}/audio")
def get_audio(book_id: str, download: bool = False):
    d = book_dir(book_id)
    p = d / "audio.mp3"
    if not p.exists():
        raise HTTPException(404, "Audio pas encore prêt")
    name = f"{read_meta(d)['title']}.mp3" if download else None
    return FileResponse(p, media_type="audio/mpeg", filename=name)


@app.post("/api/books/{book_id}/regenerate")
def regenerate(book_id: str, voice: str = Form(...), language: str = Form(...),
               speed: float = Form(1.0), settings: str = Form("")):
    check_common(language, speed)
    st = parse_settings(settings)
    name = voice_name(voice)
    d = book_dir(book_id)
    if read_meta(d)["status"] in ("queued", "processing"):
        raise HTTPException(409, "Conversion déjà en cours")
    meta = update_meta(d, voice=resolve_voice(voice), voice_name=name, language=language, speed=speed,
                       settings=st, status="queued", progress=0.0, error=None, started_at=None, finished_at=None)
    jobs.put(book_id)
    return public_meta(meta)


@app.get("/api/books/{book_id}/chapters")
def get_chapters(book_id: str):
    d = book_dir(book_id)
    chs = load_chapters(d)
    meta = read_meta(d)
    tp = d / "timings.json"
    if meta.get("status") == "done" and tp.exists():
        ranges = chap.time_ranges(chs, json.loads(tp.read_text("utf-8")), meta.get("duration", 0))
        chs = [{**c, "time": round(a, 2), "length": round(b - a, 2)} for c, (a, b) in zip(chs, ranges)]
    return chs


@app.put("/api/books/{book_id}/chapters")
def put_chapters(book_id: str, items: list[dict] = Body(...)):
    d = book_dir(book_id)
    if read_meta(d)["status"] in ("queued", "processing"):
        raise HTTPException(409, "Conversion en cours : modifiez les chapitres après la conversion")
    try:
        cleaned = chap.finalize([{"title": str(c.get("title", "")), "start": int(c["start"]),
                                  "include": bool(c.get("include", True))} for c in items], read_paragraphs(d))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "Chapitres invalides")
    if not any(c["include"] for c in cleaned):
        raise HTTPException(400, "Gardez au moins un chapitre")
    (d / "chapters.json").write_text(json.dumps(cleaned, ensure_ascii=False), "utf-8")
    meta = update_meta(d, chapter_count=len(cleaned))
    invalidate_exports(d)
    if meta.get("mode") == "chapters" and meta["status"] == "done":
        queue_export(d, "zip")
        queue_export(d, "m4b")
    return get_chapters(book_id)


SAMPLE_PARAGRAPHS = 2
SAMPLE_MAX_CHARS = 1200   # borne le temps de calcul si un paragraphe est très long
SAMPLE_SELECTION_MAX_CHARS = 4000   # idem pour des paragraphes choisis à la main
SAMPLE_SELECTION_MAX_PARAGRAPHS = 30
SAFE_ID = re.compile(r"[0-9a-z-]{1,40}")


def sample_paragraphs(d: Path, meta: dict, selection: list[int] | None = None) -> list[tuple[int, str]]:
    """(numéro, texte) des paragraphes qui seront réellement lus (chapitres décochés ignorés).
    Sans sélection : les deux premiers ; avec `selection` : exactement les paragraphes cochés par l'utilisateur,
    dans l'ordre du livre (même dans un chapitre décoché : le choix explicite l'emporte)."""
    paragraphs = read_paragraphs(d)
    if selection:
        chosen = [(i, paragraphs[i].strip()) for i in sorted(set(selection)) if 0 <= i < len(paragraphs) and paragraphs[i].strip()]
        limit = SAMPLE_SELECTION_MAX_CHARS
    else:
        skip = chap.excluded_paragraphs(load_chapters(d), len(paragraphs)) if meta.get("mode") == "chapters" else set()
        kept = [(i, p.strip()) for i, p in enumerate(paragraphs) if i not in skip and p.strip()]
        # Un titre ou une ligne courte ne donne pas un échantillon représentatif : on les saute
        body = [x for x in kept if len(x[1]) >= 60]
        chosen = (body if len(body) >= SAMPLE_PARAGRAPHS else kept)[:SAMPLE_PARAGRAPHS]
        limit = SAMPLE_MAX_CHARS
    out, left = [], limit
    for i, p in chosen:
        if left <= 0:
            break
        if len(p) > left:
            cut = max(p.rfind(c, 0, left) for c in ".!?…")
            p = p[:cut + 1] if cut > 0 else p[:left]
        out.append((i, p))
        left -= len(p)
    return out


def _prepare_sample(book_id: str, voice: str, lang: str, speed: float, settings: str, sel: str) -> dict:
    """Valide la demande d'échantillon et choisit les paragraphes ; ne synthétise rien."""
    check_common(lang, speed)
    st = parse_settings(settings)
    try:
        selection = [int(x) for x in sel.split(",") if x.strip()] or None
    except ValueError:
        raise HTTPException(400, "Sélection de paragraphes invalide")
    if selection and len(set(selection)) > SAMPLE_SELECTION_MAX_PARAGRAPHS:
        raise HTTPException(400, f"Choisissez au plus {SAMPLE_SELECTION_MAX_PARAGRAPHS} paragraphes pour un échantillon")
    voice_id = resolve_voice(voice)
    name = voice_name(voice_id)  # valide l'identifiant
    d = book_dir(book_id)
    meta = read_meta(d)
    if meta["status"] in ("queued", "processing"):
        raise HTTPException(409, "Conversion en cours : l'échantillon sera possible ensuite")
    pairs = sample_paragraphs(d, meta, selection)
    if not pairs:
        raise HTTPException(400, "Aucun texte à lire dans ce livre")
    paras = [p for _, p in pairs]
    key = hashlib.sha1(json.dumps([voice_id, lang, speed, paras, st], sort_keys=True).encode()).hexdigest()[:16]
    return {"dir": d / "samples", "paras": paras, "indices": [i for i, _ in pairs], "st": st, "voice_id": voice_id,
            "voice_name": name, "lang": lang, "speed": speed, "path": d / "samples" / f"{key}.wav"}


def _write_sample_meta(job: dict) -> None:
    """Métadonnées sauvegardées avec chaque échantillon : voix, langue, vitesse, réglages, paragraphes, durée…"""
    path: Path = job["path"]
    info_path = path.with_suffix(".json")
    if info_path.exists():
        return
    with wave.open(str(path), "rb") as w:
        duration = round(w.getnframes() / w.getframerate(), 1)
    info = {"id": path.stem, "created": time.time(), "voice": job["voice_id"], "voice_name": job["voice_name"],
            "language": job["lang"], "speed": job["speed"], "settings": job["st"], "paragraphs": job["indices"],
            "chars": sum(len(p) for p in job["paras"]), "duration": duration, "size": path.stat().st_size}
    info_path.write_text(json.dumps(info, ensure_ascii=False), "utf-8")


def _render_sample(job: dict, progress=None, cancelled=None) -> None:
    """Synthétise l'échantillon (sauf s'il existe déjà) et sauvegarde ses métadonnées.
    `progress(0..1)` suit l'avancement, au morceau de phrase près."""
    path: Path = job["path"]
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        st, paras = job["st"], job["paras"]
        latents = get_latents(job["voice_id"])
        pause = b"\x00\x00" * int(tts_engine.SAMPLE_RATE * st["paragraph_pause"])
        total = sum(len(p) for p in paras) or 1

        def chunks():
            base = 0
            for n, para in enumerate(paras):
                if n:
                    yield pause
                sizes = [len(c) for c in tts_engine.chunk_text(para, job["lang"])]

                def on_chunk(i, _total, base=base, sizes=sizes):
                    if cancelled and cancelled():
                        raise InterruptedError
                    if progress:
                        progress(min(0.99, (base + sum(sizes[:i])) / total))

                yield from tts_engine.synthesize(para, latents, job["lang"], job["speed"], st, on_chunk=on_chunk)
                base += sum(sizes)

        _write_wav(path, chunks())
    _write_sample_meta(job)


# Échantillons : le travail tourne en arrière-plan, l'interface lit la progression ; chaque échantillon terminé est
# conservé dans samples/ (audio + métadonnées) jusqu'à ce que l'utilisateur le supprime
sample_jobs: dict[str, dict] = {}
_sample_run = threading.Lock()   # un échantillon à la fois


def _sample_view(job: dict) -> dict:
    return {"id": job["id"], "status": job["status"], "progress": round(job["progress"], 3), "error": job["error"],
            "sample": job["path"].stem if job["status"] == "done" else None}


@app.post("/api/books/{book_id}/sample")
def start_sample(book_id: str, voice: str = Form(...), lang: str = Form("fr"), speed: float = Form(1.0),
                 settings: str = Form(""), sel: str = Form("")):
    """Démarre la génération d'un échantillon. `sel` : numéros (à partir de 0) des paragraphes à lire, séparés par des
    virgules ; vide = les deux premiers paragraphes."""
    job = _prepare_sample(book_id, voice, lang, speed, settings, sel)
    now = time.time()
    for k in [k for k, j in sample_jobs.items() if now - j["created"] > 3600]:
        del sample_jobs[k]
    job.update(id=uuid.uuid4().hex[:12], book=book_id, status="working", progress=0.0, error=None, created=now, cancel=False)
    sample_jobs[job["id"]] = job

    def run() -> None:
        with _sample_run:
            if job["cancel"]:
                return
            try:
                _render_sample(job, lambda p: job.update(progress=p), lambda: job["cancel"])
                if not job["cancel"]:
                    job.update(status="done", progress=1.0)
            except InterruptedError:
                job.update(status="cancelled")
            except Exception as e:  # noqa: BLE001
                job.update(status="error", error=e.detail if isinstance(e, HTTPException) else str(e))

    threading.Thread(target=run, daemon=True).start()
    return _sample_view(job)


def _sample_job(book_id: str, job_id: str) -> dict:
    job = sample_jobs.get(job_id)
    if not job or job["book"] != book_id:
        raise HTTPException(404, "Échantillon introuvable")
    return job


@app.get("/api/books/{book_id}/sample/jobs/{job_id}")
def sample_status(book_id: str, job_id: str):
    return _sample_view(_sample_job(book_id, job_id))


@app.delete("/api/books/{book_id}/sample/jobs/{job_id}")
def cancel_sample(book_id: str, job_id: str):
    """Annule un échantillon en cours (le calcul s'arrête à la prochaine phrase)."""
    job = _sample_job(book_id, job_id)
    if job["status"] == "working":
        job.update(cancel=True, status="cancelled")
    return _sample_view(job)


def _sample_file(book_id: str, sample_id: str) -> Path:
    if not SAFE_ID.fullmatch(sample_id):
        raise HTTPException(404, "Échantillon introuvable")
    p = book_dir(book_id) / "samples" / f"{sample_id}.wav"
    if not p.exists():
        raise HTTPException(404, "Échantillon introuvable")
    return p


@app.get("/api/books/{book_id}/samples")
def list_samples(book_id: str):
    """Échantillons conservés de ce livre, du plus récent au plus ancien, avec leurs métadonnées."""
    sdir = book_dir(book_id) / "samples"
    out = []
    for wav in sdir.glob("*.wav") if sdir.is_dir() else []:
        try:
            out.append(json.loads(wav.with_suffix(".json").read_text("utf-8")))
        except (OSError, ValueError):
            out.append({"id": wav.stem, "created": wav.stat().st_mtime, "size": wav.stat().st_size})   # ancien échantillon sans métadonnées
    return sorted(out, key=lambda s: s.get("created", 0), reverse=True)


@app.get("/api/books/{book_id}/samples/{sample_id}/audio")
def sample_audio(book_id: str, sample_id: str):
    return FileResponse(_sample_file(book_id, sample_id), media_type="audio/wav")


@app.delete("/api/books/{book_id}/samples/{sample_id}")
def delete_sample(book_id: str, sample_id: str):
    p = _sample_file(book_id, sample_id)
    p.unlink(missing_ok=True)
    p.with_suffix(".json").unlink(missing_ok=True)
    return {"ok": True}


# --- Versions : chaque conversion est conservée (audio, exports, minutages, chapitres + métadonnées) -------------

def _version_dir(book_id: str, version_id: str) -> Path:
    p = book_dir(book_id) / "versions" / version_id
    if not SAFE_ID.fullmatch(version_id) or not p.is_dir():
        raise HTTPException(404, "Version introuvable")
    return p


@app.get("/api/books/{book_id}/versions")
def list_versions(book_id: str):
    """Conversions précédentes de ce livre, de la plus récente à la plus ancienne."""
    vroot = book_dir(book_id) / "versions"
    out = []
    for vdir in vroot.iterdir() if vroot.is_dir() else []:
        try:
            out.append(json.loads((vdir / "version.json").read_text("utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda v: v.get("created", 0), reverse=True)


@app.get("/api/books/{book_id}/versions/{version_id}/audio")
def version_audio(book_id: str, version_id: str, download: bool = False):
    vdir = _version_dir(book_id, version_id)
    info = json.loads((vdir / "version.json").read_text("utf-8"))
    name = export.safe_name(f"{info.get('title') or 'livre'} ({info.get('voice_name') or 'voix'}, {time.strftime('%Y-%m-%d %H-%M', time.localtime(info.get('created') or 0))}).mp3")
    return FileResponse(vdir / "audio.mp3", media_type="audio/mpeg", filename=name if download else None)


@app.get("/api/books/{book_id}/versions/{version_id}/export/{kind}")
def version_export(book_id: str, version_id: str, kind: str):
    if kind not in EXPORT_KINDS:
        raise HTTPException(404, "Export inconnu")
    vdir = _version_dir(book_id, version_id)
    p = vdir / EXPORT_KINDS[kind]
    if not p.exists():
        raise HTTPException(404, "Export absent de cette version")
    info = json.loads((vdir / "version.json").read_text("utf-8"))
    title = export.safe_name(f"{info.get('title') or 'livre'} ({info.get('voice_name') or 'voix'})")
    return FileResponse(p, media_type="application/zip" if kind == "zip" else "audio/mp4",
                        filename=f"{title} (chapitres).zip" if kind == "zip" else f"{title}.m4b")


@app.delete("/api/books/{book_id}/versions/{version_id}")
def delete_version(book_id: str, version_id: str):
    shutil.rmtree(_version_dir(book_id, version_id), ignore_errors=True)
    return {"ok": True}

@app.post("/api/books/{book_id}/start")
def start_book(book_id: str, voice: str | None = Form(None), language: str | None = Form(None),
               speed: float | None = Form(None), settings: str | None = Form(None)):
    """Lance la conversion intégrale. Les réglages donnés (voix, langue, vitesse…) remplacent ceux de l'upload."""
    d = book_dir(book_id)
    if read_meta(d)["status"] != "draft":
        raise HTTPException(409, "Ce livre n'est pas en attente de lancement")
    fields: dict = {}
    if voice is not None:
        fields.update(voice=resolve_voice(voice), voice_name=voice_name(voice))
    if language is not None or speed is not None:
        meta = read_meta(d)
        language = language if language is not None else meta["language"]
        speed = speed if speed is not None else meta["speed"]
        check_common(language, speed)
        fields.update(language=language, speed=speed)
    if settings is not None:
        fields["settings"] = parse_settings(settings)
    meta = update_meta(d, status="queued", progress=0.0, **fields)
    jobs.put(book_id)
    return public_meta(meta)


@app.post("/api/books/{book_id}/export/{kind}")
def start_export(book_id: str, kind: str):
    if kind not in EXPORT_KINDS:
        raise HTTPException(404, "Export inconnu")
    d = book_dir(book_id)
    meta = read_meta(d)
    if meta["status"] != "done":
        raise HTTPException(409, "Le livre n'est pas encore converti")
    if (meta.get("exports") or {}).get(kind, {}).get("status") not in ("pending", "working"):
        queue_export(d, kind)
    return read_meta(d)["exports"][kind]


@app.get("/api/books/{book_id}/export/{kind}")
def download_export(book_id: str, kind: str):
    if kind not in EXPORT_KINDS:
        raise HTTPException(404, "Export inconnu")
    d = book_dir(book_id)
    p = d / EXPORT_KINDS[kind]
    if not p.exists():
        raise HTTPException(404, "Export pas encore prêt")
    title = export.safe_name(read_meta(d)["title"])
    name = f"{title} (chapitres).zip" if kind == "zip" else f"{title}.m4b"
    media = "application/zip" if kind == "zip" else "audio/mp4"
    return FileResponse(p, media_type=media, filename=name)


@app.post("/api/books/{book_id}/cancel")
def cancel_book(book_id: str):
    """Annule une conversion en attente ou en cours : le livre redevient un brouillon (ou reste « prêt » s'il avait déjà un audio)."""
    d = book_dir(book_id)
    status = read_meta(d)["status"]
    if status not in ("queued", "processing"):
        raise HTTPException(409, "Aucune conversion à annuler")
    cancelled.add(book_id)
    if status == "queued":  # pas encore démarrée : on remet l'état tout de suite (le travailleur la saute)
        update_meta(d, **_status_after_cancel(d))
    return public_meta(read_meta(d))   # en cours : l'état change dès que le calcul s'arrête (quelques secondes)


@app.delete("/api/books/{book_id}")
def delete_book(book_id: str):
    d = book_dir(book_id)
    cancelled.add(book_id)
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")

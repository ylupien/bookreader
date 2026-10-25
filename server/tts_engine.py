"""Synthèse vocale avec XTTS-v2 (Coqui), sur GPU si disponible.

Une « voix » = deux tenseurs (gpt_cond_latent + speaker_embedding) passés au modèle.
Les voix intégrées viennent du modèle ; les voix personnalisées (clonées ou mélangées)
sont stockées dans DATA_DIR/voices.
"""
import re
import threading

import numpy as np
import torch

from . import speech_text

SAMPLE_RATE = 24000

DEFAULT_SETTINGS = {
    "temperature": 0.75,          # expressivité / variabilité
    "top_p": 0.85,                # variété de l'intonation
    "repetition_penalty": 5.0,    # évite bégaiements et sons répétés
    "sentence_pause": 0.25,       # secondes entre phrases
    "paragraph_pause": 0.8,       # secondes entre paragraphes
}
LIMITS = {
    "temperature": (0.1, 1.0),
    "top_p": (0.1, 1.0),
    "repetition_penalty": (1.0, 15.0),
    "sentence_pause": (0.0, 1.5),
    "paragraph_pause": (0.0, 3.0),
}

_tts = None
_load_lock = threading.Lock()
_gpu_lock = threading.Lock()   # une seule inférence à la fois sur le GPU


def device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def load():
    global _tts
    with _load_lock:
        if _tts is None:
            from TTS.api import TTS

            _tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device())
    return _tts.synthesizer.tts_model


def is_loaded() -> bool:
    return _tts is not None


def clean_settings(raw: dict | None) -> dict:
    """Complète avec les valeurs par défaut et borne chaque réglage."""
    out = dict(DEFAULT_SETTINGS)
    for k, (lo, hi) in LIMITS.items():
        if raw and raw.get(k) is not None:
            out[k] = min(hi, max(lo, float(raw[k])))
    return out


# --- Voix --------------------------------------------------------------------

def builtin_speakers() -> list[str]:
    return sorted(load().speaker_manager.speakers.keys())


def builtin_latents(name: str):
    s = load().speaker_manager.speakers[name]
    return s["gpt_cond_latent"], s["speaker_embedding"]


def clone_latents(audio_paths: list[str]):
    """Calcule l'empreinte vocale d'un ou plusieurs enregistrements."""
    model = load()
    with _gpu_lock, torch.inference_mode():
        gpt, spk = model.get_conditioning_latents(audio_path=audio_paths, gpt_cond_len=30, max_ref_length=60)
    return gpt.cpu(), spk.cpu()


def mix_latents(a, b, weight_a: float):
    """Mélange linéaire de deux voix (weight_a = part de la voix A, entre 0 et 1)."""
    w = float(weight_a)
    return (a[0].cpu() * w + b[0].cpu() * (1 - w)), (a[1].cpu() * w + b[1].cpu() * (1 - w))


# --- Découpage du texte ------------------------------------------------------
# Le nettoyage et le découpage sont dans speech_text.py (XTTS invente des mots sur la ponctuation seule,
# les caractères inconnus et les morceaux orphelins). Ici : le lien avec le tokenizer du modèle.

_known_cache: dict[str, bool] = {}


def _is_known(ch: str) -> bool:
    """Le tokenizer de XTTS connaît-il ce caractère ? (sinon il le lit comme un son inventé)"""
    ok = _known_cache.get(ch)
    if ok is None:
        tok = load().tokenizer.tokenizer
        ok = tok.token_to_id("[UNK]") not in tok.encode(ch.lower().replace(" ", "[SPACE]")).ids
        _known_cache[ch] = ok
    return ok


def chunk_text(text: str, language: str = "en") -> list[str]:
    """Morceaux qui seront réellement envoyés au moteur (texte nettoyé, une phrase par morceau)."""
    return speech_text.chunk_text(text, _is_known if _tts is not None else None, language)

# --- Synthèse ----------------------------------------------------------------

def synthesize(text: str, latents, language: str, speed: float = 1.0, settings: dict | None = None, on_chunk=None):
    """Génère l'audio PCM 16 bits mono (24 kHz), phrase par phrase.
    `on_chunk(i, total)` est appelée avant chaque morceau (i morceaux déjà faits sur `total`) : sert à la progression."""
    model = load()
    st = clean_settings(settings)
    gpt, spk = latents
    dev = model.device
    pause = b"\x00\x00" * int(SAMPLE_RATE * st["sentence_pause"])
    chunks = chunk_text(text, language)
    for i, chunk in enumerate(chunks):
        if on_chunk:
            on_chunk(i, len(chunks))
        with _gpu_lock, torch.inference_mode():
            out = model.inference(
                chunk, language, gpt.to(dev), spk.to(dev),
                temperature=st["temperature"], top_p=st["top_p"], top_k=50,
                repetition_penalty=st["repetition_penalty"], length_penalty=1.0,
                speed=speed, enable_text_splitting=False,
            )
        wav = out["wav"]
        wav = wav.cpu().numpy() if torch.is_tensor(wav) else np.asarray(wav)
        pcm = (np.clip(wav.astype(np.float32).reshape(-1), -1.0, 1.0) * 32767).astype(np.int16)
        yield pcm.tobytes()
        if i < len(chunks) - 1:
            yield pause

"""Aides propres à Windows : chemins ffmpeg, fenêtre console cachée, remplacement de fichiers."""
import os
import subprocess
import time
from pathlib import Path

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")

# Sans ce drapeau, une console s'ouvre à chaque appel de ffmpeg depuis une application graphique
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(*args, **kwargs):
    return subprocess.run(*args, creationflags=NO_WINDOW, **kwargs)


def popen(*args, **kwargs):
    return subprocess.Popen(*args, creationflags=NO_WINDOW, **kwargs)


def replace(src: Path, dst: Path, attempts: int = 20, delay: float = 0.25) -> None:
    """Path.replace avec nouvelles tentatives : sous Windows, la destination peut être
    verrouillée un court instant (lecteur, antivirus, indexation)."""
    for n in range(attempts):
        try:
            src.replace(dst)
            return
        except PermissionError:
            if n == attempts - 1:
                raise
            time.sleep(delay)

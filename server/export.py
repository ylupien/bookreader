"""Exports d'un livre converti : un MP3 par chapitre (ZIP) et un M4B avec chapitres."""
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from . import winutil

_RESERVED = re.compile(r"(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$")


def safe_name(s: str, limit: int = 80) -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", s).strip(" .")
    s = s[:limit].strip(" .")
    if _RESERVED.match(s):
        s = "_" + s
    return s or "Sans titre"


def _segments(chapters, ranges):
    """Chapitres retenus avec leurs bornes (secondes), en ignorant les segments vides."""
    return [(i, c, start, end) for i, (c, (start, end)) in enumerate(zip(chapters, ranges))
            if c.get("include", True) and end - start > 0.05]


def build_zip(audio: Path, out: Path, title: str, artist: str, chapters, ranges, progress) -> None:
    segs = _segments(chapters, ranges)
    if not segs:
        raise ValueError("Aucun chapitre sélectionné")
    width = max(2, len(str(len(segs))))
    tmp_zip = out.with_suffix(".tmp")
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_STORED) as zf:
        playlist = ["#EXTM3U"]
        for n, (_, c, start, end) in enumerate(segs, 1):
            name = f"{str(n).zfill(width)} - {safe_name(c['title'])}.mp3"
            dst = Path(tmp) / f"{n}.mp3"
            # Découpe sans réencodage (rapide, aucune perte de qualité) + tags ID3
            winutil.run(
                [winutil.FFMPEG, "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                 "-i", str(audio), "-map", "0:a", "-c", "copy", "-id3v2_version", "3",
                 "-metadata", f"title={c['title']}", "-metadata", f"album={title}",
                 "-metadata", f"artist={artist}", "-metadata", f"track={n}/{len(segs)}",
                 "-metadata", "genre=Audiobook", str(dst)],
                check=True, capture_output=True,
            )
            zf.write(dst, name)
            dst.unlink()
            playlist += [f"#EXTINF:{round(end - start)},{c['title']}", name]
            progress(n / len(segs))
        zf.writestr(f"{safe_name(title)}.m3u", "\n".join(playlist) + "\n")
    winutil.replace(tmp_zip, out)


def _concat_quote(p: Path) -> str:
    # Dans une liste concat, une apostrophe se note '\''
    return p.as_posix().replace("'", "'\\''")


def _ffmeta_escape(s: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", s)


def build_m4b(audio: Path, out: Path, title: str, artist: str, chapters, ranges, progress) -> None:
    segs = _segments(chapters, ranges)
    if not segs:
        raise ValueError("Aucun chapitre sélectionné")
    total = sum(end - start for _, _, start, end in segs)
    with tempfile.TemporaryDirectory() as tmp:
        # Liste de segments (permet d'exclure les chapitres décochés)
        lst = Path(tmp) / "list.txt"
        lst.write_text("".join(
            f"file '{_concat_quote(audio)}'\ninpoint {start:.3f}\noutpoint {end:.3f}\n" for _, _, start, end in segs
        ), "utf-8")
        meta = [";FFMETADATA1", f"title={_ffmeta_escape(title)}", f"album={_ffmeta_escape(title)}",
                f"artist={_ffmeta_escape(artist)}", "genre=Audiobook"]
        pos = 0.0
        for _, c, start, end in segs:
            length = end - start
            meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(pos * 1000)}",
                     f"END={round((pos + length) * 1000)}", f"title={_ffmeta_escape(c['title'])}"]
            pos += length
        meta_file = Path(tmp) / "meta.txt"
        meta_file.write_text("\n".join(meta) + "\n", "utf-8")
        tmp_out = out.with_name(out.name + ".tmp")  # même disque que la destination
        proc = winutil.popen(
            [winutil.FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-i", str(meta_file), "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
             "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", "-f", "mp4",
             "-progress", "pipe:1", "-nostats", str(tmp_out)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for line in proc.stdout:
            if line.startswith("out_time_us=") and line.strip() != "out_time_us=N/A":
                progress(min(0.99, int(line.split("=")[1]) / 1e6 / max(total, 1)))
        if proc.wait() != 0:
            tmp_out.unlink(missing_ok=True)
            raise RuntimeError("Échec de la création du M4B : " + proc.stderr.read()[-300:])
        winutil.replace(tmp_out, out)

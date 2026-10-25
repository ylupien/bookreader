"""Détection et gestion des chapitres d'un livre (en indices de paragraphes)."""
import re
import unicodedata

MAX_TITLE = 80              # au-delà, un paragraphe n'est pas un titre
FALLBACK_CHARS = 20000      # découpe par longueur : ~25 à 30 min d'audio par partie

_HEADING = re.compile(
    r"^(chapitre|chapter|chap\.|partie|part|livre|book|tome|volume|prologue|[ée]pilogue|epilogue|"
    r"introduction|conclusion|pr[ée]face|preface|avant-propos|postface|afterword|foreword|interlude|"
    r"annexe|appendix|intermède|interm[eè]de)\b",
    re.IGNORECASE,
)
# Parties qu'on préfère ne pas écouter (décochées par défaut)
_FRONT_MATTER = re.compile(
    r"^(table of contents|contents|table des mati[eè]res|sommaire|cover|couverture|copyright|"
    r"droits d'auteur|mentions l[ée]gales|about .*|[àa] propos de .*|du m[eê]me auteur|also by .*|"
    r"(bonus )?(high resolution )?(color )?(illustrations?|images)|landmarks|title page|page de titre|"
    r"newsletter|isbn.*)$",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def default_include(title: str) -> bool:
    return not _FRONT_MATTER.match(title.strip())


def _from_toc(paragraphs: list[str]) -> list[dict]:
    """Retrouve dans le texte les titres listés par une table des matières en début de livre."""
    limit = min(len(paragraphs), max(60, len(paragraphs) // 7))
    best = (0, 0)
    i = 0
    while i < limit:  # plus longue suite de paragraphes courts = table des matières probable
        j = i
        while j < len(paragraphs) and len(paragraphs[j]) <= MAX_TITLE:
            j += 1
        if j - i > best[1] - best[0]:
            best = (i, j)
        i = j + 1
    lo, hi = best
    if hi - lo < 4:
        return []
    found, pos = [], lo
    for t in range(lo, hi):
        key = _norm(paragraphs[t])
        if not key:
            continue
        # Cherche après l'entrée elle-même : le premier titre suit parfois la table directement
        for k in range(max(pos, t + 1), len(paragraphs)):
            if len(paragraphs[k]) <= MAX_TITLE and _norm(paragraphs[k]) == key:
                found.append({"title": paragraphs[k], "start": k})
                pos = k + 1
                break
    return found if len(found) >= 3 and len(found) >= (hi - lo) // 3 else []


def _from_headings(paragraphs: list[str]) -> list[dict]:
    """Paragraphes courts du type « Chapitre 3 », « Prologue », « Partie II »."""
    idx = [i for i, p in enumerate(paragraphs) if len(p) <= MAX_TITLE and _HEADING.match(p.strip())]
    # Des titres consécutifs forment une table des matières : on les ignore
    runs, keep = [], []
    for i in idx:
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    for r in runs:
        if len(r) < 3:
            keep.append(r[-1] if len(r) == 2 else r[0])
    out = []
    for i in keep:
        title = paragraphs[i].strip()
        nxt = paragraphs[i + 1].strip() if i + 1 < len(paragraphs) else ""
        # « Chapitre 3 » suivi d'un sous-titre court : on les combine
        if re.fullmatch(r"\w+\.?\s+[\wIVXLC]+\.?", title) and 0 < len(nxt) <= 60 and not re.search(r"[.!?]$", nxt):
            title = f"{title} — {nxt}"
        out.append({"title": title, "start": i})
    return out if len(out) >= 2 else []


def _by_length(paragraphs: list[str]) -> list[dict]:
    out, size = [{"title": "Partie 1", "start": 0}], 0
    for i, p in enumerate(paragraphs):
        if size >= FALLBACK_CHARS and i < len(paragraphs) - 1:
            out.append({"title": f"Partie {len(out) + 1}", "start": i})
            size = 0
        size += len(p)
    return out


def finalize(chapters: list[dict], paragraphs: list[str]) -> list[dict]:
    """Trie, dédoublonne, ajoute un chapitre « Début » si besoin et fixe les cases à cocher."""
    n = len(paragraphs)
    seen, out = set(), []
    for c in sorted(chapters, key=lambda c: int(c["start"])):
        s = int(c["start"])
        if 0 <= s < n and s not in seen:
            seen.add(s)
            title = (str(c.get("title") or "").strip() or paragraphs[s][:60])[:120]
            out.append({"title": title, "start": s,
                        "include": bool(c["include"]) if "include" in c else default_include(title)})
    if not out or out[0]["start"] != 0:
        first = paragraphs[0].strip() if n else ""
        title = first if 0 < len(first) <= MAX_TITLE else "Début"
        out.insert(0, {"title": title, "start": 0, "include": default_include(title)})
    return out


def detect(paragraphs: list[str], structural: list[dict] | None = None) -> list[dict]:
    """Choisit la meilleure source : structure du document, table des matières, titres, longueur."""
    for found in (structural or [], _from_toc(paragraphs), _from_headings(paragraphs)):
        if len(found) >= 2:
            return finalize(found, paragraphs)
    return finalize(_by_length(paragraphs), paragraphs)


def time_ranges(chapters: list[dict], timings: list[float], duration: float) -> list[tuple[float, float]]:
    """Début et fin (secondes) de chaque chapitre dans le MP3 complet."""
    starts = [timings[c["start"]] if c["start"] < len(timings) else duration for c in chapters]
    ends = starts[1:] + [duration]
    return list(zip(starts, ends))


def excluded_paragraphs(chapters: list[dict], n: int) -> set[int]:
    out = set()
    for i, c in enumerate(chapters):
        if not c.get("include", True):
            end = chapters[i + 1]["start"] if i + 1 < len(chapters) else n
            out.update(range(c["start"], end))
    return out

"""Préparation du texte avant la synthèse vocale.

XTTS « invente » des mots dans trois cas, mesurés avec une retranscription Whisper de l'audio produit :
  - un morceau fait de ponctuation seule (« . », « ” », « » ») : il prononce du charabia (« Nine round », « Yua »…) ;
    ces morceaux apparaissent à chaque fin de dialogue typographique (`… . ”`), car l'espace avant le guillemet
    fait couper la phrase ;
  - un morceau très court issu d'une abréviation coupée (« p. 12 » → « p. » + « 12). » → « CPA 12 ») ;
  - un caractère inconnu de son vocabulaire (©, [, ], +, }…) ou un appel de note (« [1] » → « one you »,
    « animals.1 » → « one door »).
Ce module nettoie le texte, le découpe en phrases sans couper après une abréviation, et ne laisse jamais de morceau
orphelin. Il ne dépend ni de torch ni du modèle : `is_known` (caractère connu du tokenizer) est fourni par l'appelant.
"""
import re
import unicodedata
from typing import Callable

MAX_CHUNK = 230          # XTTS supporte ~250 caractères (EN) / ~273 (FR) par appel
MIN_SENTENCE = 25        # les phrases très courtes sont fusionnées avec la suivante
MIN_LAST_CHUNK = 25      # le dernier morceau d'un texte n'est jamais plus court (sauf texte entier court)
HARD_LIMIT = 250         # un morceau fusionné ne dépasse jamais cette taille

# --- Nettoyage des caractères ------------------------------------------------

_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st", "œ": "oe", "Œ": "Oe"}
_SPACES = "            　\t\r\f\v"
_INVISIBLE = "­​‌‍⁠﻿‎‏‪‫‬‭‮"
_QUOTES = "“”„‟\"«»‹›❝❞〝〞"
_SUPERSCRIPTS = "¹²³⁴⁵⁶⁷⁸⁹⁰"
# Symboles que le modèle ne sait pas dire : remplacés par une espace
_SYMBOLS = "©®™℗§¶†‡•▪▫◦●○■□▲►◄★☆✓✔✗✘→←↑↓⇒⇐↔*_~^|\\<>{}[]=`¦¬"

# Abréviations que le moteur épelle (« p. 12 » → « P-12 ») : dites en toutes lettres quand un nombre suit
_ABBREVIATIONS = {
    "en": [(r"\bpp\.\s*(?=\d)", "pages "), (r"\bp\.\s*(?=\d)", "page "), (r"\bNos?\.\s*(?=\d)", "number "),
           (r"\bFigs?\.\s*(?=\d)", "figure "), (r"\bVols?\.\s*(?=\d)", "volume "), (r"\bCh\.\s*(?=\d)", "chapter ")],
    "fr": [(r"\bpp\.\s*(?=\d)", "pages "), (r"\bp\.\s*(?=\d)", "page "), (r"\bn[°º]\s*(?=\d)", "numéro "),
           (r"\bNos?\.\s*(?=\d)", "numéro "), (r"\bFigs?\.\s*(?=\d)", "figure "), (r"\bVols?\.\s*(?=\d)", "volume "),
           (r"\bch\.\s*(?=\d)", "chapitre ")],
}
_CITATION = re.compile(r"\[\s*(?:\d+|[a-z])(?:\s*[,;–-]\s*\d+)*\s*\]")          # [1] [12] [1, 3] [1–4] [a]
_FOOTNOTE = re.compile(r"(?<=[A-Za-zÀ-ÿ][.!?…:;,])\d{1,3}(?=\s+[A-ZÀ-Ý“«‘]|\s*$)")   # « animals.1 The next… »
_ELLIPSIS = re.compile(r"\.(?:\s*\.){2,}|…")
_MULTISPACE = re.compile(r"\s+")


def clean_for_speech(text: str, is_known: Callable[[str], bool] | None = None, lang: str = "en") -> str:
    """Texte débarrassé de ce que le moteur prononcerait mal. `is_known(c)` : le tokenizer connaît-il ce caractère ?"""
    text = unicodedata.normalize("NFC", text)
    for a, b in _LIGATURES.items():
        text = text.replace(a, b)
    text = text.translate({ord(c): " " for c in _SPACES} | {ord(c): None for c in _INVISIBLE})
    text = "".join(ch for ch in text if ch in "\n" or unicodedata.category(ch)[0] != "C")   # caractères de contrôle
    # Appels de note
    text = _CITATION.sub("", text)
    text = text.translate({ord(c): None for c in _SUPERSCRIPTS})
    text = _FOOTNOTE.sub("", text)
    # Guillemets : le moteur ne les dit pas, et un guillemet isolé en fin de phrase fabrique un morceau de ponctuation
    text = text.translate({ord(c): " " for c in _QUOTES})
    text = re.sub(r"(?<=\w)[’‘](?=\w)", "'", text)       # apostrophe typographique entre deux lettres : d’abord → d'abord
    text = text.replace("’", " ").replace("‘", " ")      # sinon : guillemet simple (‘Oui,’ dit-il) → supprimé
    for pattern, spoken in _ABBREVIATIONS.get(lang, []):
        text = re.sub(pattern, spoken, text, flags=re.IGNORECASE)
    text = text.replace("+", " plus ")
    text = text.translate({ord(c): " " for c in _SYMBOLS})
    # Caractères hors vocabulaire du moteur
    if is_known is not None:
        text = "".join(ch if ch.isspace() or is_known(ch) else " " for ch in text)
    # Points de suspension homogènes (« . . . », « … », « ... »)
    text = _ELLIPSIS.sub("...", text)
    text = re.sub(r"\s+([,;:!?.…])", r"\1", text)         # « mot , » → « mot, »
    return _MULTISPACE.sub(" ", text).strip()


# --- Découpage en phrases et en morceaux -------------------------------------

# Ne terminent jamais une phrase : le point qui suit appartient à l'abréviation
_NEVER_END = {
    "mr", "mrs", "ms", "dr", "drs", "prof", "sr", "jr", "st", "mt", "no", "nos", "nº", "n°", "p", "pp", "vs", "fig", "figs",
    "vol", "vols", "ch", "chap", "cf", "art", "ex", "approx", "dept", "mme", "mmes", "mlle", "mlles", "m", "mm", "me", "mgr",
    "col", "gen", "lt", "sgt", "capt", "hon", "rev", "ed", "eds", "tel", "env", "av", "bd", "fr", "ms", "pl", "sec", "col", "ca",
}
_BOUNDARY = re.compile(r"(?<=[.!?…])\s+")
_INITIAL = re.compile(r"^[A-ZÀ-Ý]\.$")
_STARTS_SENTENCE = re.compile(r"^[A-ZÀ-Ý0-9(\[]")


def split_sentences(text: str) -> list[str]:
    """Phrases du texte, sans couper après une abréviation (« p. 12 », « Mr. Smith », « J. K. Rowling », « etc. »)."""
    out, start = [], 0
    for m in _BOUNDARY.finditer(text):
        before, after = text[start:m.start()], text[m.end():]
        last = before.split()[-1] if before.split() else ""
        word = last.rstrip(".").lower().strip("(")
        ends_with_dot = last.endswith(".") and not last.endswith("..")
        split = True
        if ends_with_dot and (word in _NEVER_END or _INITIAL.match(last)):
            split = False
        elif last.endswith(("?", "!")):
            split = True
        elif not _STARTS_SENTENCE.match(after):
            split = False                      # la suite commence par une minuscule : ce n'est pas une fin de phrase
        if split:
            out.append(text[start:m.start()].strip())
            start = m.end()
    out.append(text[start:].strip())
    return [s for s in out if s]


_SOFT_BREAK = re.compile(r"(?<=[,;:])\s+")


def _split_long(sentence: str) -> list[str]:
    """Coupe une phrase trop longue aux virgules, puis aux espaces en dernier recours."""
    if len(sentence) <= MAX_CHUNK:
        return [sentence]
    out, cur = [], ""
    for part in _SOFT_BREAK.split(sentence):
        while len(part) > MAX_CHUNK:
            cut = part.rfind(" ", 0, MAX_CHUNK)
            cut = cut if cut > 0 else MAX_CHUNK
            out.append(part[:cut])
            part = part[cut:].strip()
        if cur and len(cur) + len(part) + 1 > MAX_CHUNK:
            out.append(cur)
            cur = part
        else:
            cur = f"{cur} {part}".strip()
    if cur:
        out.append(cur)
    return out


def finish(chunk: str) -> str:
    """Termine le morceau par une ponctuation de fin de phrase (sans quoi XTTS ajoute des sons parasites)."""
    chunk = chunk.strip()
    if not chunk:
        return chunk
    if chunk[-1] in ".!?…":
        return chunk
    if chunk[-1] in ",;:—–-":
        return chunk[:-1].rstrip() + "."
    return chunk + "."


def chunk_text(text: str, is_known: Callable[[str], bool] | None = None, lang: str = "en") -> list[str]:
    """Morceaux à synthétiser, déjà nettoyés : une phrase par morceau (les très courtes sont regroupées),
    ≤ MAX_CHUNK caractères, aucun morceau de ponctuation seule et aucun dernier morceau orphelin."""
    text = clean_for_speech(text, is_known, lang)
    if not any(c.isalnum() for c in text):
        return []
    pieces = []
    for s in split_sentences(text):
        pieces.extend(_split_long(s.strip()))
    chunks, cur = [], ""
    for p in filter(None, pieces):
        if cur and (len(cur) >= MIN_SENTENCE or len(cur) + len(p) + 1 > MAX_CHUNK):
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        chunks.append(cur)
    # Un dernier morceau très court (« 12). », « Oui. ») est rattaché au précédent plutôt que lu seul
    while len(chunks) > 1 and len(chunks[-1]) < MIN_LAST_CHUNK and len(chunks[-2]) + len(chunks[-1]) + 1 <= HARD_LIMIT:
        last = chunks.pop()
        chunks[-1] = f"{chunks[-1]} {last}"
    chunks = [c for c in chunks if any(ch.isalnum() for ch in c)]
    return [finish(c) for c in chunks]

"""Extraction de texte (et des chapitres) depuis différents formats de fichiers."""
import io
import re
import statistics
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup

SUPPORTED = {".pdf", ".txt", ".md", ".markdown", ".html", ".htm", ".docx", ".epub", ".rtf"}

# Un début de chapitre est marqué « \x01titre\x02 » en tête de paragraphe pendant
# l'extraction ; le marqueur traverse le nettoyage puis est retiré par split_markers().
M_START, M_END = "\x01", "\x02"


def _mark(title: str) -> str:
    title = re.sub(r"\s+", " ", title.replace(M_START, "").replace(M_END, "")).strip()
    return f"{M_START}{title}{M_END}"


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _html_to_text(html: str, mark_headings: bool = False) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    if mark_headings:
        for h in soup.find_all(["h1", "h2"]):
            title = h.get_text(" ", strip=True)
            if title:
                h.insert(0, _mark(title))
    # Sépare les blocs par des lignes vides pour garder les paragraphes
    for tag in soup.find_all(["p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]):
        tag.append("\n\n")
    return soup.get_text()


# --- PDF ---------------------------------------------------------------------

def _pdf_page_text(text: str) -> str:
    """Reconstitue les paragraphes d'une page PDF (pypdf renvoie une ligne par ligne visuelle)."""
    lines = [l.strip() for l in text.split("\n")]
    lines = [l for l in lines if l and not re.fullmatch(r"[-–—\s]*\d{1,4}[-–—\s]*", l)]  # numéros de page
    if not lines:
        return ""
    typical = statistics.median(len(l) for l in lines) or 1
    out = []
    for i, line in enumerate(lines):
        out.append(line)
        short = len(line) < 0.8 * typical
        if (short and re.search(r"[.!?:»\"”]$", line)) or len(line) < 0.5 * typical:
            out.append("")  # fin de paragraphe probable
    return "\n".join(out)


def _pdf_outline(reader) -> dict[int, list[str]]:
    """Signets du PDF : {numéro de page: [titres]} (premier niveau, ou tous si trop peu)."""
    def walk(items, depth, acc):
        for it in items:
            if isinstance(it, list):
                walk(it, depth + 1, acc)
            else:
                try:
                    acc.append((depth, reader.get_destination_page_number(it), str(it.title)))
                except Exception:  # noqa: BLE001
                    continue
        return acc

    try:
        entries = walk(reader.outline, 0, [])
    except Exception:  # noqa: BLE001
        return {}
    top = [e for e in entries if e[0] == 0]
    chosen = top if len(top) >= 2 else entries
    pages: dict[int, list[str]] = {}
    for _, page, title in chosen:
        pages.setdefault(page, []).append(title)
    return pages


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    outline = _pdf_outline(reader)
    parts = []
    for n, page in enumerate(reader.pages):
        text = _pdf_page_text(page.extract_text() or "")
        for title in outline.get(n, []):
            # Place le marqueur sur la ligne du titre si on la trouve, sinon en début de page
            key = title.strip().lower()[:40]
            lines = text.split("\n")
            idx = next((i for i, l in enumerate(lines) if key and l.lower().startswith(key)), None)
            if idx is None:
                text = _mark(title) + text
            else:
                lines[idx] = "\n" + _mark(title) + lines[idx]
                text = "\n".join(lines)
        parts.append(text)
    return "\n\n".join(parts)


# --- Autres formats ----------------------------------------------------------

def _docx(data: bytes) -> str:
    import docx

    doc = docx.Document(io.BytesIO(data))
    out = []
    for p in doc.paragraphs:
        style = (p.style.name if p.style is not None else "").lower()
        is_heading = style in ("title", "titre") or re.match(r"(heading|titre)\s*[12]$", style)
        out.append((_mark(p.text) if is_heading and p.text.strip() else "") + p.text)
    return "\n\n".join(out)


def _epub(data: bytes) -> str:
    import ebooklib
    from ebooklib import epub

    # EbookLib lit depuis un chemin : on passe par un fichier temporaire
    # (delete=False : sous Windows, un fichier ouvert ne peut pas être relu par un autre lecteur)
    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
        tmp.write(data)
    try:
        book = epub.read_epub(tmp.name, options={"ignore_ncx": False})
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    # Table des matières : premier titre pour chaque fichier du livre
    toc: dict[str, str] = {}

    def walk(items):
        for it in items:
            if isinstance(it, tuple):  # (Section, [enfants])
                sec, children = it
                if getattr(sec, "href", None):
                    toc.setdefault(sec.href.split("#")[0], sec.title)
                walk(children)
            elif isinstance(it, list):
                walk(it)
            elif getattr(it, "href", None):
                toc.setdefault(it.href.split("#")[0], it.title)

    walk(book.toc)
    use_toc = len(toc) >= 2

    parts = []
    for item_id, _ in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        text = _html_to_text(item.get_content().decode("utf-8", errors="replace"), mark_headings=not use_toc)
        title = toc.get(item.get_name()) if use_toc else None
        if title and re.search(r"\w", text):
            text = _mark(title) + text.lstrip()
        parts.append(text)
    return "\n\n".join(parts)


def _markdown(text: str) -> str:
    import markdown

    return _html_to_text(markdown.markdown(text), mark_headings=True)


def _rtf(text: str) -> str:
    from striprtf.striprtf import rtf_to_text

    return rtf_to_text(text)


# --- Nettoyage ---------------------------------------------------------------

def clean_text(text: str) -> str:
    """Normalise le texte : recolle les mots coupés, fusionne les lignes d'un même paragraphe."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # mots coupés en fin de ligne
    text = re.sub(r"[ \t ]+", " ", text)
    paragraphs = re.split(r"\n\s*\n", text)
    out = []
    for p in paragraphs:
        p = re.sub(r"\s*\n\s*", " ", p).strip()
        if p and re.search(r"\w", p):
            out.append(p)
    return "\n\n".join(out)


def split_markers(text: str) -> tuple[str, list[dict]]:
    """Retire les marqueurs de chapitre ; renvoie le texte et [{title, start}]."""
    paragraphs, chapters = [], []
    pending = None
    for p in text.split("\n\n"):
        titles = re.findall(f"{M_START}([^{M_END}]*){M_END}", p)
        body = re.sub(f"{M_START}[^{M_END}]*{M_END}", "", p).strip()
        if titles and pending is None:
            pending = titles[0]
        if not body or not re.search(r"\w", body):
            continue
        if pending is not None:
            if not chapters or chapters[-1]["start"] != len(paragraphs):
                chapters.append({"title": pending or body[:60], "start": len(paragraphs)})
            pending = None
        paragraphs.append(body)
    return "\n\n".join(paragraphs), chapters


def extract_document(filename: str, data: bytes) -> tuple[str, list[dict]]:
    """Renvoie (texte nettoyé, chapitres trouvés dans la structure du document)."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Format non supporté : {ext or '(aucun)'}")
    if ext == ".pdf":
        raw = _pdf(data)
    elif ext == ".docx":
        raw = _docx(data)
    elif ext == ".epub":
        raw = _epub(data)
    elif ext in (".html", ".htm"):
        raw = _html_to_text(_decode(data), mark_headings=True)
    elif ext in (".md", ".markdown"):
        raw = _markdown(_decode(data))
    elif ext == ".rtf":
        raw = _rtf(_decode(data))
    else:
        raw = _decode(data)
    return split_markers(clean_text(raw))


_FR_WORDS = {"le", "la", "les", "des", "est", "et", "une", "du", "que", "qui", "dans", "pour", "pas", "sur", "avec", "ce", "il", "elle", "nous", "vous", "au", "aux", "mais", "ou"}
_EN_WORDS = {"the", "and", "is", "of", "to", "in", "that", "it", "was", "for", "with", "on", "as", "be", "this", "are", "not", "but", "you", "he", "she", "they", "at", "by"}


def detect_language(text: str) -> str:
    """Détection simple FR/EN par mots fréquents."""
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ]+", text[:20000].lower())
    fr = sum(w in _FR_WORDS for w in words)
    en = sum(w in _EN_WORDS for w in words)
    return "fr" if fr >= en else "en"

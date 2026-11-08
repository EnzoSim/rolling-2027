"""Récupération du texte d'une notice et découpage en pages.

Le texte vient en priorité du dépôt amont sondages-commission-index, qui publie
une extraction pdfplumber sous archives_txt/. Cette génération est récente : pour
les notices plus anciennes, on retombe sur une extraction locale du PDF, avec la
même commande pdfplumber que l'amont pour obtenir le même texte.

Stdlib uniquement, sauf le repli PDF qui importe pdfplumber à la demande.
"""

import re
import ssl
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

PAGE_RE = re.compile(r"^--- page (\d+) ---\s*$")
HEADER_RE = re.compile(r"^#\s?(.*)$")
TIMEOUT = 30
# Toluna et l'IFOP répondent 403 au User-Agent par défaut de Python (relevé du 8 novembre
# 2026) ; un nom honnête, avec l'adresse du dépôt, passe partout.
USER_AGENT = "rolling-2027 (+https://github.com/EnzoSim/rolling-2027)"
# Certificats intermédiaires que certains sites d'instituts oublient d'envoyer. Le serveur de
# l'IFOP envoie l'ancien « GlobalSign RSA OV SSL CA 2018 » au lieu du « GlobalSign GCC R46 OV TLS
# CA 2025 » qui a signé son certificat (relevé du 8 novembre 2026) ; un navigateur va le chercher
# seul, Python non. Celui-ci vient de GlobalSign (secure.globalsign.com/cacert/
# gsgccr46ovtlsca2025.crt, SHA-256 D1:60:E2:DE:…:40:63:F9, valable jusqu'au 23 juin 2029) : il
# complète la chaîne, qui doit toujours remonter à une racine du système (GlobalSign Root R46).
CERTS_DIR = Path(__file__).resolve().parent / "certs"


def ssl_context():
    """Le contexte TLS par défaut, plus les intermédiaires de mining/certs."""
    context = ssl.create_default_context()
    for pem in sorted(CERTS_DIR.glob("*.pem")):
        context.load_verify_locations(cadata=pem.read_text(encoding="ascii"))
    return context


SSL_CONTEXT = ssl_context()


@dataclass(frozen=True)
class Page:
    """Une page de notice, telle que découpée par l'extraction amont."""

    number: int
    lines: tuple

    @property
    def text(self):
        return "\n".join(self.lines)

    def numbered(self):
        """Le texte avec un numéro devant chaque ligne.

        Numéroter les lignes est ce qui permet à un petit modèle de désigner un
        emplacement sans avoir à le recopier.
        """
        return "\n".join(f"[{i}] {line}" for i, line in enumerate(self.lines, 1))


def parse_header(text):
    """Les métadonnées `# clé: valeur` en tête du fichier amont, avant la page 1."""
    header = {}
    for raw in text.splitlines():
        if PAGE_RE.match(raw):
            break
        match = HEADER_RE.match(raw)
        if not match:
            continue
        key, _, value = match.group(1).partition(":")
        if value:
            header[key.strip()] = value.strip()
    return header


def split_pages(text):
    """[Page] découpé sur les séparateurs `--- page N ---`.

    Le texte qui précède la première page (en-tête de métadonnées) est ignoré.
    """
    pages, number, lines = [], None, []
    for raw in text.splitlines():
        match = PAGE_RE.match(raw)
        if match:
            if number is not None:
                pages.append(Page(number, tuple(lines)))
            number, lines = int(match.group(1)), []
            continue
        if number is not None:
            lines.append(raw.rstrip())
    if number is not None:
        pages.append(Page(number, tuple(lines)))
    return pages


def fetch_text(url):
    """Le contenu texte d'une URL brute."""
    with urlopen(url, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8")


def pdf_text_from_url(url):
    """Le texte d'un PDF distant, sans écrire de fichier temporaire."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=TIMEOUT, context=SSL_CONTEXT) as response:
        return extract_pdf_text(BytesIO(response.read()))


def extract_pdf_text(pdf_source):
    """Repli : extraire le texte d'un PDF local, comme le fait le dépôt amont.

    pdfplumber n'est importé qu'ici, et reste une dépendance optionnelle : le
    chemin nominal passe par le TXT amont et n'a rien à installer.
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise SystemExit(
            "❌ --pdf a besoin de pdfplumber, qui est une dépendance optionnelle :\n"
            "     pip install -r requirements_mining.txt\n"
            "   Elle n'est pas nécessaire pour traiter une issue : le texte vient alors du dépôt amont."
        ) from exc

    parts = []
    with pdfplumber.open(pdf_source) as document:
        for number, page in enumerate(document.pages, 1):
            parts.append(f"--- page {number} ---\n" + (page.extract_text(layout=True) or ""))
    return "\n".join(parts)


def blob_to_raw(url, blob_base, raw_base):
    """Convertit un lien GitHub `blob` en lien `raw`.

    check_new_polls.notice_links() renvoie des liens blob, lisibles par un humain
    dans l'issue ; le téléchargement a besoin de la forme raw.
    """
    return url.replace(blob_base, raw_base) if url and url.startswith(blob_base) else url


def strip_empty(pages):
    """Écarte les pages sans aucun contenu : rien à demander à un modèle dessus."""
    return [page for page in pages if page.text.strip()]

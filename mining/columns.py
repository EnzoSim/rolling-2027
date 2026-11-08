"""La vague du jour, jamais son rappel : un contrôle propre aux rapports d'instituts.

Un rapport aligne souvent la vague du jour et la précédente sur la même ligne
(« Jean-Luc Mélenchon 19 17 », colonne « Rappels 19-21 octobre »). La vérification de
l'extraction retrouve chaque part sur sa ligne et chaque tableau fait 100 : elle passerait
aussi avec la colonne du rappel. Ce contrôle exige que la part retenue soit le premier nombre
qui suit le nom du candidat sur sa ligne, la place de la vague du jour dans les rapports
relevés le 8 novembre 2026 (Toluna Harris Interactive, IFOP, Elabe, Cluster17).

Une part qui n'est pas ce premier nombre devient une alerte : la PR reste en brouillon pour
un humain, même quand la fusion automatique des rapports est permise. Une mise en page qui
donnerait le rappel d'abord bloque donc la fusion, elle ne la trompe jamais.
"""

import re
from decimal import Decimal, InvalidOperation

from merge import _norm

NUMBER_RE = re.compile(r"<\s*1(?![\d,.])|(?<![\d.,])\d+(?:[,.]\d+)?")


def first_number_after(source, name):
    """Le premier nombre de la ligne après le nom du candidat, ou None (« <1 » vaut 0,5)."""
    line = _norm(source)
    words = _norm(name).split()
    for needle in (" ".join(words), words[-1] if words else ""):
        if not needle:
            continue
        at = line.rfind(needle)
        if at < 0:
            continue
        match = NUMBER_RE.search(line, at + len(needle))
        if not match:
            return None
        text = match.group(0)
        if text.startswith("<"):
            return Decimal("0.5")
        try:
            return Decimal(text.replace(",", "."))
        except InvalidOperation:
            return None
    return None


def check(proposal):
    """Les alertes d'une proposition tirée d'un rapport, une par part qui n'ouvre pas sa ligne."""
    alerts = []
    for poll_id, evidence in (getattr(proposal, "evidence", None) or {}).items():
        for value in evidence.get("values", []):
            try:
                kept = Decimal(str(value.get("intentions", "")).replace(",", "."))
            except InvalidOperation:
                continue
            first = first_number_after(value.get("source", ""), value.get("candidat", ""))
            if first is None or first != kept:
                alerts.append(
                    f"`{poll_id}` · {value.get('candidat')} : {value.get('intentions')} n'est pas le premier nombre"
                    f" après son nom sur sa ligne du rapport (« {value.get('source')} ») : vague du jour ou rappel ?"
                )
    return alerts

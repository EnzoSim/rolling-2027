"""Garde-fou de la fusion automatique : une part très loin des autres sondages.

Une extraction vérifiée a retrouvé chaque chiffre sur sa ligne de la notice. Cela ne protège
pas d'une notice qui se trompe elle-même : la notice 10318 (OpinionWay pour Les Échos et
Radio Classique, terrain du 13 au 14 octobre 2026) étiquetait mal deux lignes de sa page 13.
Le dépôt a donc publié Le Pen à 4 % et Zemmour à 35 % (#26), corrigés à la main ensuite (#28).

Pour chaque candidat d'un tableau proposé, on prend les autres sondages du même tour,
terminés à 60 jours au plus de lui, qui mesurent ce candidat, en ne gardant que le plus récent
de chaque institut : un institut qui publie souvent ne pèse pas plus que les autres. Au second
tour, seuls les sondages du même duel comptent, puisqu'une part dépend de l'adversaire. Au
premier tour, toutes les listes comptent : 138 listes pour 376 sondages au 8 novembre 2026,
dont 117 testées moins de quatre fois, si bien qu'une règle par liste ne contrôlerait presque
rien. À 3 sondages ou plus, une part à plus de 20 points de leur médiane renvoie la PR en
brouillon : la donnée n'est pas refusée, elle attend un regard humain.

Pourquoi 20 points et pas les 15 de Ballottage (`seriesOutliers` de src/series.js) : Ballottage
compare des sondages d'une même liste, ici on compare des listes différentes. Rejouée sur les
376 sondages du dépôt, la règle trouve au plus 14 points d'écart entre listes (IFOP, 1ᵉʳ au
6 février 2026 : Mélenchon à 25 % quand la gauche n'a presque que lui), et 29 et 31 points
pour l'erreur d'OpinionWay. 20 points laissent de la marge des deux côtés.
"""

import csv
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import median

from merge import _norm

OUTLIER_POINTS = 20
OUTLIER_MIN_POLLS = 3
WINDOW_DAYS = 60
SECOND_ROUND = "2nd Tour"


@dataclass(frozen=True)
class Outlier:
    """Une part d'un tableau proposé, loin de la médiane des autres sondages."""

    poll_id: str
    candidat: str
    value: float
    median: float
    polls: int

    def to_dict(self):
        return asdict(self)


def _day(text):
    try:
        return date.fromisoformat(str(text or "").strip())
    except ValueError:
        return None


def _share(text):
    try:
        return float(str(text or "").strip().replace(",", "."))
    except ValueError:
        return None


def _shares(rows):
    """{nom normalisé: (nom affiché, part)} pour les lignes lisibles d'un tableau."""
    shares = {}
    for row in rows:
        value = _share(row.get("intentions"))
        name = str(row.get("candidat") or "").strip()
        if name and value is not None:
            shares[_norm(name)] = (name, value)
    return shares


def _published(root, skip):
    """Les sondages déjà dans le dépôt, sauf ceux de la proposition (déjà écrits sur disque)."""
    root = Path(root)
    index = root / "polls.csv"
    if not index.is_file():
        return []
    published = []
    with index.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            poll_id = (row.get("poll_id") or "").strip()
            end = _day(row.get("fin_enquete"))
            path = root / "polls" / f"{poll_id}.csv"
            if not poll_id or poll_id in skip or end is None or not path.is_file():
                continue
            with path.open(encoding="utf-8", newline="") as table:
                shares = _shares(csv.DictReader(table))
            published.append(
                {
                    "poll_id": poll_id,
                    "institute": (row.get("nom_institut") or "").strip(),
                    "end": end,
                    "tour": (row.get("tour") or "").strip(),
                    "shares": {key: value for key, (_, value) in shares.items()},
                }
            )
    return published


def _references(published, tour, end, candidate, duel):
    """Le dernier sondage de chaque institut, même tour, à 60 jours, qui mesure ce candidat."""
    latest = {}
    for poll in published:
        if poll["tour"] != tour or candidate not in poll["shares"]:
            continue
        if abs((poll["end"] - end).days) > WINDOW_DAYS:
            continue
        if duel is not None and frozenset(poll["shares"]) != duel:
            continue
        kept = latest.get(poll["institute"])
        if kept is None or (poll["end"], poll["poll_id"]) > (kept["end"], kept["poll_id"]):
            latest[poll["institute"]] = poll
    return [poll["shares"][candidate] for poll in latest.values()]


def find(proposal, root, points=OUTLIER_POINTS, min_polls=OUTLIER_MIN_POLLS):
    """Les parts de la proposition à plus de `points` de la médiane des autres sondages."""
    skip = set(proposal.results)
    published = _published(root, skip)
    if not published:
        return []
    meta = {row.get("poll_id"): row for row in proposal.polls}
    found = []
    for poll_id, rows in proposal.results.items():
        row = meta.get(poll_id) or {}
        end = _day(row.get("fin_enquete") or proposal.methodology.get("end"))
        tour = (row.get("tour") or "").strip()
        if end is None or not tour:
            continue
        shares = _shares(rows)
        duel = frozenset(shares) if tour == SECOND_ROUND else None
        for key, (name, value) in shares.items():
            references = _references(published, tour, end, key, duel)
            if len(references) < min_polls:
                continue
            centre = median(references)
            if abs(value - centre) > points:
                found.append(Outlier(poll_id, name, value, centre, len(references)))
    return found

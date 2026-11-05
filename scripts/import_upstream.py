#!/usr/bin/env python3
"""Reprend de MieuxVoter/presidentielle2027 les seuls sondages que nous n'avons pas.

Un `git merge` de l'amont ne marche plus depuis le 5 novembre 2026 : les deux dépôts
dépouillent chacun les mêmes notices. Mêmes parts, mais pas les mêmes lettres (notre
OpinionWay A est leur D), ni les mêmes marges, ni les mêmes numéros d'hypothèse (IFOP du
27 au 29 octobre : H125 ici, H116 là-bas). Un sondage se reconnaît donc à ce qu'il dit,
jamais à son `poll_id` :

- connu : nous avons un tableau aux mêmes parts, du même institut ou aux mêmes dates ;
- en désaccord : le même institut, les mêmes dates, d'autres parts. Rien n'est repris, nos
  lignes ont été vérifiées contre la notice, et le journal le signale ;
- absent : il est repris, son hypothèse rattachée à la nôtre de même liste, ou créée à la
  suite de nos numéros.

Usage : import_upstream.py <dossier de l'amont> [--root <dépôt>] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from merge import _norm, load_candidates, load_hypotheses  # noqa: E402


@dataclass(frozen=True)
class Table:
    """Une ligne de polls.csv et les parts de son fichier polls/<poll_id>.csv."""

    row: dict
    shares: dict

    @property
    def poll_id(self) -> str:
        return self.row["poll_id"].strip()

    @property
    def institute(self) -> str:
        return _norm(self.row["nom_institut"])

    @property
    def dates(self) -> tuple:
        return (self.row["debut_enquete"].strip(), self.row["fin_enquete"].strip())

    def label(self) -> str:
        return f"{self.poll_id} ({self.row['nom_institut']}, {self.dates[0]} au {self.dates[1]})"


@dataclass
class Plan:
    new: list = field(default_factory=list)
    diverging: list = field(default_factory=list)
    known: int = 0


def read_csv(path: Path) -> list:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_shares(path: Path) -> dict:
    shares = {}
    for row in read_csv(path):
        value = (row.get("intentions") or "").strip()
        if value:
            shares[_norm(row["candidat"])] = float(value)
    return shares


def read_tables(root: Path) -> list:
    return [
        Table(row, read_shares(root / "polls" / f"{row['poll_id'].strip()}.csv"))
        for row in read_csv(root / "polls.csv")
        if row["poll_id"].strip()
    ]


def classify(ours: list, theirs: list) -> Plan:
    plan = Plan()
    for table in theirs:
        same_shares = any(
            mine.shares == table.shares and (mine.institute == table.institute or mine.dates == table.dates)
            for mine in ours
        )
        same_poll = any(mine.institute == table.institute and mine.dates == table.dates for mine in ours)
        if same_shares:
            plan.known += 1
        elif same_poll:
            plan.diverging.append(table)
        else:
            plan.new.append(table)
    return plan


def next_hypothesis_id(existing, their_id: str) -> str:
    """Le numéro suivant les nôtres : ceux de l'amont signifient autre chose ici."""
    prefix = "H2_" if their_id.startswith("H2_") else "H"
    pattern = re.compile(re.escape(prefix) + r"(\d+)")
    numbers = [int(m.group(1)) for m in map(pattern.fullmatch, existing) if m]
    return f"{prefix}{max(numbers, default=0) + 1}"


def append_rows(path: Path, rows: list) -> None:
    if not rows:
        return
    with path.open("r", encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))
    if not path.read_bytes().endswith(b"\n"):
        with path.open("a", encoding="utf-8", newline="") as f:
            f.write("\n")
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore", lineterminator="\n")
        writer.writerows(rows)


def missing_candidates(root: Path, upstream: Path, tables: list, names_of) -> list:
    """Les lignes de candidats.csv de l'amont pour des noms que nous ne connaissons pas."""
    ours, our_names = load_candidates(root / "candidats.csv")
    theirs, their_names = load_candidates(upstream / "candidats.csv")
    rows = {row["candidate_id"].strip(): row for row in read_csv(upstream / "candidats.csv")}
    needed = {}
    for table in tables:
        for name in set(names_of(table)) | set(table.shares):
            their_id = their_names.get(name)
            if name in our_names or their_id is None:
                continue  # Un nom inconnu des deux côtés fera échouer merge.py, et l'alerte partira.
            if their_id in ours:
                raise ValueError(f"Candidat {their_id} : {name} chez l'amont, {ours[their_id].complete_name} ici")
            needed[their_id] = rows[their_id]
    return list(needed.values())


def import_tables(root: Path, upstream: Path, tables: list) -> None:
    our_ids = {table_id.strip() for table_id in (row["poll_id"] for row in read_csv(root / "polls.csv"))}
    our_hypotheses = load_hypotheses(root / "hypotheses.csv")
    by_list = {frozenset(names): hid for hid, names in our_hypotheses.items()}
    their_hypotheses = load_hypotheses(upstream / "hypotheses.csv")
    their_rows = {row["id_hypothese"].strip(): row for row in read_csv(upstream / "hypotheses.csv")}

    def names_of(table):
        their_id = table.row["hypothese"].strip()
        if their_id not in their_hypotheses:
            raise ValueError(f"{table.poll_id} : hypothèse {their_id!r} inconnue de l'amont")
        return their_hypotheses[their_id]

    polls, hypotheses = [], []
    for table in tables:
        if table.poll_id in our_ids:
            raise ValueError(f"{table.poll_id} existe déjà ici pour un autre sondage")
        their_id = table.row["hypothese"].strip()
        names = frozenset(names_of(table))
        if names not in by_list:
            by_list[names] = next_hypothesis_id(set(by_list.values()), their_id)
            hypotheses.append({**their_rows[their_id], "id_hypothese": by_list[names]})
        polls.append({**table.row, "hypothese": by_list[names]})

    candidates = missing_candidates(root, upstream, tables, names_of)
    append_rows(root / "candidats.csv", candidates)
    append_rows(root / "hypotheses.csv", hypotheses)
    append_rows(root / "polls.csv", polls)
    for table in tables:
        shutil.copyfile(upstream / "polls" / f"{table.poll_id}.csv", root / "polls" / f"{table.poll_id}.csv")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("upstream", type=Path, help="un clone de MieuxVoter/presidentielle2027")
    parser.add_argument("--root", type=Path, default=ROOT, help="le dépôt à compléter")
    parser.add_argument("--dry-run", action="store_true", help="dire ce qui serait repris, sans rien écrire")
    args = parser.parse_args(argv)

    plan = classify(read_tables(args.root), read_tables(args.upstream))
    print(f"Tableaux de l'amont : {plan.known} connus, {len(plan.diverging)} en désaccord, {len(plan.new)} absents.")
    for table in plan.new:
        print(f"Absent : {table.label()}")
    for table in plan.diverging:
        print(f"::warning::Parts différentes de l'amont, gardées telles quelles : {table.label()}")

    changed = bool(plan.new) and not args.dry_run
    if changed:
        import_tables(args.root, args.upstream, plan.new)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

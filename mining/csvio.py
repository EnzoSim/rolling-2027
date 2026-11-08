"""Écriture append-only des propositions de sondage.

Ce module ne régénère jamais un CSV complet : les lignes existantes conservent
leurs octets. C'est important pour les revues de PR et évite qu'un bot reformate
des années de données à l'occasion d'un seul ajout.

Seule exception, bornée : une notice qui arrive après le rapport de l'institut écrit
son nom dans la cellule `filename` des lignes du même sondage (`attach_notice`) ;
aucun autre octet de polls.csv ne bouge.
"""

import csv
import io
from pathlib import Path

from merge import _norm
from mining.proposal import Proposal, ProposalError, awaits_notice

POLL_FIELDS = [
    "poll_id",
    "hypothese",
    "nom_institut",
    "commanditaire",
    "debut_enquete",
    "fin_enquete",
    "echantillon",
    "population",
    "rolling",
    "media",
    "tour",
    "sous_echantillon1",
    "sous_population1",
    "sous_echantillon2",
    "sous_population2",
    "sous_echantillon3",
    "sous_population3",
    "filename",
]
CANDIDATE_FIELDS = [
    "candidate_id",
    "complete_name",
    "name",
    "surname",
    "parti",
    "annonce_candidature",
    "retrait_candidature",
    "second_round",
]
HYPOTHESIS_FIELDS = ["id_hypothese", "hypothese_complete", "commentaire"]
RESULT_FIELDS = ["candidat", "intentions", "erreur_sup", "erreur_inf"]


def _header(path):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        return next(reader, [])


def append_rows(path, rows):
    """Ajoute `rows` à la fin de `path`, après contrôle strict de son en-tête."""
    rows = list(rows)
    if not rows:
        return
    path = Path(path)
    fields = _header(path)
    if not fields:
        raise ProposalError(f"{path} n'a pas d'en-tête CSV")
    unexpected = set().union(*(set(row) for row in rows)) - set(fields)
    missing = [field for field in fields if any(field not in row for row in rows)]
    if unexpected or missing:
        raise ProposalError(f"colonnes incompatibles pour {path.name}: inconnues={unexpected}, absentes={missing}")
    # Certains vieux CSV n'auraient pas de LF final : l'ajouter est le seul octet
    # existant qu'il soit légitime de modifier pour ne pas fusionner deux lignes.
    needs_newline = path.stat().st_size and not path.read_bytes().endswith(b"\n")
    with path.open("a", encoding="utf-8", newline="") as handle:
        if needs_newline:
            handle.write("\n")
        writer = csv.DictWriter(handle, fieldnames=fields, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        writer.writerows(rows)


def _line(fields, row):
    buffer = io.StringIO()
    csv.DictWriter(buffer, fieldnames=fields, quoting=csv.QUOTE_MINIMAL, lineterminator="\n").writerow(row)
    return buffer.getvalue()


def attach_notice(path, poll_ids, filename):
    """Écrit `filename` dans la cellule `filename` des lignes `poll_ids`, et rien d'autre.

    Chaque ligne visée doit se réécrire à l'identique avant le changement : sinon (guillemets
    inhabituels, ligne sur plusieurs lignes physiques) on refuse plutôt que de reformater.
    """
    path = Path(path)
    targets = set(poll_ids)
    if not targets:
        return
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    fields = next(csv.reader([lines[0]]))
    if "filename" not in fields or "poll_id" not in fields:
        raise ProposalError(f"{path.name} n'a pas les colonnes poll_id et filename")
    done = set()
    for index, physical in enumerate(lines[1:], 1):
        records = list(csv.reader([physical]))
        if len(records) != 1:
            continue
        row = dict(zip(fields, records[0]))
        if row.get("poll_id") not in targets:
            continue
        ending = "\n" if physical.endswith("\n") else ""
        if _line(fields, row) != physical.rstrip("\r\n") + "\n":
            raise ProposalError(f"la ligne {row['poll_id']} ne se réécrit pas à l'identique : rien n'est changé")
        row["filename"] = filename
        lines[index] = _line(fields, row)[:-1] + ending
        done.add(row["poll_id"])
    if done != targets:
        raise ProposalError(f"lignes introuvables dans {path.name} : {', '.join(sorted(targets - done))}")
    path.write_text("".join(lines), encoding="utf-8", newline="")


def _named_rows(path, field):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle)), field


def validate(proposal, root):
    """Vérifie toutes les collisions avant le premier append."""
    if not isinstance(proposal, Proposal):
        proposal = Proposal(**proposal)
    root = Path(root)
    expected = {
        root / "polls.csv": POLL_FIELDS,
        root / "candidats.csv": CANDIDATE_FIELDS,
        root / "hypotheses.csv": HYPOTHESIS_FIELDS,
    }
    for path, fields in expected.items():
        if _header(path) != fields:
            raise ProposalError(f"en-tête inattendu dans {path.name}")

    poll_rows, _ = _named_rows(root / "polls.csv", "poll_id")
    candidate_rows, _ = _named_rows(root / "candidats.csv", "candidate_id")
    hypothesis_rows, _ = _named_rows(root / "hypotheses.csv", "id_hypothese")
    existing_polls = {row["poll_id"] for row in poll_rows}
    existing_candidates = {row["candidate_id"] for row in candidate_rows}
    existing_names = {_norm(row["complete_name"]) for row in candidate_rows}
    existing_hypotheses = {row["id_hypothese"] for row in hypothesis_rows}

    poll_ids = [row.get("poll_id") for row in proposal.polls]
    if len(poll_ids) != len(set(poll_ids)) or set(poll_ids) & existing_polls:
        raise ProposalError("un poll_id de la proposition existe déjà")
    by_id = {row["poll_id"]: row for row in poll_rows}
    attached = [item.get("poll_id") for item in proposal.attachments]
    if len(attached) != len(set(attached)) or set(attached) & set(poll_ids):
        raise ProposalError("une ligne est rattachée deux fois à la notice")
    for poll_id in attached:
        row = by_id.get(poll_id)
        if row is None:
            raise ProposalError(f"ligne à rattacher introuvable : {poll_id}")
        if not awaits_notice(row):
            raise ProposalError(f"{poll_id} a déjà sa notice ({row['filename']})")
    if set(proposal.results) != set(poll_ids):
        raise ProposalError("chaque ligne polls.csv doit avoir exactement un fichier de résultats")
    for poll_id in poll_ids:
        if (root / "polls" / f"{poll_id}.csv").exists():
            raise ProposalError(f"le fichier polls/{poll_id}.csv existe déjà")
        rows = proposal.results[poll_id]
        if not rows or any(set(row) != set(RESULT_FIELDS) for row in rows):
            raise ProposalError(f"résultats invalides pour {poll_id}")

    candidate_ids = [row.get("candidate_id") for row in proposal.candidates]
    candidate_names = [_norm(row.get("complete_name", "")) for row in proposal.candidates]
    if len(candidate_ids) != len(set(candidate_ids)) or set(candidate_ids) & existing_candidates:
        raise ProposalError("un candidate_id de la proposition existe déjà")
    if (
        not all(candidate_names)
        or len(candidate_names) != len(set(candidate_names))
        or set(candidate_names) & existing_names
    ):
        raise ProposalError("un candidat de la proposition existe déjà ou est vide")
    if any(set(row) != set(CANDIDATE_FIELDS) for row in proposal.candidates):
        raise ProposalError("colonnes candidat invalides")

    hypothesis_ids = [row.get("id_hypothese") for row in proposal.hypotheses]
    if len(hypothesis_ids) != len(set(hypothesis_ids)) or set(hypothesis_ids) & existing_hypotheses:
        raise ProposalError("un id_hypothese de la proposition existe déjà")
    if any(set(row) != set(HYPOTHESIS_FIELDS) for row in proposal.hypotheses):
        raise ProposalError("colonnes hypothèse invalides")

    hypotheses = {row["id_hypothese"]: row["hypothese_complete"] for row in hypothesis_rows + proposal.hypotheses}
    for metadata in proposal.polls:
        if set(metadata) != set(POLL_FIELDS):
            raise ProposalError(f"colonnes metadata invalides pour {metadata.get('poll_id')}")
        expected_names = {_norm(name) for name in hypotheses.get(metadata["hypothese"], "").split(",") if name.strip()}
        result_names = {_norm(row["candidat"]) for row in proposal.results[metadata["poll_id"]]}
        if not expected_names or expected_names != result_names:
            raise ProposalError(f"candidats et hypothèse incohérents pour {metadata['poll_id']}")
    return proposal


def apply(proposal, root):
    """Valide puis ajoute les lignes et les nouveaux fichiers de résultats."""
    proposal = validate(proposal, root)
    root = Path(root)
    append_rows(root / "candidats.csv", proposal.candidates)
    append_rows(root / "hypotheses.csv", proposal.hypotheses)
    append_rows(root / "polls.csv", proposal.polls)
    attach_notice(root / "polls.csv", [item["poll_id"] for item in proposal.attachments], proposal.filename)
    for poll_id, rows in proposal.results.items():
        with (root / "polls" / f"{poll_id}.csv").open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    return proposal


def summary(proposal):
    text = (
        f"{len(proposal.polls)} sondage(s), {len(proposal.hypotheses)} hypothèse(s) nouvelle(s), "
        f"{len(proposal.candidates)} candidat(s) nouveau(x)"
    )
    if proposal.attachments:
        text += f", notice rattachée à {len(proposal.attachments)} sondage(s) déjà relevé(s)"
    return text

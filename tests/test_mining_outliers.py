"""Garde-fou de la fusion automatique : une part très loin des autres sondages."""

import csv
import subprocess
from pathlib import Path

from mining import outliers
from mining.proposal import Proposal

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ["poll_id", "hypothese", "nom_institut", "fin_enquete", "tour"]


def _repo(tmp_path, polls):
    """Un dépôt minimal : polls.csv et un fichier de résultats par sondage."""
    (tmp_path / "polls").mkdir()
    with (tmp_path / "polls.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for poll_id, institute, end, tour, shares in polls:
            writer.writerow(
                {"poll_id": poll_id, "hypothese": "H1", "nom_institut": institute, "fin_enquete": end, "tour": tour}
            )
            with (tmp_path / "polls" / f"{poll_id}.csv").open("w", encoding="utf-8", newline="") as table:
                rows = csv.writer(table)
                rows.writerow(["candidat", "intentions", "erreur_sup", "erreur_inf"])
                for name, value in shares.items():
                    rows.writerow([name, value, "", ""])
    return tmp_path


def _proposal(shares, end="2026-10-14", tour="1er Tour", poll_id="20261013_1014_ow_B"):
    return Proposal(
        filename="notice.pdf",
        methodology={"end": end},
        polls=[{"poll_id": poll_id, "hypothese": "H67", "fin_enquete": end, "tour": tour}],
        results={poll_id: [{"candidat": name, "intentions": str(value)} for name, value in shares.items()]},
    )


FOUR_INSTITUTES = [
    ("20261012_1014_if_A", "IFOP", "2026-10-14", "1er Tour", {"Marine Le Pen": 33, "Éric Zemmour": 5}),
    ("20261010_1011_el_A", "Elabe", "2026-10-11", "1er Tour", {"Marine Le Pen": 35, "Éric Zemmour": 4}),
    ("20261001_1002_hi_A", "Harris Interactive", "2026-10-02", "1er Tour", {"Marine Le Pen": 34, "Éric Zemmour": 5}),
    ("20260920_0921_cl_A", "Cluster17", "2026-09-21", "1er Tour", {"Marine Le Pen": 36, "Éric Zemmour": 4}),
]


def test_deux_lignes_interverties_sont_signalees(tmp_path):
    root = _repo(tmp_path, FOUR_INSTITUTES)
    found = outliers.find(_proposal({"Marine Le Pen": 4, "Éric Zemmour": 35}), root)
    assert [(item.candidat, item.value, item.median, item.polls) for item in found] == [
        ("Marine Le Pen", 4.0, 34.5, 4),
        ("Éric Zemmour", 35.0, 4.5, 4),
    ]


def test_un_sondage_ordinaire_passe(tmp_path):
    root = _repo(tmp_path, FOUR_INSTITUTES)
    assert outliers.find(_proposal({"Marine Le Pen": 31, "Éric Zemmour": 6}), root) == []


def test_un_ecart_de_vingt_points_ne_suffit_pas(tmp_path):
    root = _repo(tmp_path, FOUR_INSTITUTES)
    assert outliers.find(_proposal({"Marine Le Pen": 14.5}), root) == []
    assert [item.candidat for item in outliers.find(_proposal({"Marine Le Pen": 14}), root)] == ["Marine Le Pen"]


def test_moins_de_trois_sondages_ne_disent_rien(tmp_path):
    root = _repo(tmp_path, FOUR_INSTITUTES[:2])
    assert outliers.find(_proposal({"Marine Le Pen": 4}), root) == []


def test_un_institut_ne_compte_qu_une_fois(tmp_path):
    same = [
        (f"2026101{day}_101{day}_ow_A", "OpinionWay", f"2026-10-1{day}", "1er Tour", {"Marine Le Pen": 34})
        for day in range(4)
    ]
    root = _repo(tmp_path, same)
    assert outliers.find(_proposal({"Marine Le Pen": 4}), root) == []


def test_un_sondage_a_plus_de_soixante_jours_ne_compte_pas(tmp_path):
    old = [(poll_id, institute, "2026-07-01", tour, shares) for poll_id, institute, _, tour, shares in FOUR_INSTITUTES]
    root = _repo(tmp_path, old)
    assert outliers.find(_proposal({"Marine Le Pen": 4}), root) == []


def test_au_second_tour_seul_le_meme_duel_compte(tmp_path):
    duels = [
        ("20261012_1014_if_2A", "IFOP", "2026-10-14", "2nd Tour", {"Marine Le Pen": 70, "Jean-Luc Mélenchon": 30}),
        ("20261010_1011_el_2A", "Elabe", "2026-10-11", "2nd Tour", {"Marine Le Pen": 71, "Jean-Luc Mélenchon": 29}),
        (
            "20261001_1002_hi_2A",
            "Harris Interactive",
            "2026-10-02",
            "2nd Tour",
            {"Marine Le Pen": 69, "Jean-Luc Mélenchon": 31},
        ),
    ]
    root = _repo(tmp_path, duels)
    # Le Pen contre Philippe se joue à 50 : les duels contre Mélenchon ne disent rien de lui.
    assert outliers.find(_proposal({"Marine Le Pen": 48, "Édouard Philippe": 52}, tour="2nd Tour"), root) == []
    flipped = outliers.find(_proposal({"Marine Le Pen": 30, "Jean-Luc Mélenchon": 70}, tour="2nd Tour"), root)
    assert [item.candidat for item in flipped] == ["Marine Le Pen", "Jean-Luc Mélenchon"]


def test_les_tableaux_de_la_proposition_ne_se_comparent_pas_a_eux_memes(tmp_path):
    # Les fichiers de la proposition sont déjà écrits quand create_or_update l'examine.
    bad = ("20261013_1014_ow_B", "OpinionWay", "2026-10-14", "1er Tour", {"Marine Le Pen": 4, "Éric Zemmour": 35})
    root = _repo(tmp_path, [*FOUR_INSTITUTES[:2], bad])
    assert outliers.find(_proposal({"Marine Le Pen": 4, "Éric Zemmour": 35}), root) == []


def test_sans_donnees_publiees_rien_n_est_signale(tmp_path):
    assert outliers.find(_proposal({"Marine Le Pen": 4}), tmp_path) == []


def test_la_notice_10318_d_opinionway_aurait_ete_arretee():
    """L'erreur réelle (#26, corrigée par #28), rejouée sur les données du dépôt."""
    bad = subprocess.run(
        ["git", "show", "f0c49d7:polls/20261013_1014_ow_B.csv"], cwd=ROOT, capture_output=True, text=True
    )
    if bad.returncode != 0:  # clone superficiel : l'ancienne version n'est pas là
        rows = [{"candidat": "Marine Le Pen", "intentions": "4"}, {"candidat": "Éric Zemmour", "intentions": "35"}]
    else:
        rows = list(csv.DictReader(bad.stdout.splitlines()))
    proposal = _proposal({})
    proposal.results = {"20261013_1014_ow_B": rows}
    found = outliers.find(proposal, ROOT)
    assert {item.candidat for item in found} == {"Marine Le Pen", "Éric Zemmour"}

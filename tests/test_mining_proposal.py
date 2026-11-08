"""Assemblage et écriture append-only d'une proposition validée."""

import shutil
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import pytest

from mining import csvio, extraction, proposal

ROOT = Path(__file__).resolve().parents[1]


def _methodology():
    return extraction.Methodology(
        "OpinionWay",
        "CNews",
        "2099-09-09",
        "2099-09-10",
        1001,
        935,
        "représentatif de la population française âgée de 18 ans et plus",
        "source dates",
        "source sample",
    )


def _table():
    return extraction.ExtractedTable(
        2,
        "2nd Tour",
        (("certains d'aller voter", 690),),
        (
            extraction.CandidateValue("Édouard Philippe", Decimal("50"), "Édouard Philippe 50"),
            extraction.CandidateValue("Marine Le Pen", Decimal("50"), "Marine Le Pen 50"),
        ),
    )


def _copy_data(tmp_path):
    for name in ("candidats.csv", "hypotheses.csv", "polls.csv"):
        shutil.copy(ROOT / name, tmp_path / name)
    shutil.copytree(ROOT / "polls", tmp_path / "polls")


def test_build_reutilise_l_hypothese_existante_et_le_code_institut(tmp_path):
    _copy_data(tmp_path)
    built = proposal.build("future.pdf", _methodology(), [_table()], tmp_path)
    assert built.polls[0]["hypothese"] == "H2_2"
    assert built.polls[0]["poll_id"] == "20990909_0910_ow_2A"
    assert built.hypotheses == [] and built.candidates == []


def test_apply_ajoute_sans_reformater_les_octets_existants(tmp_path):
    _copy_data(tmp_path)
    original = (tmp_path / "polls.csv").read_bytes()
    built = proposal.build("future.pdf", _methodology(), [_table()], tmp_path)
    csvio.apply(built, tmp_path)
    updated = (tmp_path / "polls.csv").read_bytes()
    assert updated.startswith(original)
    assert (tmp_path / "polls" / "20990909_0910_ow_2A.csv").exists()
    assert "Édouard Philippe,50,," in (tmp_path / "polls" / "20990909_0910_ow_2A.csv").read_text(encoding="utf-8")


def _second_tour(page, left, right):
    return extraction.ExtractedTable(
        page,
        "2nd Tour",
        (),
        (
            extraction.CandidateValue(left, Decimal("40"), f"{left} 40"),
            extraction.CandidateValue(right, Decimal("60"), f"{right} 60"),
        ),
    )


def test_une_proposition_incomplete_garde_ses_tableaux_et_liste_les_manques(tmp_path):
    # Cas réel, issue #194 : quota épuisé à la page 40, deux tableaux déjà vérifiés.
    _copy_data(tmp_path)
    built = proposal.build("future.pdf", _methodology(), [_table()], tmp_path, missing=["page 40 : quota épuisé"])
    assert [poll["poll_id"] for poll in built.polls] == ["20990909_0910_ow_2A"]
    assert built.missing == ["page 40 : quota épuisé"]


def test_une_relance_complete_sans_dupliquer_les_tableaux_deja_enregistres(tmp_path):
    _copy_data(tmp_path)
    csvio.apply(proposal.build("future.pdf", _methodology(), [_table()], tmp_path), tmp_path)
    melenchon = _second_tour(5, "Jean-Luc Mélenchon", "Marine Le Pen")
    built = proposal.build("future.pdf", _methodology(), [_table(), melenchon], tmp_path)
    # Le tableau déjà fusionné n'est pas reproposé ; le nouveau prend la lettre libre suivante.
    assert [(poll["poll_id"], poll["hypothese"]) for poll in built.polls] == [("20990909_0910_ow_2B", "H2_9")]
    assert built.already_present == ["page 2 : H2_2 déjà enregistrée pour future.pdf"]
    csvio.apply(built, tmp_path)


def test_une_notice_entierement_enregistree_ne_propose_rien(tmp_path):
    _copy_data(tmp_path)
    csvio.apply(proposal.build("future.pdf", _methodology(), [_table()], tmp_path), tmp_path)
    with pytest.raises(proposal.ProposalError, match="déjà enregistrés"):
        proposal.build("future.pdf", _methodology(), [_table()], tmp_path)


# Une notice qui arrive après le rapport de l'institut (8 novembre 2026) : le Harris du 3 au
# 5 novembre a été relevé depuis le rapport de Toluna avant que sa notice soit en ligne. La
# notice doit se rattacher à ces lignes, jamais les ajouter une seconde fois.

REPORT = "Rapport-OpinionWay-CNews-2099.pdf"
NOTICE = "10999-pres-iv-opinionway-cnews-11-septembre.pdf"


def test_un_nom_de_notice_se_reconnait_sous_toutes_ses_formes():
    for name in ("10351-pres-iv-ifop-lci-3-novembre.pdf", "10166a-pres-iv-opinionway.pdf", "9942-p-toluna-hi-lci.pdf"):
        assert not proposal.awaits_notice({"filename": name})
    for name in (
        "",
        "Rapport-Toluna-Barometre-Vague-9.pdf",
        "barometre-odoxa-mascaret-mars-2026.pdf",
        "122860-ifop.pdf",
    ):
        assert proposal.awaits_notice({"filename": name})


def test_la_notice_se_rattache_aux_lignes_relevees_depuis_le_rapport(tmp_path):
    _copy_data(tmp_path)
    melenchon = _second_tour(5, "Jean-Luc Mélenchon", "Marine Le Pen")
    csvio.apply(proposal.build(REPORT, _methodology(), [_table(), melenchon], tmp_path), tmp_path)
    before = (tmp_path / "polls.csv").read_text(encoding="utf-8").splitlines(keepends=True)

    built = proposal.build(NOTICE, _methodology(), [_table(), melenchon], tmp_path)
    assert built.polls == [] and built.results == {}
    assert [(item["poll_id"], item["previous"]) for item in built.attachments] == [
        ("20990909_0910_ow_2A", REPORT),
        ("20990909_0910_ow_2B", REPORT),
    ]
    assert built.failures == []
    csvio.apply(built, tmp_path)

    after = (tmp_path / "polls.csv").read_text(encoding="utf-8").splitlines(keepends=True)
    assert len(after) == len(before), "aucune ligne ajoutée"
    changed = [(old, new) for old, new in zip(before, after) if old != new]
    assert [new.split(",", 1)[0] for _, new in changed] == ["20990909_0910_ow_2A", "20990909_0910_ow_2B"]
    for old, new in changed:
        assert old.replace(REPORT, NOTICE) == new, "seule la cellule filename change"
    assert not (tmp_path / "polls" / "20990909_0910_ow_2C.csv").exists()
    # Relancée, la notice est désormais « déjà enregistrée » : rien n'est reproposé.
    with pytest.raises(proposal.ProposalError, match="déjà enregistrés"):
        proposal.build(NOTICE, _methodology(), [_table(), melenchon], tmp_path)


def test_une_ligne_sans_fichier_attend_aussi_sa_notice(tmp_path):
    _copy_data(tmp_path)
    csvio.apply(proposal.build("", _methodology(), [_table()], tmp_path), tmp_path)
    built = proposal.build(NOTICE, _methodology(), [_table()], tmp_path)
    assert [item["poll_id"] for item in built.attachments] == ["20990909_0910_ow_2A"]
    csvio.apply(built, tmp_path)
    line = next(
        row for row in (tmp_path / "polls.csv").read_text(encoding="utf-8").splitlines() if row.startswith("20990909_")
    )
    assert line.endswith("," + NOTICE)


def test_la_notice_ajoute_ses_hypotheses_nouvelles_et_rattache_les_autres(tmp_path):
    _copy_data(tmp_path)
    csvio.apply(proposal.build(REPORT, _methodology(), [_table()], tmp_path), tmp_path)
    melenchon = _second_tour(5, "Jean-Luc Mélenchon", "Marine Le Pen")
    built = proposal.build(NOTICE, _methodology(), [_table(), melenchon], tmp_path)
    assert [item["poll_id"] for item in built.attachments] == ["20990909_0910_ow_2A"]
    assert [(poll["poll_id"], poll["filename"]) for poll in built.polls] == [("20990909_0910_ow_2B", NOTICE)]
    csvio.apply(built, tmp_path)


def test_d_autres_chiffres_pour_le_meme_sondage_ne_s_ecrivent_pas(tmp_path):
    _copy_data(tmp_path)
    csvio.apply(proposal.build(REPORT, _methodology(), [_table()], tmp_path), tmp_path)
    original = (tmp_path / "polls.csv").read_bytes()
    other = extraction.ExtractedTable(
        2,
        "2nd Tour",
        (),
        (
            extraction.CandidateValue("Édouard Philippe", Decimal("51"), "Édouard Philippe 51"),
            extraction.CandidateValue("Marine Le Pen", Decimal("49"), "Marine Le Pen 49"),
        ),
    )
    with pytest.raises(proposal.ProposalError, match="d'autres chiffres"):
        proposal.build(NOTICE, _methodology(), [other], tmp_path)
    assert (tmp_path / "polls.csv").read_bytes() == original


def test_une_ligne_qui_a_deja_sa_notice_ne_se_rattache_pas(tmp_path):
    _copy_data(tmp_path)
    csvio.apply(proposal.build(NOTICE, _methodology(), [_table()], tmp_path), tmp_path)
    built = proposal.build("10998-pres-iv-opinionway-autre.pdf", _methodology(), [_table()], tmp_path)
    assert built.attachments == [], "une notice ne remplace jamais une autre notice"
    forged = proposal.Proposal(NOTICE, asdict(_methodology()), attachments=[{"poll_id": "20990909_0910_ow_2A"}])
    with pytest.raises(proposal.ProposalError, match="a déjà sa notice"):
        csvio.validate(forged, tmp_path)


def test_un_rapport_arrive_apres_sa_notice_n_ajoute_rien(tmp_path):
    _copy_data(tmp_path)
    melenchon = _second_tour(5, "Jean-Luc Mélenchon", "Marine Le Pen")
    csvio.apply(proposal.build(NOTICE, _methodology(), [_table()], tmp_path), tmp_path)
    original = (tmp_path / "polls.csv").read_bytes()
    built = proposal.build(REPORT, _methodology(), [_table(), melenchon], tmp_path)
    # Le tableau de la notice n'est ni ajouté ni rattaché au rapport ; celui que le rapport
    # est seul à donner s'ajoute, sous le nom du rapport.
    assert built.attachments == []
    assert built.already_present == [f"page 2 : H2_2 déjà enregistrée (20990909_0910_ow_2A, {NOTICE})"]
    assert [(poll["poll_id"], poll["filename"]) for poll in built.polls] == [("20990909_0910_ow_2B", REPORT)]
    with pytest.raises(proposal.ProposalError, match="déjà enregistrés"):
        proposal.build(REPORT, _methodology(), [_table()], tmp_path)
    assert (tmp_path / "polls.csv").read_bytes() == original

"""rolling-2027 : le dépouillement manuel (bot ou humain) passe par les validateurs du dépôt."""

from pathlib import Path

import pytest

import submit_extraction as se

NOTICE = (Path(__file__).parent / "fixtures" / "notices" / "10314-ifop-lci-14-octobre.txt").read_text(encoding="utf-8")
FILENAME = "10314-pres-climat-politique-post-primaire-ps-pp-ifop-lci-14-octobre.pdf"

METHODOLOGY = """/extraction
INSTITUT: IFOP
COMMANDITAIRE: LCI, Sud Radio
DEBUT: 2026-10-12
FIN: 2026-10-14
ECHANTILLON: 1525
INSCRITS: 1390
POPULATION: représentatif de la population française âgée de 18 ans et plus
SOURCE_DATES: en ligne du 12 au 14 octobre 2026.
SOURCE_ECHANTILLON: extrait d’un échantillon de 1 525
SOURCE_INSCRITS: L’enquête a été menée auprès d’un échantillon de 1 390 personnes
"""

PAGE_9 = """
PAGE 9
TABLEAU
TOUR: 1er Tour
EFFECTIFS: exprimé une intention de vote = 1050 | certains d'aller voter = 832
Nathalie Arthaud | - | Nathalie Arthaud -
Jean-Luc Mélenchon | 16 | Jean-Luc Mélenchon 16,0
Fabien Roussel | 2.5 | Fabien Roussel  2,5
Marine Tondelier | 2 | Marine Tondelier 2,0
Raphaël Glucksmann | 14 | Raphaël Glucksmann 14,0
Gabriel Attal | 6 | Gabriel Attal   6,0
Édouard Philippe | 14 | Edouard Philippe 14,0
Bruno Retailleau | 6.5 | Bruno Retailleau 6,5
Nicolas Dupont-Aignan | 2 | Nicolas Dupont-Aignan 2,0
Marine Le Pen | 34 | Marine Le Pen   34,0
Éric Zemmour | 3 | Éric Zemmour    3,0
FIN
"""


def test_un_depouillement_juste_passe_tous_les_controles():
    proposal, report = se.verify(METHODOLOGY + PAGE_9, "essai-bot.pdf", NOTICE)
    assert report is None
    assert len(proposal.polls) == 1
    poll = proposal.polls[0]
    assert poll["nom_institut"] == "IFOP" and poll["hypothese"] == "H67"
    assert poll["commanditaire"] == "LCI, Sud Radio" and poll["echantillon"] == 1525
    rows = {row["candidat"]: row["intentions"] for row in proposal.results[poll["poll_id"]]}
    assert rows["Marine Le Pen"] == "34" and rows["Nathalie Arthaud"] == "0" and rows["Fabien Roussel"] == "2.5"


def test_une_notice_deja_depouillee_est_refusee():
    with pytest.raises(se.SubmissionError, match="déjà enregistr"):
        se.verify(METHODOLOGY + PAGE_9, FILENAME, NOTICE)


def test_un_chiffre_faux_est_refuse():
    faux = PAGE_9.replace("Marine Le Pen | 34 |", "Marine Le Pen | 33 |")
    with pytest.raises(se.SubmissionError, match="Le Pen"):
        se.verify(METHODOLOGY + faux, "essai-bot.pdf", NOTICE)


def test_un_tiret_sur_une_ligne_chiffree_est_refuse():
    faux = PAGE_9.replace("Fabien Roussel | 2.5 | Fabien Roussel  2,5", "Fabien Roussel | - | Fabien Roussel  2,5")
    with pytest.raises(se.SubmissionError):
        se.verify(METHODOLOGY + faux, "essai-bot.pdf", NOTICE)


def test_une_date_qui_ne_se_justifie_pas_est_refusee():
    faux = METHODOLOGY.replace("DEBUT: 2026-10-12", "DEBUT: 2026-10-11")
    with pytest.raises(se.SubmissionError, match="méthodologie"):
        se.verify(faux + PAGE_9, "essai-bot.pdf", NOTICE)


def test_sans_page_rien_a_verifier():
    with pytest.raises(se.SubmissionError, match="PAGE"):
        se.verify(METHODOLOGY, "essai-bot.pdf", NOTICE)


def test_le_rapport_vient_du_site_d_un_institut():
    with pytest.raises(se.SubmissionError, match="RAPPORT"):
        se.report_text("https://exemple.test/rapport.pdf")
    with pytest.raises(se.SubmissionError, match="RAPPORT"):
        se.report_text("http://www.odoxa.fr/rapport.pdf")


def test_le_commentaire_garde_son_texte_sans_commande_ni_cloture():
    body = "/extraction\n```\nINSTITUT: IFOP\n```\n"
    assert se.strip_command(body) == "INSTITUT: IFOP"


def test_la_base_des_inscrits_dans_effectifs_est_ignoree():
    """Cas réel, issue #17 : le bot avait recopié « inscrits … = 978 » dans EFFECTIFS."""
    avec = PAGE_9.replace(
        "EFFECTIFS: exprimé une intention de vote = 1050",
        "EFFECTIFS: inscrits sur les listes électorales = 1390 | exprimé une intention de vote = 1050",
    )
    proposal, _ = se.verify(METHODOLOGY + avec, "essai-bot.pdf", NOTICE)
    assert proposal.polls[0]["sous_echantillon1"] == 1390

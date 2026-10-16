"""rolling-2027 : le dépouillement manuel (bot ou humain) passe par les validateurs du dépôt."""

from pathlib import Path
from types import SimpleNamespace

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


ISSUE_URL = "https://api.github.com/repos/EnzoSim/rolling-2027/issues/17"


def _publier(monkeypatch, tmp_path, post, created=None, failure=None):
    """main() avec --pr, la PR simulée (ouverte, fusionnée ou en panne) ; rend les appels à l'API."""
    calls = []
    monkeypatch.setattr(
        se, "_github_request", lambda url, token, method="GET", payload=None: calls.append((url, method, payload))
    )
    monkeypatch.setattr(se, "issue_poll_filename", lambda *args: "essai-bot.pdf")
    monkeypatch.setattr(se.pull_request, "prepare_branch", lambda *args: None)
    monkeypatch.setattr(se.csvio, "apply", lambda *args: None)

    def create_or_update(*args, **kwargs):
        if failure:
            raise failure
        return created

    monkeypatch.setattr(se.pull_request, "create_or_update", create_or_update)
    monkeypatch.setenv("GITHUB_REPOSITORY", "EnzoSim/rolling-2027")
    depouillement = tmp_path / "extraction.txt"
    depouillement.write_text(METHODOLOGY + PAGE_9, encoding="utf-8")
    notice_txt = tmp_path / "notice.txt"
    notice_txt.write_text(NOTICE, encoding="utf-8")
    argv = ["--issue", "17", "--input", str(depouillement), "--notice-txt", str(notice_txt), "--pr"]
    code = se.main(argv + (["--post"] if post else []))
    return code, calls


def _pr(merged):
    return se.pull_request.PullRequest(
        22, "https://github.com/EnzoSim/rolling-2027/pull/22", "mining/issue-17", merged=merged
    )


def test_une_notice_publiee_ferme_son_issue(monkeypatch, tmp_path):
    """Cas réel, issue #17 : « Closes #17 » n'a rien fermé, la fusion étant faite avec GITHUB_TOKEN."""
    code, calls = _publier(monkeypatch, tmp_path, post=True, created=_pr(merged=True))
    assert code == 0
    assert [(url, method) for url, method, _ in calls] == [
        (f"{ISSUE_URL}/comments", "POST"),
        (f"{ISSUE_URL}/labels", "POST"),
        (ISSUE_URL, "PATCH"),
    ]
    assert "fusionnée" in calls[0][2]["body"]
    assert calls[1][2] == {"labels": ["avec-intentions-de-vote"]}
    assert calls[2][2] == {"state": "closed", "state_reason": "completed"}


def test_une_pr_a_relire_laisse_l_issue_ouverte(monkeypatch, tmp_path):
    code, calls = _publier(monkeypatch, tmp_path, post=True, created=_pr(merged=False))
    assert code == 0
    assert [(url, method) for url, method, _ in calls] == [(f"{ISSUE_URL}/comments", "POST")]
    assert "ouverte, à relire" in calls[0][2]["body"]


def test_sans_post_rien_n_est_ecrit_sous_l_issue(monkeypatch, tmp_path):
    code, calls = _publier(monkeypatch, tmp_path, post=False, created=_pr(merged=True))
    assert code == 0 and calls == []


def test_une_publication_en_panne_laisse_l_issue_ouverte(monkeypatch, tmp_path):
    panne = se.pull_request.PullRequestError("git add a échoué")
    code, calls = _publier(monkeypatch, tmp_path, post=True, failure=panne)
    assert code == 1
    assert [(url, method) for url, method, _ in calls] == [(f"{ISSUE_URL}/comments", "POST")]
    assert "la publication a échoué" in calls[0][2]["body"]


# Cas réel, issue #8 (Odoxa, notice 10310) : le rapport écrit ses bases en page de
# méthodologie, pas sous ses tableaux.
RAPPORT = """--- page 3 ---
Méthodologie Enquête réalisée par Internet du 24 septembre au 7 octobre 2026.
• 7 599 (hypothèse Philippe) à 7 374 (hypothèse Attal) individus au 1er tour
--- page 12 ---
Intentions de vote au premier tour Hypothèse : Edouard Philippe candidat
Nathalie Arthaud 0,5%
Fabien Roussel 2%
Jean-Luc Mélenchon 18%
Marine Tondelier 3%
Raphaël Glucksmann 9,5%
Edouard Philippe 17%
Bruno Retailleau 6,5%
Nicolas Dupont-Aignan 2%
Marine Le Pen 37%
Éric Zemmour 4,5%
"""
TABLEAU_12 = [
    "TABLEAU",
    "TOUR: 1er Tour",
    "EFFECTIFS: exprimé une intention de vote = 7599",
    "Nathalie Arthaud | 0.5 | Nathalie Arthaud 0,5%",
    "Fabien Roussel | 2 | Fabien Roussel 2%",
    "Jean-Luc Mélenchon | 18 | Jean-Luc Mélenchon 18%",
    "Marine Tondelier | 3 | Marine Tondelier 3%",
    "Raphaël Glucksmann | 9.5 | Raphaël Glucksmann 9,5%",
    "Édouard Philippe | 17 | Edouard Philippe 17%",
    "Bruno Retailleau | 6.5 | Bruno Retailleau 6,5%",
    "Nicolas Dupont-Aignan | 2 | Nicolas Dupont-Aignan 2%",
    "Marine Le Pen | 37 | Marine Le Pen 37%",
    "Éric Zemmour | 4.5 | Éric Zemmour 4,5%",
    "FIN",
]
TERRAIN = SimpleNamespace(start="2026-09-24", end="2026-10-07")


def _candidats():
    return se.extraction.candidate_names(se.ROOT / "candidats.csv")


def test_la_methodologie_d_un_rapport_est_la_page_qui_porte_les_dates_du_terrain():
    assert [page.number for page in se.base_pages(RAPPORT, TERRAIN)] == [3]


def test_un_rapport_peut_ecrire_ses_bases_en_page_de_methodologie():
    tables = se.check_tables(RAPPORT, {12: TABLEAU_12}, _candidats(), se.base_pages(RAPPORT, TERRAIN))
    assert [count for _label, count in tables[0].samples] == [7599]


def test_sur_une_notice_l_effectif_reste_sur_la_page_du_tableau():
    with pytest.raises(se.SubmissionError, match="l'effectif 7599 est absent de la page"):
        se.check_tables(RAPPORT, {12: TABLEAU_12}, _candidats())


def test_un_effectif_ecrit_nulle_part_est_refuse():
    faux = [line.replace("= 7599", "= 7600") for line in TABLEAU_12]
    with pytest.raises(se.SubmissionError, match="page 12, tableau 1 : l'effectif 7600"):
        se.check_tables(RAPPORT, {12: faux}, _candidats(), se.base_pages(RAPPORT, TERRAIN))

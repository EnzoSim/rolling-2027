"""Création de PR : commandes contrôlées, sans réseau ni dépôt Git réel."""

from types import SimpleNamespace

import pytest

from mining import pull_request
from mining.proposal import Proposal


def _proposal():
    return Proposal(
        filename="notice.pdf",
        methodology={
            "institute": "OpinionWay",
            "commissioner": "CNews",
            "start": "2026-09-09",
            "end": "2026-09-10",
            "sample": 1001,
            "registered": 935,
            "population": "représentatif de la population française âgée de 18 ans et plus",
            "source_dates": "Du 9 au 10 septembre 2026",
            "source_sample": "1 001 personnes",
            "source_registered": "935 inscrits",
        },
        polls=[{"poll_id": "20260909_0910_ow_A", "hypothese": "H1", "tour": "1er Tour"}],
        results={"20260909_0910_ow_A": []},
        evidence={
            "20260909_0910_ow_A": {
                "page": 12,
                "values": [{"candidat": "Marine Le Pen", "intentions": "30", "source": "Marine Le Pen 30%"}],
            }
        },
        failures=["citation <inventée>"],
    )


def test_nom_de_branche_est_deterministe_et_borne():
    assert pull_request.branch_name(42) == "mining/issue-42"
    with pytest.raises(pull_request.PullRequestError):
        pull_request.branch_name(0)


def test_corps_de_pr_contient_citations_brouillon_et_echappe_le_modele():
    body = pull_request.body(42, _proposal(), ["model:free"], 5)
    assert "Closes #42" in body
    assert "comparé chaque tableau" in body
    assert "page 12" in body and "Marine Le Pen 30%" in body
    assert "&lt;inventée&gt;" in body
    assert "model:free" in body and "appels LLM : 5" in body


def test_prepare_branch_ne_change_que_la_branche_dediee(monkeypatch, tmp_path):
    commands = []

    def fake_run(command, root, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pull_request, "_run", fake_run)
    assert pull_request.prepare_branch(42, tmp_path) == "mining/issue-42"
    assert commands == [
        ["git", "status", "--porcelain"],
        ["git", "fetch", "origin", "main"],
        ["git", "switch", "-C", "mining/issue-42", "origin/main"],
    ]


def test_creation_de_pr_est_un_brouillon_et_applique_les_labels(monkeypatch, tmp_path):
    commands = []
    views = 0

    def fake_run(command, root, **kwargs):
        nonlocal views
        commands.append(command)
        if command[:3] == ["git", "diff", "--cached"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if command[:3] == ["gh", "pr", "view"]:
            views += 1
            if views == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="not found")
            return SimpleNamespace(returncode=0, stdout='{"number": 7, "url": "https://example.test/pr/7"}', stderr="")
        if command[:3] == ["gh", "label", "list"]:
            return SimpleNamespace(
                returncode=0, stdout='[{"name": "automated"}, {"name": "needs-human-review"}]', stderr=""
            )
        if command[:3] == ["gh", "pr", "create"]:
            return SimpleNamespace(returncode=0, stdout="https://example.test/pr/7\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pull_request, "_run", fake_run)
    monkeypatch.setattr(pull_request, "_validate", lambda root: None)
    result = pull_request.create_or_update(42, "MieuxVoter/presidentielle2027", _proposal(), tmp_path)
    assert result.number == 7 and result.url.endswith("/7")
    create = next(command for command in commands if command[:3] == ["gh", "pr", "create"])
    assert "--draft" in create and "--head" in create and "mining/issue-42" in create
    labels = next(command for command in commands if command[:3] == ["gh", "pr", "edit"])
    assert "--add-label" in labels and "needs-human-review" in labels


@pytest.mark.parametrize("state,reused", [("OPEN", True), ("CLOSED", False), ("MERGED", False)])
def test_seule_une_pr_ouverte_est_reutilisee(monkeypatch, tmp_path, state, reused):
    def fake_run(command, root, **kwargs):
        return SimpleNamespace(
            returncode=0, stdout=f'{{"number": 7, "url": "https://example.test/pr/7", "state": "{state}"}}', stderr=""
        )

    monkeypatch.setattr(pull_request, "_run", fake_run)
    found = pull_request._existing_pr("MieuxVoter/presidentielle2027", "mining/issue-42", tmp_path)
    assert (found is not None) == reused


def test_une_pr_incomplete_le_dit_en_tete():
    proposal = _proposal()
    proposal.missing = ["page 40 : quota épuisé chez openrouter (remise à zéro 00:00 UTC)"]
    body = pull_request.body(42, proposal, ["model:free"], 5)
    assert "Dépouillement incomplet" in body and "page 40 : quota épuisé" in body
    assert body.index("Dépouillement incomplet") < body.index("Tableaux proposés")


def test_une_pr_complete_ne_parle_pas_d_incomplet():
    assert "Dépouillement incomplet" not in pull_request.body(42, _proposal(), ["model:free"], 5)


# --- rolling-2027 : fusion automatique d'un dépouillement complet ---


def _faux_gh(commands):
    views = {"n": 0}

    def fake_run(command, root, **kwargs):
        commands.append(command)
        if command[:3] == ["git", "diff", "--cached"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if command[:3] == ["gh", "pr", "view"]:
            views["n"] += 1
            if views["n"] == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="not found")
            return SimpleNamespace(returncode=0, stdout='{"number": 9, "url": "https://example.test/pr/9"}', stderr="")
        if command[:3] == ["gh", "label", "list"]:
            return SimpleNamespace(
                returncode=0, stdout='[{"name": "automated"}, {"name": "needs-human-review"}]', stderr=""
            )
        if command[:3] == ["gh", "pr", "create"]:
            return SimpleNamespace(returncode=0, stdout="https://example.test/pr/9\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return fake_run


def test_un_depouillement_complet_se_fusionne_seul(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(pull_request, "_run", _faux_gh(commands))
    monkeypatch.setattr(pull_request, "_validate", lambda root: None)
    proposal = _proposal()
    proposal.failures = []
    result = pull_request.create_or_update(42, "EnzoSim/rolling-2027", proposal, tmp_path, automerge=True)
    create = next(c for c in commands if c[:3] == ["gh", "pr", "create"])
    assert "--draft" not in create
    assert ["gh", "pr", "merge", "9", "--repo", "EnzoSim/rolling-2027", "--squash", "--delete-branch"] in commands
    assert ["gh", "workflow", "run", "post-merge.yml", "--repo", "EnzoSim/rolling-2027", "--ref", "main"] in commands
    labels = next(c for c in commands if c[:3] == ["gh", "pr", "edit"])
    assert "needs-human-review" not in labels
    assert result.merged


def test_un_depouillement_incomplet_reste_en_brouillon(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(pull_request, "_run", _faux_gh(commands))
    monkeypatch.setattr(pull_request, "_validate", lambda root: None)
    proposal = _proposal()
    proposal.missing = ["page 12 : quota épuisé"]
    result = pull_request.create_or_update(42, "EnzoSim/rolling-2027", proposal, tmp_path, automerge=True)
    assert "--draft" in next(c for c in commands if c[:3] == ["gh", "pr", "create"])
    assert not any(c[:3] == ["gh", "pr", "merge"] for c in commands)
    assert not result.merged


def test_sans_automerge_rien_ne_change(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(pull_request, "_run", _faux_gh(commands))
    monkeypatch.setattr(pull_request, "_validate", lambda root: None)
    result = pull_request.create_or_update(42, "EnzoSim/rolling-2027", _proposal(), tmp_path)
    assert "--draft" in next(c for c in commands if c[:3] == ["gh", "pr", "create"])
    assert not result.merged


def test_une_alerte_d_extraction_bloque_la_fusion(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(pull_request, "_run", _faux_gh(commands))
    monkeypatch.setattr(pull_request, "_validate", lambda root: None)
    result = pull_request.create_or_update(42, "EnzoSim/rolling-2027", _proposal(), tmp_path, automerge=True)
    assert not result.merged and not any(c[:3] == ["gh", "pr", "merge"] for c in commands)


def test_git_add_recoit_les_fichiers_de_resultats_par_poll_id(monkeypatch, tmp_path):
    """Cas réel, issue #17 : le chemin était construit avec la ligne entière de polls.csv."""
    commands = []
    monkeypatch.setattr(pull_request, "_run", _faux_gh(commands))
    monkeypatch.setattr(pull_request, "_validate", lambda root: None)
    pull_request.create_or_update(42, "EnzoSim/rolling-2027", _proposal(), tmp_path)
    add = next(c for c in commands if c[:2] == ["git", "add"])
    assert "polls/20260909_0910_ow_A.csv" in add
    assert not any("{" in part for part in add)


# --- rolling-2027 : une fusion vérifiée ne se perd plus sur une panne de GitHub ---
# Cas réel, rolling-2027#69 (26 octobre 2026) : quatre tableaux vérifiés, puis « gh pr merge »
# a reçu un 502 Bad Gateway et la PR est restée ouverte.

BAD_GATEWAY = 'non-200 OK status code: 502 Bad Gateway body: "<html>502 Bad Gateway</html>"'
MERGE = ["gh", "pr", "merge", "9", "--repo", "EnzoSim/rolling-2027", "--squash", "--delete-branch"]
REBUILD = ["gh", "workflow", "run", "post-merge.yml", "--repo", "EnzoSim/rolling-2027", "--ref", "main"]


def _gh_qui_flanche(commands, *, merge_errors=(), state="OPEN", listed="[]"):
    """Un faux `gh` : `merge_errors`, les sorties d'erreur des premières fusions, puis le succès."""
    errors = list(merge_errors)

    def fake_run(command, root, **kwargs):
        commands.append(command)
        if command[:3] == ["gh", "pr", "merge"] and errors:
            return SimpleNamespace(returncode=1, stdout="", stderr=errors.pop(0))
        if command[:3] == ["gh", "pr", "view"]:
            return SimpleNamespace(returncode=0, stdout=f'{{"state": "{state}"}}', stderr="")
        if command[:3] == ["gh", "pr", "list"]:
            return SimpleNamespace(returncode=0, stdout=listed, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return fake_run


@pytest.fixture
def pauses(monkeypatch):
    waited = []
    monkeypatch.setattr(pull_request, "_sleep", waited.append)
    return waited


def test_un_502_sur_la_fusion_se_retente(monkeypatch, tmp_path, pauses):
    commands = []
    monkeypatch.setattr(pull_request, "_run", _gh_qui_flanche(commands, merge_errors=[BAD_GATEWAY]))
    pull_request.merge_verified("EnzoSim/rolling-2027", 9, tmp_path)
    assert commands.count(MERGE) == 2
    assert pauses == [10]
    assert commands[-1] == REBUILD


def test_une_fusion_passee_malgre_le_502_n_est_pas_refaite(monkeypatch, tmp_path, pauses):
    commands = []
    monkeypatch.setattr(pull_request, "_run", _gh_qui_flanche(commands, merge_errors=[BAD_GATEWAY], state="MERGED"))
    pull_request.merge_verified("EnzoSim/rolling-2027", 9, tmp_path)
    assert commands.count(MERGE) == 1 and pauses == []
    assert commands[-1] == REBUILD


def test_une_erreur_definitive_ne_se_retente_pas(monkeypatch, tmp_path, pauses):
    commands = []
    refused = "Pull request #9 is not mergeable: the merge commit cannot be cleanly created."
    monkeypatch.setattr(pull_request, "_run", _gh_qui_flanche(commands, merge_errors=[refused]))
    with pytest.raises(pull_request.PullRequestError, match="not mergeable"):
        pull_request.merge_verified("EnzoSim/rolling-2027", 9, tmp_path)
    assert commands.count(MERGE) == 1 and pauses == []
    assert REBUILD not in commands


def test_les_essais_ont_une_fin(monkeypatch, tmp_path, pauses):
    commands = []
    monkeypatch.setattr(pull_request, "_run", _gh_qui_flanche(commands, merge_errors=[BAD_GATEWAY] * 10))
    with pytest.raises(pull_request.PullRequestError, match="502"):
        pull_request.merge_verified("EnzoSim/rolling-2027", 9, tmp_path)
    assert commands.count(MERGE) == len(pull_request.RETRY_DELAYS) + 1
    assert pauses == list(pull_request.RETRY_DELAYS)


def test_la_fusion_automatique_passe_par_les_essais(monkeypatch, tmp_path, pauses):
    """create_or_update fusionne avec les mêmes essais : un 502 ne laisse plus la PR ouverte."""
    commands = []
    base = _faux_gh(commands)
    errors = [BAD_GATEWAY]

    def fake_run(command, root, **kwargs):
        if command[:3] == ["gh", "pr", "merge"] and errors:
            commands.append(command)
            return SimpleNamespace(returncode=1, stdout="", stderr=errors.pop(0))
        if command[:3] == ["gh", "pr", "view"] and command[-1] == "state":
            commands.append(command)
            return SimpleNamespace(returncode=0, stdout='{"state": "OPEN"}', stderr="")
        return base(command, root, **kwargs)

    monkeypatch.setattr(pull_request, "_run", fake_run)
    monkeypatch.setattr(pull_request, "_validate", lambda root: None)
    proposal = _proposal()
    proposal.failures = []
    result = pull_request.create_or_update(42, "EnzoSim/rolling-2027", proposal, tmp_path, automerge=True)
    assert result.merged and commands.count(MERGE) == 2 and pauses == [10]


def test_une_pr_verifiee_ne_se_dit_pas_brouillon():
    proposal = _proposal()
    proposal.failures = []
    ready = pull_request.body(42, proposal, ["model:free"], 5, ready=True)
    assert "brouillon" not in ready and "- [ ]" not in ready
    assert "vérifié automatiquement" in ready and "Closes #42" in ready
    assert "brouillon" in pull_request.body(42, proposal, ["model:free"], 5)


LISTED = """[
  {"number": 69, "isDraft": false, "headRefName": "mining/issue-68", "labels": [{"name": "automated"}], "mergeable": "MERGEABLE"},
  {"number": 70, "isDraft": true, "headRefName": "mining/issue-71", "labels": [{"name": "automated"}, {"name": "needs-human-review"}], "mergeable": "MERGEABLE"},
  {"number": 72, "isDraft": false, "headRefName": "mining/issue-73", "labels": [{"name": "automated"}, {"name": "needs-human-review"}], "mergeable": "MERGEABLE"},
  {"number": 74, "isDraft": false, "headRefName": "mining/issue-75", "labels": [{"name": "automated"}], "mergeable": "CONFLICTING"},
  {"number": 76, "isDraft": false, "headRefName": "sync/upstream", "labels": [{"name": "automated"}], "mergeable": "MERGEABLE"},
  {"number": 66, "isDraft": false, "headRefName": "mining/issue-65", "labels": [{"name": "automated"}], "mergeable": "UNKNOWN"}
]"""


def test_le_rattrapage_ne_prend_que_les_pr_verifiees(monkeypatch, tmp_path, pauses):
    commands = []
    monkeypatch.setattr(pull_request, "_run", _gh_qui_flanche(commands, listed=LISTED))
    assert pull_request.pending_verified("EnzoSim/rolling-2027", tmp_path) == [66, 69]
    merged, failures = pull_request.catch_up("EnzoSim/rolling-2027", tmp_path)
    assert merged == [66, 69] and failures == []
    merges = [c for c in commands if c[:3] == ["gh", "pr", "merge"]]
    assert [c[3] for c in merges] == ["66", "69"], "jamais un brouillon, une PR à relire, en conflit ou hors mining"
    assert commands.count(REBUILD) == 1, "post-merge.yml une seule fois, après les fusions"


def test_le_rattrapage_continue_apres_un_echec(monkeypatch, tmp_path, pauses):
    commands = []
    refused = "Pull request #66 is not mergeable: the base branch policy prohibits the merge."
    monkeypatch.setattr(pull_request, "_run", _gh_qui_flanche(commands, merge_errors=[refused], listed=LISTED))
    merged, failures = pull_request.catch_up("EnzoSim/rolling-2027", tmp_path)
    assert merged == [69]
    assert failures and failures[0][0] == 66 and "not mergeable" in failures[0][1]
    assert commands.count(REBUILD) == 1


def test_sans_pr_en_attente_rien_ne_part(monkeypatch, tmp_path, pauses):
    commands = []
    monkeypatch.setattr(pull_request, "_run", _gh_qui_flanche(commands))
    assert pull_request.catch_up("EnzoSim/rolling-2027", tmp_path) == ([], [])
    assert REBUILD not in commands

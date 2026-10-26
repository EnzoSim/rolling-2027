"""Le rattrapage horaire des PR de dépouillement vérifiées (merge_verified_prs.py, retry-mining.yml)."""

from pathlib import Path

import merge_verified_prs
from mining import pull_request

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "retry-mining.yml"


def test_la_fusion_automatique_coupee_coupe_le_rattrapage(monkeypatch, capsys):
    monkeypatch.setenv("ROLLING_AUTOMERGE", "0")
    monkeypatch.setattr(pull_request, "catch_up", lambda repo, root: (_ for _ in ()).throw(AssertionError("appelé")))
    assert merge_verified_prs.main(["--repo", "EnzoSim/rolling-2027"]) == 0
    assert "coupée" in capsys.readouterr().out


def test_le_rattrapage_dit_ce_qu_il_a_fait(monkeypatch, capsys):
    monkeypatch.setenv("ROLLING_AUTOMERGE", "1")
    monkeypatch.setattr(pull_request, "catch_up", lambda repo, root: ([69], [(74, "en conflit")]))
    assert merge_verified_prs.main(["--repo", "EnzoSim/rolling-2027"]) == 1, "un échec se voit dans Actions"
    out = capsys.readouterr().out
    assert "PR #69 fusionnée." in out and "::warning::PR #74 toujours ouverte : en conflit" in out


def test_rien_en_attente(monkeypatch, capsys):
    monkeypatch.setenv("ROLLING_AUTOMERGE", "1")
    monkeypatch.setattr(pull_request, "catch_up", lambda repo, root: ([], []))
    assert merge_verified_prs.main(["--repo", "EnzoSim/rolling-2027"]) == 0
    assert "Aucune PR vérifiée en attente." in capsys.readouterr().out


def test_sans_depot_le_script_refuse(monkeypatch, capsys):
    monkeypatch.setenv("ROLLING_AUTOMERGE", "1")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert merge_verified_prs.main([]) == 2


def test_le_passage_horaire_fusionne_les_pr_verifiees():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    job = workflow[workflow.index("  merge-verified:") :]
    for permission in ("contents: write", "pull-requests: write", "actions: write"):
        assert permission in job, permission
    assert 'python merge_verified_prs.py --repo "$GITHUB_REPOSITORY"' in job
    assert "ROLLING_AUTOMERGE: ${{ vars.ROLLING_AUTOMERGE || '1' }}" in job
    assert "cron: '47 * * * *'" in workflow, "chaque heure, avec la relance des notices"

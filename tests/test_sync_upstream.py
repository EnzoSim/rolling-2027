"""Le rétablissement de la synchro ne multiplie pas les alertes GitHub."""

import copy
import os
import subprocess
import textwrap
from pathlib import Path

from scripts.sync_issue import GitHubIssues, MARKER, TITLE, reconcile


class FakeIssues:
    def __init__(self, rows=()):
        self.rows = copy.deepcopy(list(rows))
        self.created = 0

    def alerts(self):
        return sorted(copy.deepcopy(self.rows), key=lambda row: row["number"])

    def request(self, method, suffix="", data=None):
        if method == "POST":
            self.created += 1
            row = {"number": len(self.rows) + 1, "state": "open", **data}
            self.rows.append(row)
            return row
        assert method == "PATCH"
        row = next(row for row in self.rows if row["number"] == int(suffix[1:]))
        row.update(data)
        return row


def test_repeated_failure_recovery_and_recurrence_reuse_one_issue():
    client = FakeIssues()
    assert reconcile(client, "success", "run/1") is None
    assert client.rows == []
    assert reconcile(client, "failure", "run/2") == 1
    assert reconcile(client, "failure", "run/3") == 1
    assert client.created == 1
    assert "run/3" in client.rows[0]["body"]
    assert "run/2" not in client.rows[0]["body"]
    reconcile(client, "success", "run/4")
    assert client.rows[0]["state"] == "closed"
    assert client.rows[0]["state_reason"] == "completed"
    reconcile(client, "failure", "run/5")
    assert client.rows[0]["state"] == "open"
    assert client.created == 1


def test_existing_duplicates_are_closed_without_losing_their_original_diagnostic():
    client = FakeIssues(
        [
            {"number": 52, "title": TITLE, "state": "open", "body": "run/original-52"},
            {"number": 27, "title": TITLE, "state": "open", "body": "run/original-27"},
            {"number": 29, "title": TITLE, "state": "open", "body": "run/original-29"},
        ]
    )
    assert reconcile(client, "success", "run/green") == 27
    assert client.created == 0
    assert all(row["state"] == "closed" for row in client.rows)
    for row in client.rows:
        if row["number"] != 27:
            assert row["body"] == f"Doublon de #27.\n\nrun/original-{row['number']}"
    reconcile(client, "failure", "run/red")
    assert [row["number"] for row in client.rows if row["state"] == "open"] == [27]


def test_rest_pagination_finds_old_alerts_and_excludes_pull_requests():
    client = GitHubIssues("owner/repo", "unused")
    ordinary = [{"number": n, "title": "Other", "body": ""} for n in range(1, 101)]
    pages = [
        ordinary,
        [
            {"number": 101, "title": TITLE, "body": "", "pull_request": {}},
            {"number": 102, "title": "Renamed alert", "body": MARKER},
            {"number": 103, "title": TITLE, "body": ""},
        ],
    ]
    calls = []

    def request(method, suffix):
        calls.append((method, suffix))
        return pages[len(calls) - 1]

    client.request = request
    assert [row["number"] for row in client.alerts()] == [102, 103]
    assert calls == [
        ("GET", "?state=all&per_page=100&page=1"),
        ("GET", "?state=all&per_page=100&page=2"),
    ]


def test_failed_validation_never_commits_or_pushes_a_merged_dataset(tmp_path):
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/sync-upstream.yml"
    step = workflow.read_text().split("- name: Régénérer et pousser\n", 1)[1]
    step = step.split("\n      - name:", 1)[0]
    script = textwrap.dedent(step.split("run: |\n", 1)[1])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command, body in {
        "python": 'echo "python $*" >> "$CALLS"\nif [ "$*" = "-m pytest -q" ]; then exit 1; fi\n',
        "git": 'echo "git $*" >> "$CALLS"\n',
    }.items():
        executable = bin_dir / command
        executable.write_text("#!/usr/bin/env bash\n" + body)
        executable.chmod(0o755)
    calls = tmp_path / "calls"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "CALLS": str(calls)},
        check=False,
    )
    assert result.returncode != 0
    recorded = calls.read_text()
    assert "python -m pytest -q" in recorded
    assert "git " not in recorded

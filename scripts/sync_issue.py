"""Une seule alerte pour la synchro : réutilisée, rouverte, puis fermée au succès.

Le titre historique permet aussi de ranger les doublons déjà créés. Les runs de
sync-upstream sont sérialisés par le groupe de concurrence du workflow ; la liste
REST paginée évite le délai d'indexation de la recherche GitHub.
"""

import argparse
import json
import os
import re
import urllib.request

TITLE = "⚠️ Synchronisation avec Mieux Voter en échec"
MARKER = "<!-- rolling-2027:sync-upstream -->"


class GitHubIssues:
    def __init__(self, repository, token):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("GITHUB_REPOSITORY invalide")
        self.url = f"https://api.github.com/repos/{repository}/issues"
        self.token = token

    def request(self, method, suffix="", data=None):
        request = urllib.request.Request(
            self.url + suffix,
            data=json.dumps(data).encode("utf-8") if data is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "rolling-2027-sync",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def alerts(self):
        alerts = []
        page = 1
        while True:
            rows = self.request("GET", f"?state=all&per_page=100&page={page}")
            alerts.extend(
                row for row in rows
                if "pull_request" not in row
                and (row["title"] == TITLE or MARKER in (row.get("body") or ""))
            )
            if len(rows) < 100:
                return sorted(alerts, key=lambda row: row["number"])
            page += 1


def reconcile(client, status, run_url):
    alerts = client.alerts()
    if status == "success" and not alerts:
        return None

    failed = status == "failure"
    body = (
        f"{MARKER}\n\n"
        + ("La synchronisation avec MieuxVoter/presidentielle2027 a échoué."
           if failed else "La synchronisation avec MieuxVoter/presidentielle2027 a réussi.")
        + f"\n\nDernière exécution : {run_url}\n\n"
        "Cette issue unique est mise à jour à chaque échec, fermée après une réussite "
        "et rouverte si la synchronisation échoue à nouveau.\n"
    )
    if not alerts:
        canonical = client.request("POST", data={"title": TITLE, "body": body})
    else:
        canonical = alerts[0]
        client.request("PATCH", f"/{canonical['number']}", {
            "body": body,
            "state": "open" if failed else "closed",
            "state_reason": "reopened" if failed else "completed",
        })

    for duplicate in alerts[1:]:
        if duplicate["state"] == "open":
            client.request("PATCH", f"/{duplicate['number']}", {
                "state": "closed",
                "state_reason": "not_planned",
                "body": f"Doublon de #{canonical['number']}.\n\n" + (duplicate.get("body") or ""),
            })
    print(f"Alerte #{canonical['number']} : {'ouverte' if failed else 'résolue'}.")
    return canonical["number"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("status", choices=("success", "failure"))
    args = parser.parse_args()
    repository = os.environ["GITHUB_REPOSITORY"]
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    reconcile(GitHubIssues(repository, os.environ["GH_TOKEN"]), args.status, run_url)


if __name__ == "__main__":
    main()

"""Création sûre d'une PR brouillon à partir d'une proposition déjà validée.

Ce module ne lit aucun contenu de la notice et ne décide aucune valeur : il se
contente de créer une branche dédiée, d'exécuter les vérifications du dépôt, puis
d'appeler GitHub CLI. Les commandes sont passées sous forme de listes, jamais
construites à partir de texte de notice ou de commentaire.
"""

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


class PullRequestError(RuntimeError):
    """Une branche ou une PR n'a pas pu être créée ; la cause est publiable."""


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    branch: str
    labels_warning: str = ""
    merged: bool = False


def branch_name(issue):
    """Nom déterministe et sans entrée libre : un rerun met à jour la même PR."""
    if not isinstance(issue, int) or issue <= 0:
        raise PullRequestError("numéro d'issue invalide")
    return f"mining/issue-{issue}"


def _run(command, root, *, input_text=None, allow_failure=False):
    """Exécute une commande et transforme son erreur en diagnostic court."""
    completed = subprocess.run(
        command,
        cwd=root,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode and not allow_failure:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        raise PullRequestError(f"{' '.join(command[:3])} a échoué : {detail[-1] if detail else 'erreur inconnue'}")
    return completed


# rolling-2027 : une fusion vérifiée ne se perd plus sur une panne passagère de GitHub. Le
# 26 octobre 2026, « gh pr merge » a reçu un 502 Bad Gateway sur rolling-2027#69 : les quatre
# tableaux étaient vérifiés, mais la PR est restée ouverte jusqu'à ce qu'une personne la
# fusionne. Ces erreurs-là se retentent, après ces délais (secondes) ; les autres remontent
# aussitôt, et le rattrapage horaire (`catch_up`, retry-mining.yml) reprend ce qui reste.
TRANSIENT_MARKERS = (
    "500 internal",
    "502",
    "503",
    "504",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
    "tls handshake",
    "temporary failure",
    "secondary rate limit",
)
RETRY_DELAYS = (10, 30, 90)
_sleep = time.sleep


def _transient(completed):
    """Une erreur de GitHub ou du réseau qui peut passer en réessayant."""
    text = f"{completed.stderr or ''}\n{completed.stdout or ''}".lower()
    return any(marker in text for marker in TRANSIENT_MARKERS)


def _run_retrying(command, root, *, done=None):
    """`_run`, retenté sur une panne passagère (`RETRY_DELAYS`).

    `done()`, quand il est donné, dit après un échec si l'effet a quand même eu lieu :
    GitHub peut fusionner une PR et répondre 502.
    """
    for delay in (*RETRY_DELAYS, None):
        completed = _run(command, root, allow_failure=True)
        if not completed.returncode or (done is not None and done()):
            return completed
        if delay is None or not _transient(completed):
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            raise PullRequestError(f"{' '.join(command[:3])} a échoué : {detail[-1] if detail else 'erreur inconnue'}")
        _sleep(delay)
    raise AssertionError("inaccessible")


def _pr_state(repo, number, root):
    """L'état d'une PR (« OPEN », « MERGED », « CLOSED »), ou None si GitHub ne répond pas."""
    completed = _run(["gh", "pr", "view", str(number), "--repo", repo, "--json", "state"], root, allow_failure=True)
    if completed.returncode:
        return None
    try:
        return json.loads(completed.stdout).get("state")
    except (json.JSONDecodeError, AttributeError):
        return None


def merge_verified(repo, number, root, *, rebuild=True):
    """Fusionne une PR de dépouillement vérifiée, puis relance post-merge.yml.

    Une fusion faite avec GITHUB_TOKEN ne déclenche aucun workflow : post-merge.yml
    reconstruit le flux à la main (`rebuild`). Chaque appel est retenté sur une panne
    passagère de GitHub.
    """
    _run_retrying(
        ["gh", "pr", "merge", str(number), "--repo", repo, "--squash", "--delete-branch"],
        root,
        done=lambda: _pr_state(repo, number, root) == "MERGED",
    )
    if rebuild:
        _run_retrying(["gh", "workflow", "run", "post-merge.yml", "--repo", repo, "--ref", "main"], root)


def pending_verified(repo, root):
    """Les PR de dépouillement vérifiées restées ouvertes, la plus ancienne d'abord.

    Vérifiée : ouverte prête (jamais en brouillon) par `create_or_update`, sur une branche
    `mining/issue-N`, étiquetée `automated`, sans `needs-human-review`. Une PR en conflit
    attend un nouveau dépouillement (`/mining-pr`), qui reconstruit sa branche.
    """
    listed = _run_retrying(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--label",
            "automated",
            "--limit",
            "50",
            "--json",
            "number,isDraft,headRefName,labels,mergeable",
        ],
        root,
    )
    try:
        rows = json.loads(listed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise PullRequestError("gh pr list a renvoyé un JSON illisible") from exc
    pending = []
    for row in rows:
        labels = {label.get("name") for label in row.get("labels") or []}
        if row.get("isDraft") or "needs-human-review" in labels or row.get("mergeable") == "CONFLICTING":
            continue
        if not str(row.get("headRefName", "")).startswith("mining/issue-"):
            continue
        pending.append(int(row["number"]))
    return sorted(pending)


def catch_up(repo, root):
    """Fusionne les PR vérifiées restées ouvertes ; post-merge.yml une seule fois à la fin.

    Renvoie les numéros fusionnés et, pour chaque échec, son numéro et sa raison : une PR
    qui échoue n'empêche pas les suivantes.
    """
    merged, failures = [], []
    for number in pending_verified(repo, root):
        try:
            merge_verified(repo, number, root, rebuild=False)
            merged.append(number)
        except PullRequestError as exc:
            failures.append((number, str(exc)))
    if merged:
        _run_retrying(["gh", "workflow", "run", "post-merge.yml", "--repo", repo, "--ref", "main"], root)
    return merged, failures


def _working_tree_clean(root):
    status = _run(["git", "status", "--porcelain"], root).stdout.strip()
    if status:
        raise PullRequestError("l'arbre Git doit être propre avant de préparer la branche de mining")


def prepare_branch(issue, root):
    """Replace la branche de l'issue sur `origin/main`, avant l'écriture des CSV."""
    root = Path(root)
    _working_tree_clean(root)
    branch = branch_name(issue)
    _run(["git", "fetch", "origin", "main"], root)
    # Cette branche est strictement réservée à l'issue. La recréer à chaque run
    # remplace la proposition précédente, jamais une branche humaine.
    _run(["git", "switch", "-C", branch, "origin/main"], root)
    return branch


def _safe(text):
    """Le texte issu du modèle reste du texte, pas du Markdown exécutable."""
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("```", "'''")


def body(issue, proposal, models, calls, ready=False):
    """Corps de PR relisible : toutes les valeurs pointent vers leur citation.

    `ready` : le dépouillement est complet et vérifié (`can_automerge`), la PR se fusionne
    seule ; elle ne se dit alors pas brouillon, pour qu'on ne la croie pas en attente.
    """
    method = proposal.methodology
    lines = ["# Proposition de sondage générée automatiquement", "", f"Closes #{issue}", ""]
    if ready:
        lines.extend(
            [
                "> 🤖 Dépouillement vérifié automatiquement : chaque chiffre est retrouvé sur sa ligne de la"
                " notice, pytest et merge.py passent. Cette PR se fusionne seule ; si elle reste ouverte, le"
                " rattrapage horaire (retry-mining.yml) la fusionne.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "> 🤖 Cette PR est un brouillon. Une comparaison humaine avec la notice/PDF est obligatoire avant fusion.",
                "",
                "- [ ] J'ai comparé chaque tableau et la méthodologie au PDF source.",
                "",
            ]
        )
    if proposal.missing:
        lines.extend(
            [
                "## ⚠️ Dépouillement incomplet",
                "",
                "Ces pages n'ont pas pu être interrogées (quota ou réseau). Les tableaux ci-dessous sont vérifiés et"
                " peuvent être fusionnés tels quels ; relancer `/mining-pr` sous l'issue pour compléter, avant ou après"
                " la fusion : les hypothèses déjà enregistrées ne sont pas reproposées.",
                "",
            ]
        )
        lines.extend(f"- {_safe(item)}" for item in proposal.missing)
        lines.append("")
    if proposal.candidates:
        lines.extend(["## Candidats à ajouter", ""])
        lines.extend(f"- `{row['candidate_id']}` — {_safe(row['complete_name'])}" for row in proposal.candidates)
        lines.append("")
    lines.extend(
        [
            "## Méthodologie",
            "",
            f"- Institut : **{_safe(method.get('institute'))}**",
            f"- Commanditaire : {_safe(method.get('commissioner'))}",
            f"- Terrain : {method.get('start')} → {method.get('end')}",
            f"- Échantillon : {method.get('sample')} ; inscrits : {method.get('registered') or 'non indiqué'}",
            f"- Population : {_safe(method.get('population'))}",
            "",
            "<details><summary>Citations méthodologiques</summary>",
            "",
            f"- Dates : {_safe(method.get('source_dates'))}",
            f"- Échantillon : {_safe(method.get('source_sample'))}",
        ]
    )
    if method.get("source_registered"):
        lines.append(f"- Inscrits : {_safe(method['source_registered'])}")
    lines.extend(["", "</details>", ""])
    lines.extend(["## Tableaux proposés", ""])
    new_hypotheses = {row["id_hypothese"] for row in proposal.hypotheses}
    for poll in proposal.polls:
        evidence = proposal.evidence.get(poll["poll_id"], {})
        marker = "nouvelle" if poll["hypothese"] in new_hypotheses else "existante"
        lines.extend(
            [
                f"### `{poll['poll_id']}` — {poll['tour']}",
                "",
                f"Hypothèse {marker} : `{poll['hypothese']}` · page {evidence.get('page', '?')}",
                "",
                "| Candidat | Intention | Citation de la notice |",
                "| --- | ---: | --- |",
            ]
        )
        for value in evidence.get("values", []):
            source = _safe(value.get("source", "")).replace("|", "\\|")
            lines.append(f"| {_safe(value.get('candidat'))} | {value.get('intentions')} | {source} |")
        lines.append("")
    if proposal.failures:
        lines.extend(["## Tableaux écartés", ""])
        lines.extend(f"- {_safe(failure)}" for failure in proposal.failures)
        lines.append("")
    model_text = ", ".join(sorted(set(models))) or "inconnu"
    lines.extend(["---", f"Modèle(s) : {model_text} · appels LLM : {calls}."])
    return "\n".join(lines) + "\n"


def _validate(root):
    _run([sys.executable, "-m", "pytest", "-q"], root)
    _run([sys.executable, "merge.py"], root)


def _existing_pr(repo, branch, root):
    """La PR ouverte de la branche, ou None.

    `gh pr view <branche>` renvoie aussi une PR fermée ou fusionnée : la
    « mettre à jour » laisserait la nouvelle proposition invisible.
    """
    completed = _run(
        ["gh", "pr", "view", branch, "--repo", repo, "--json", "number,url,state"], root, allow_failure=True
    )
    if completed.returncode:
        return None
    try:
        view = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PullRequestError("gh pr view a renvoyé un JSON illisible") from exc
    return view if view.get("state", "OPEN") == "OPEN" else None


def _available_labels(repo, root):
    completed = _run(
        ["gh", "label", "list", "--repo", repo, "--limit", "100", "--json", "name"], root, allow_failure=True
    )
    if completed.returncode:
        return set()
    try:
        return {row["name"] for row in json.loads(completed.stdout)}
    except (json.JSONDecodeError, KeyError, TypeError):
        return set()


def _apply_labels(repo, number, root, review=True):
    available = _available_labels(repo, root)
    wanted = [label for label in ("automated", "needs-human-review") if label in available]
    if not review:
        wanted = [label for label in wanted if label == "automated"]
    elif "needs-human-review" not in available and "need-screening !" in available:
        wanted.append("need-screening !")
    if wanted:
        _run(
            ["gh", "pr", "edit", str(number), "--repo", repo, *sum((["--add-label", label] for label in wanted), [])],
            root,
        )
    missing = {"automated", "needs-human-review"} - available
    if not review:
        missing.discard("needs-human-review")
    if "needs-human-review" in missing and "need-screening !" in available:
        missing.remove("needs-human-review")
    return "" if not missing else "Labels absents : " + ", ".join(sorted(missing))


def can_automerge(proposal):
    """rolling-2027 : seul un dépouillement complet et sans alerte se fusionne seul.

    Chaque chiffre a déjà été retrouvé sur sa ligne de la notice (extraction.py), et
    `_validate` vient de faire passer pytest et merge.py. Une page non dépouillée ou
    une alerte de l'extraction laissent la PR en brouillon, pour une relecture humaine.
    """
    return not proposal.missing and not getattr(proposal, "failures", None)


def create_or_update(issue, repo, proposal, root, models=(), calls=0, automerge=False):
    """Valide, commit, pousse et crée ou met à jour la PR de l'issue.

    Brouillon par défaut ; avec `automerge` et une proposition complète
    (`can_automerge`), la PR est ouverte prête, fusionnée, puis post-merge.yml est
    relancé (une fusion faite avec GITHUB_TOKEN ne déclenche aucun workflow).
    """
    root = Path(root)
    ready = automerge and can_automerge(proposal)
    branch = branch_name(issue)
    _validate(root)
    # proposal.polls porte les lignes de polls.csv (des dictionnaires) ; les fichiers de
    # résultats sont nommés d'après leur poll_id, les clés de proposal.results.
    paths = ["candidats.csv", "hypotheses.csv", "polls.csv", *(f"polls/{poll_id}.csv" for poll_id in proposal.results)]
    _run(["git", "add", "--", *paths], root)
    staged = _run(["git", "diff", "--cached", "--quiet"], root, allow_failure=True)
    if staged.returncode == 0:
        raise PullRequestError("aucune donnée nouvelle à committer")
    _run(["git", "config", "user.name", "github-actions[bot]"], root)
    _run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], root)
    _run(["git", "commit", "-m", f"🤖 Ajout sondage depuis l'issue #{issue}"], root)
    _run(["git", "push", "--force-with-lease", "--set-upstream", "origin", branch], root)

    content = body(issue, proposal, models, calls, ready=ready)
    existing = _existing_pr(repo, branch, root)
    title = f"🤖 Proposition de sondage — issue #{issue}"
    if existing:
        number, url = existing["number"], existing["url"]
        _run(["gh", "pr", "edit", str(number), "--repo", repo, "--title", title, "--body", content], root)
        if ready:
            _run(["gh", "pr", "ready", str(number), "--repo", repo], root, allow_failure=True)
    else:
        created = _run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                repo,
                "--base",
                "main",
                "--head",
                branch,
                *([] if ready else ["--draft"]),
                "--title",
                title,
                "--body",
                content,
            ],
            root,
        )
        url = created.stdout.strip().splitlines()[-1]
        view = _existing_pr(repo, branch, root)
        if not view:
            raise PullRequestError("la PR a été créée mais GitHub ne permet pas de la relire")
        number, url = view["number"], view["url"] or url
    warning = _apply_labels(repo, number, root, review=not ready)
    if not ready:
        return PullRequest(number, url, branch, warning)
    merge_verified(repo, number, root)
    return PullRequest(number, url, branch, warning, merged=True)

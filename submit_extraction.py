#!/usr/bin/env python3
"""rolling-2027 : publier un dépouillement fait à la main (par une personne ou un bot).

Sans clé d'API, c'est le bot (ou un humain) qui lit la notice et écrit le dépouillement,
dans le format que la chaîne demande au modèle (mining/prompts/e2_methodologie.txt et
e3_tableaux.txt). Ce script ne décide aucune valeur : il les vérifie toutes contre le
texte de la notice, avec les validateurs du dépôt, puis ouvre la PR et la fusionne quand
rien ne cloche (ROLLING_AUTOMERGE=1), comme le dépouillement par modèle.

    python submit_extraction.py --issue 17 --input extraction.txt          # vérifie seulement
    python submit_extraction.py --issue 17 --input extraction.txt --pr     # PR (+ fusion)
    python submit_extraction.py --issue 17 --body-env COMMENT_BODY --post --pr   # depuis un commentaire

Le format (docs/BOT.md) : les champs de méthodologie, puis un bloc « PAGE n » par page
dépouillée, chacun avec ses blocs TABLEAU … FIN. Une valeur « - » (moins de 0,5 % chez
l'IFOP) s'écrit « - » et vaut 0, sa ligne source recopiée telle quelle.
"""

import argparse
import os
import re
import sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from check_new_polls import _github_request
from mine_poll import NoticeUnavailable, issue_poll_filename, notice_date, notice_text_for
from mining import csvio, extraction, notice, pull_request
from mining.proposal import ProposalError, build as build_proposal

ROOT = Path(__file__).resolve().parent
COMMAND_RE = re.compile(r"^\s*/extraction\b", re.MULTILINE)
PAGE_RE = re.compile(r"^\s*PAGE\s+(\d+)\s*$", re.IGNORECASE)
DASH_RE = re.compile(r"^\s*(?P<name>[^|]+?)\s*\|\s*[-–—]\s*\|\s*(?P<source>.+?)\s*$")
FENCE_RE = re.compile(r"^\s*```")
# Un rapport d'institut ne se télécharge que depuis le site de l'institut lui-même.
REPORT_HOSTS = (
    "ifop.com",
    "odoxa.fr",
    "harris-interactive.fr",
    "toluna-group.com",
    "opinion-way.com",
    "opinionway.com",
    "elabe.fr",
    "ipsos.com",
    "bva-group.com",
    "cluster17.com",
    "yougov.com",
    "today.yougov.com",
    "csa.eu",
    "veriangroup.com",
    "commission-des-sondages.fr",
)


class SubmissionError(ValueError):
    """Le dépouillement ne passe pas une vérification ; le message est publiable."""


def strip_command(text):
    """Le texte utile d'un commentaire : sans la commande ni les clôtures de code."""
    lines = [line for line in (text or "").splitlines() if not FENCE_RE.match(line)]
    body = "\n".join(lines)
    return COMMAND_RE.sub("", body, count=1).strip()


def split_submission(text):
    """(texte de méthodologie, {page: [lignes]}, url du rapport ou None)."""
    head, pages, current, report = [], {}, None, None
    for raw in strip_command(text).splitlines():
        line = raw.rstrip()
        page = PAGE_RE.match(line)
        if page:
            current = int(page.group(1))
            pages.setdefault(current, [])
            continue
        if current is None:
            if line.strip().upper().startswith("RAPPORT:"):
                report = line.split(":", 1)[1].strip()
                continue
            head.append(line)
        else:
            pages[current].append(line)
    if not pages:
        raise SubmissionError("aucun bloc « PAGE n » : rien à vérifier")
    return "\n".join(head), pages, report


def _blocks(lines):
    """Les blocs TABLEAU … FIN d'une page, chacun avec ses lignes intérieures."""
    blocks, current = [], None
    for line in lines:
        word = line.strip().upper()
        if word == "TABLEAU":
            if current is not None:
                raise SubmissionError("TABLEAU ouvert deux fois sans FIN")
            current = []
        elif word == "FIN":
            if current is None:
                raise SubmissionError("FIN sans TABLEAU")
            blocks.append(current)
            current = None
        elif current is not None:
            current.append(line)
        elif line.strip():
            raise SubmissionError(f"ligne hors d'un bloc TABLEAU : {line.strip()[:60]}")
    if current is not None:
        raise SubmissionError("TABLEAU sans FIN")
    return blocks


def _dash_value(match, page, known):
    """Un candidat noté « - » : présent dans l'hypothèse, à 0, sa ligne sur la page."""
    name, source = match.group("name").strip(), match.group("source").strip()
    canonical = {extraction._norm(candidate): candidate for candidate in known}.get(extraction._norm(name), name)
    if not extraction.citation_in_page(source, page):
        raise SubmissionError(f"page {page.number} : ligne introuvable pour {name}")
    if extraction._norm(name) not in extraction._norm(source):
        raise SubmissionError(f"page {page.number} : la ligne ne contient pas {name}")
    if re.search(r"\d", source.replace(name, "")) or not re.search(r"[-–—]", source):
        raise SubmissionError(f"page {page.number} : « - » ne correspond pas à la ligne de {name}")
    return extraction.CandidateValue(canonical, Decimal("0"), source)


def _without_registered(line):
    """EFFECTIFS sans la base des inscrits : elle est déjà dans la méthodologie (INSCRITS).

    Un bot la recopie volontiers (cas réel, issue #17, OpinionWay : « inscrits sur les
    listes électorales = 978 ») ; le tableau ne garde que ses propres bases.
    """
    if not re.match(r"^\s*EFFECTIFS\s*:", line, re.IGNORECASE):
        return line
    head, _, rest = line.partition(":")
    kept = [item for item in rest.split("|") if "inscrit" not in extraction._norm(item.split("=")[0])]
    return f"{head}: {' | '.join(item.strip() for item in kept)}"


def check_tables(pages_text, page_blocks, known):
    """Chaque tableau passé par parse_tables (citation, candidat, valeur, total, effectifs)."""
    pages = {page.number: page for page in notice.split_pages(pages_text)}
    tables = []
    for number, lines in sorted(page_blocks.items()):
        page = pages.get(number)
        if page is None:
            raise SubmissionError(f"la notice n'a pas de page {number}")
        for index, block in enumerate(_blocks(lines), 1):
            block = [_without_registered(line) for line in block]
            dashes = [DASH_RE.match(line) for line in block]
            numeric = [line for line, dash in zip(block, dashes) if not dash]
            answer = "\n".join(["TABLEAU", *numeric, "FIN"])
            parsed, failures = extraction.parse_tables(answer, page, known)
            if failures or len(parsed) != 1:
                raise SubmissionError("; ".join(failures) or f"page {number}, tableau {index} : illisible")
            table = parsed[0]
            extra = tuple(_dash_value(dash, page, known) for dash in dashes if dash)
            names = [extraction._norm(value.name) for value in (*extra, *table.values)]
            if len(names) != len(set(names)):
                raise SubmissionError(f"page {number}, tableau {index} : un candidat est présent deux fois")
            tables.append(extraction.ExtractedTable(table.page, table.tour, table.samples, extra + table.values))
    return tables


def report_text(url):
    """Le texte d'un rapport d'institut (PDF), seulement depuis le site de l'institut."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(host == allowed or host.endswith("." + allowed) for allowed in REPORT_HOSTS):
        raise SubmissionError(f"RAPPORT doit être un PDF en https sur le site d'un institut ({host or url})")
    return notice.pdf_text_from_url(url)


def verify(text, filename, notice_text):
    """Vérifie tout ; rend la proposition prête à écrire dans le dépôt."""
    methodology_text, page_blocks, report = split_submission(text)
    tables_text = report_text(report) if report else notice_text
    pages = notice.split_pages(notice_text)
    try:
        methodology = extraction.parse_methodology(
            methodology_text,
            pages,
            extraction.institutions_from_polls(ROOT / "polls.csv"),
            extraction.populations_from_polls(ROOT / "polls.csv"),
            notice_date(notice_text),
        )
    except extraction.ValidationError as exc:
        raise SubmissionError(f"méthodologie : {exc}") from exc
    tables = check_tables(tables_text, page_blocks, extraction.candidate_names(ROOT / "candidats.csv"))
    try:
        proposal = build_proposal(filename, methodology, tables, ROOT)
    except ProposalError as exc:
        raise SubmissionError(str(exc)) from exc
    return proposal, report


def comment(repo, issue, token, body):
    _github_request(f"https://api.github.com/repos/{repo}/issues/{issue}/comments", token, "POST", {"body": body})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--issue", type=int, required=True, help="issue « Nouveau sondage » de la notice")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="fichier du dépouillement")
    source.add_argument("--body-env", help="variable d'environnement qui porte le commentaire")
    parser.add_argument("--notice-txt", help="texte local de la notice (sinon le catalogue amont)")
    parser.add_argument(
        "--pr", action="store_true", help="écrire, ouvrir la PR (et la fusionner si ROLLING_AUTOMERGE=1)"
    )
    parser.add_argument("--post", action="store_true", help="publier le résultat sous l'issue")
    args = parser.parse_args(argv)

    repo = os.environ.get("GITHUB_REPOSITORY", "EnzoSim/rolling-2027")
    token = os.environ.get("GITHUB_TOKEN", "")
    text = Path(args.input).read_text(encoding="utf-8") if args.input else os.environ.get(args.body_env, "")

    try:
        filename = issue_poll_filename(repo, args.issue, token)
        notice_text = (
            Path(args.notice_txt).read_text(encoding="utf-8") if args.notice_txt else notice_text_for(filename)
        )
        proposal, report = verify(text, filename, notice_text)
    except (SubmissionError, NoticeUnavailable) as exc:
        message = f"❌ Dépouillement refusé : {exc}"
        print(message)
        if args.post:
            comment(repo, args.issue, token, message + "\n\nCorrige et renvoie `/extraction` (voir docs/BOT.md).")
        return 1

    summary = ", ".join(f"{poll['poll_id']} ({poll['hypothese']})" for poll in proposal.polls)
    print(f"✅ {len(proposal.polls)} tableau(x) vérifié(s) : {summary}")
    if not args.pr:
        return 0

    try:
        pull_request.prepare_branch(args.issue, ROOT)
        csvio.apply(proposal, ROOT)
        created = pull_request.create_or_update(
            args.issue,
            repo,
            proposal,
            ROOT,
            models=[f"dépouillement manuel{' (rapport : ' + report + ')' if report else ''}"],
            calls=0,
            automerge=os.environ.get("ROLLING_AUTOMERGE") == "1",
        )
    except (pull_request.PullRequestError, ProposalError) as exc:
        # Le dépouillement était juste : la panne est de notre côté, le bot ne doit rien changer.
        message = f"⚠️ Dépouillement vérifié ({summary}), mais la publication a échoué : {exc}"
        print(message)
        if args.post:
            comment(repo, args.issue, token, message + "\n\nRien à corriger côté bot : on relance de notre côté.")
        return 1
    state = "fusionnée" if created.merged else "ouverte, à relire"
    message = (
        f"✅ {len(proposal.polls)} tableau(x) vérifié(s) : {summary}. PR [#{created.number}]({created.url}) {state}."
    )
    print(message)
    if args.post:
        comment(repo, args.issue, token, message)
    return 0


if __name__ == "__main__":
    sys.exit(main())

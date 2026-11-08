#!/usr/bin/env python3
"""Guet des rapports d'instituts : leurs PDF d'intentions de vote, avant la notice.

La Commission des sondages met une notice en ligne de quelques heures à deux jours après
la publication du sondage (relevé du 8 novembre 2026). Plusieurs instituts déposent le
rapport sur leur propre site dès sa sortie, et leur WordPress le liste dans une API publique
(`/wp-json/wp/v2/media`) : le rapport de la vague 9 du baromètre Toluna Harris Interactive
pour M6 et RTL y était le 6 novembre, sa notice n'était pas en ligne le 8.

Ce guet lit cette API pour quelques instituts, garde les PDF dont le nom ou le titre dit des
intentions de vote à la présidentielle, et ouvre pour chacun une issue `new-poll` qui pointe
vers le rapport (marqueur `<!-- poll-report: URL -->`) : le dépouillement habituel
(mine_poll.py) le lit alors à la place d'une notice. Quand la notice arrive ensuite, ses
tableaux identiques se rattachent aux mêmes lignes (`proposal.awaits_notice`).

Un rapport n'est pris que s'il est public : son article est publié sur le site, ou la date de
son nom est arrivée (un rapport déposé avant sa date de publication attend).

    python check_institute_reports.py                 # aperçu, n'écrit rien
    python check_institute_reports.py --create-issues # CI : issues, dispatch, état mis à jour
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from check_new_polls import _github_request, trigger_llm_triage
from mining.notice import USER_AGENT

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".institute_reports.json"
PARIS = ZoneInfo("Europe/Paris")
TIMEOUT = 20
# Un rapport plus vieux que deux semaines a eu sa notice : le guet de la Commission l'a.
MAX_AGE_DAYS = 14
PER_PAGE = 30
DEFAULT_LIMIT = 5

REPORT_MARKER = "<!-- poll-report: {url} -->"
REPORT_MARKER_RE = re.compile(r"<!-- poll-report: (https://[^\s>]+) -->")
FILE_MARKER = "<!-- poll-file: {name} -->"
# Ce qui vient du site d'un institut entre dans le corps d'une issue, à côté des marqueurs que
# lit le dépouillement : un nom ou une adresse qui pourrait en fermer un ou en ouvrir un autre
# (« --> », « < », une espace) est écarté.
SAFE_NAME_RE = re.compile(r"[A-Za-z0-9._-]+\.pdf", re.IGNORECASE)
SAFE_URL_RE = re.compile(r"https://[^\s<>\"]+")


@dataclass(frozen=True)
class Institute:
    """Un institut, son site WordPress et ce qui, dans un nom de rapport, dit le sondage."""

    name: str  # nom_institut de polls.csv : l'extraction E2 doit le retrouver tel quel
    site: str
    include: re.Pattern


INSTITUTES = (
    Institute(
        "Harris Interactive",
        "tolunacorporate.com",
        re.compile(r"barometre-presidentielle-20\d\d|intentions-de-vote-a-l(a|-?election)-presidentielle"),
    ),
    # Le baromètre de l'élection présidentielle ; les sondages pour LCI ne sont pas sur le site.
    Institute("IFOP", "www.ifop.com", re.compile(r"barometre-de-l-?election-presidentielle|intentions-de-vote")),
    Institute("ELABE", "elabe.fr", re.compile(r"intentions-de-vote|election-presidentielle|presidentielle-20\d\d")),
    Institute(
        "Cluster17",
        "cluster17.com",
        re.compile(r"intentions-de-vote-p\d\d|sondage-election-presidentielle-20\d\d|barometre-politico"),
    ),
)
HOSTS = tuple(institute.site for institute in INSTITUTES)
# Ce qui parle de la présidentielle sans en mesurer le premier tour.
EXCLUDE = re.compile(
    r"legislativ|municipal|primaire|europeen|potentiel|plaidoyer|laicite|sante|droit-animal|regard|offre|"
    r"communique|-ia-|intelligence-artificielle"
)
MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}


def normalize(text):
    """Minuscules sans accents, `_` et espaces en tirets : « Baromètre_Présidentielle » → « barometre-presidentielle »."""
    text = unicodedata.normalize("NFKD", unquote(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"&#?\w+;", " ", text)
    return re.sub(r"[\s_’'–—]+", "-", text)


def report_name(url):
    """Le nom du PDF, tel que la colonne `filename` le gardera."""
    return unquote(Path(urlparse(url).path).name)


COPY_RE = re.compile(r"^(?P<stem>.+)-\d{1,2}\.pdf$")


def dedup_key(institute, name, siblings=()):
    """Un même rapport déposé deux fois (« …-9-novembre-2026.pdf » et « …-2026-1.pdf ») compte une fois.

    WordPress n'ajoute « -1 » qu'à un nom déjà pris : le suffixe ne se retire que si le nom
    sans lui est aussi là (`siblings`, les noms normalisés de la liste). « Vague-8.pdf » et
    « Vague-9.pdf » restent ainsi deux rapports.
    """
    text = normalize(name)
    copy = COPY_RE.match(text)
    if copy and f"{copy.group('stem')}.pdf" in siblings:
        text = f"{copy.group('stem')}.pdf"
    return f"{institute.name}:{text}"


def allowed_report_url(url):
    """Un rapport ne se télécharge qu'en https, depuis le site d'un institut guetté."""
    if not SAFE_URL_RE.fullmatch(url or ""):
        return False
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == allowed or host.endswith("." + allowed) for allowed in HOSTS)


def relevant(institute, name, title=""):
    text = normalize(f"{name} {title}")
    return bool(institute.include.search(text)) and not EXCLUDE.search(text)


def publication_day(name):
    """La date que porte le nom du rapport, ou None : « 9-novembre-2026 », « 20261105_ », « 08042025_ »."""
    text = normalize(name)
    found = re.search(r"(?<!\d)(\d{1,2})-(" + "|".join(MONTHS) + r")-(20\d\d)(?!\d)", text)
    candidates = []
    if found:
        candidates.append((int(found.group(3)), MONTHS[found.group(2)], int(found.group(1))))
    for match in re.finditer(r"(?<!\d)(20\d\d)(\d\d)(\d\d)(?!\d)", text):
        candidates.append((int(match.group(1)), int(match.group(2)), int(match.group(3))))
    for match in re.finditer(r"(?<!\d)(\d\d)(\d\d)(20\d\d)(?!\d)", text):
        candidates.append((int(match.group(3)), int(match.group(2)), int(match.group(1))))
    for match in re.finditer(r"(?<!\d)(20\d\d)\.(\d\d)\.(\d\d)(?!\d)", text):
        candidates.append((int(match.group(1)), int(match.group(2)), int(match.group(3))))
    for year, month, day in candidates:
        try:
            return dt.date(year, month, day)
        except ValueError:
            continue
    return None


def fetch_json(url):
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def media_url(institute, since):
    query = {
        "mime_type": "application/pdf",
        "per_page": PER_PAGE,
        "orderby": "date",
        "order": "desc",
        "after": since.strftime("%Y-%m-%dT%H:%M:%S"),
        "_fields": "id,date,post,source_url,title",
    }
    return f"https://{institute.site}/wp-json/wp/v2/media?{urlencode(query)}"


def published(institute, media, today, fetch=fetch_json):
    """(public, lien de l'article, raison) : un rapport n'est pris qu'une fois public.

    Son article publié le dit ; sans article lisible, la date que porte son nom doit être
    arrivée. Toluna dépose ses PDF sans article, parfois avant leur date (la vague 9, datée du
    9 novembre, chargée le 6) : ils attendent leur jour.
    """
    post = media.get("post")
    if post:
        for kind in ("posts", "pages"):
            try:
                found = fetch(f"https://{institute.site}/wp-json/wp/v2/{kind}/{int(post)}?_fields=status,link")
            except HTTPError as exc:
                if exc.code in (401, 403, 404):
                    continue
                raise
            if found.get("status") == "publish":
                link = found.get("link") or ""
                return True, link if SAFE_URL_RE.fullmatch(link) else None, "article publié"
    day = publication_day(report_name(media.get("source_url", "")))
    if day and day <= today:
        return True, None, f"daté du {day.isoformat()}"
    if day:
        return False, None, f"daté du {day.isoformat()}, pas encore paru"
    return False, None, "ni article publié ni date dans son nom"


def load_state(path=STATE_FILE):
    if not Path(path).exists():
        return {"seen": {}}
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    state.setdefault("seen", {})
    return state


def save_state(state, path=STATE_FILE):
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def recorded_filenames(root=ROOT):
    import csv

    with (Path(root) / "polls.csv").open(encoding="utf-8", newline="") as handle:
        return {(row.get("filename") or "").strip() for row in csv.DictReader(handle)}


def find_reports(now, state, fetch=fetch_json, recorded=frozenset(), log=print):
    """Les rapports publics, pas encore vus, du plus ancien au plus récent."""
    today = now.astimezone(PARIS).date()
    since = now - dt.timedelta(days=MAX_AGE_DAYS)
    found = []
    queued = set()
    for institute in INSTITUTES:
        try:
            items = fetch(media_url(institute, since))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            log(f"⚠️  {institute.name} ({institute.site}) injoignable : {exc}")
            continue
        items = items if isinstance(items, list) else []
        siblings = {normalize(report_name(media.get("source_url") or "")) for media in items}
        for media in items:
            url = media.get("source_url") or ""
            name = report_name(url)
            title = (media.get("title") or {}).get("rendered", "")
            if not allowed_report_url(url) or not SAFE_NAME_RE.fullmatch(name) or "--" in name:
                continue
            key = dedup_key(institute, name, siblings)
            if key in state["seen"] or key in queued or name in recorded or not relevant(institute, name, title):
                continue
            # Une copie (« …-1.pdf ») n'est examinée qu'une fois, publique ou non.
            queued.add(key)
            try:
                public, link, why = published(institute, media, today, fetch)
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                log(f"⚠️  {name} : article illisible ({exc})")
                continue
            if not public:
                log(f"⏳ {institute.name} · {name} : en attente ({why})")
                continue
            found.append(
                {
                    "key": key,
                    "institute": institute.name,
                    "name": name,
                    "url": url,
                    "article": link,
                    "why": why,
                    "uploaded": media.get("date", ""),
                }
            )
    return sorted(found, key=lambda item: item["uploaded"])


def build_issue(report):
    title = f"📊 Nouveau sondage (rapport {report['institute']}) : {report['name']}"
    lines = [
        f"Rapport de **{report['institute']}** trouvé sur le site de l'institut, avant la notice de la"
        " Commission des sondages.",
        "",
        f"- Rapport : {report['url']}",
        f"- Article : {report['article'] or 'aucun article rattaché'}",
        f"- Déposé le : {report['uploaded'][:10]}",
        f"- Public : {report['why']}",
        "",
        "Le dépouillement part de ce rapport. Quand la notice arrivera, ses tableaux identiques se"
        " rattacheront aux mêmes lignes de `polls.csv`, sans les ajouter une seconde fois.",
        "",
        FILE_MARKER.format(name=report["name"]),
        REPORT_MARKER.format(url=report["url"]),
    ]
    return title, "\n".join(lines) + "\n"


def create_issue(report, repo, token):
    title, body = build_issue(report)
    payload = {"title": title, "body": body, "labels": ["new-poll", "automated", "rapport-institut"]}
    return _github_request(f"https://api.github.com/repos/{repo}/issues", token, "POST", payload)


def run(create_issues, repo, token, limit, now=None, fetch=fetch_json, state_path=STATE_FILE, root=ROOT):
    now = now or dt.datetime.now(dt.timezone.utc)
    state = load_state(state_path)
    reports = find_reports(now, state, fetch, recorded_filenames(root))
    if not reports:
        print("✅ Aucun nouveau rapport public d'intentions de vote.")
        return 0
    for report in reports[:limit]:
        if not create_issues:
            print(f"🔎 {report['institute']} · {report['name']} ({report['why']}) → {report['url']}")
            continue
        issue = create_issue(report, repo, token)
        state["seen"][report["key"]] = {"issue": issue["number"], "url": report["url"], "at": now.isoformat()}
        save_state(state, state_path)
        print(f"✅ Issue #{issue['number']} : {report['institute']} · {report['name']}")
        trigger_llm_triage(repo, token, issue["number"], os.environ.get("GITHUB_REF_NAME") or "main")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--create-issues", action="store_true", help="ouvre les issues et lance le dépouillement")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)
    repo = os.environ.get("GITHUB_REPOSITORY", "EnzoSim/rolling-2027")
    token = os.environ.get("GITHUB_TOKEN")
    if args.create_issues and not token:
        print("❌ --create-issues demande GITHUB_TOKEN")
        return 1
    return run(args.create_issues, repo, token, args.limit)


if __name__ == "__main__":
    sys.exit(main())

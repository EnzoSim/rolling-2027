"""Guet des rapports d'instituts : filtres, embargo, dédoublonnage, issues (sans réseau)."""

import datetime as dt
from urllib.error import HTTPError

import pytest

import check_institute_reports as cir
import mine_poll

TOLUNA, IFOP, ELABE, CLUSTER = cir.INSTITUTES
V9 = "Rapport-Toluna-Barometre-Presidentielle-2027-Vague-9-M6-RTL-9-novembre-2026.pdf"
UPLOADS = "https://tolunacorporate.com/wp-content/uploads/2026/11/"
NOW = dt.datetime(2026, 11, 8, 5, 0, tzinfo=dt.timezone.utc)  # dimanche 8 novembre, 6 h à Paris


@pytest.mark.parametrize(
    "institute, name",
    [
        (TOLUNA, V9),
        (TOLUNA, "Rapport-Toluna-Harris-Interactive-Intentions-de-vote-a-la-presidentielle-de-2027-Mars-2026.pdf"),
        (IFOP, "122853-barometre-de-lelection-presidentielle-vague-7-resultats-densemble.pdf"),
        (ELABE, "les-francais-et-lelection-presidentielle-2026.pdf"),
        (ELABE, "20260829_elabe_bfmtv_la-tribune-dimanche_les-francais-et-lelection-presidentielle-2027.pdf"),
        (CLUSTER, "Intentions-de-vote-P27-Politico-Septembre-26.pdf"),
        (CLUSTER, "Barometre_Politico_Cluster17_octobre_2026.pdf"),
        (CLUSTER, "C17_Le_Point_Sondage_Election_Presidentielle_2027_Sep26-.pdf"),
    ],
)
def test_un_rapport_d_intentions_de_vote_est_retenu(institute, name):
    assert cir.relevant(institute, name)


@pytest.mark.parametrize(
    "institute, name",
    [
        (TOLUNA, "Rapport-Toluna-Suivi-du-potentiel-de-vote-a-la-presidentielle-Commstrat-V9-Octobre-2026.pdf"),
        (TOLUNA, "Rapport-Toluna-Intentions-de-vote-aux-elections-legislatives-en-cas-de-dissolution.pdf"),
        (IFOP, "ifop-pour-la-fondation-droit-animal-le-droit-animal-a-laune-de-lelection-presidentielle.pdf"),
        (IFOP, "122678_-ifop_cnosf-plaidoyer-pour-la-presidentielle-2027-barometre.pdf"),
        (IFOP, "122860-ifop-asteres-barometre-2026.pdf"),
        (ELABE, "20261105_les_echos_observatoire-politique.pdf"),
        (ELABE, "08042025_elabe_bfmlyon_bfmtv_municipale-lyon-2026.pdf"),
    ],
)
def test_ce_qui_ne_mesure_pas_le_premier_tour_est_ecarte(institute, name):
    assert not cir.relevant(institute, name)


def test_le_titre_du_media_compte_aussi():
    # Un PDF au nom générique (« 122361-rapport.pdf ») dont le titre dit le baromètre.
    assert cir.relevant(IFOP, "122361-rapport.pdf", "Baromètre de l&rsquo;élection présidentielle &#8211; vague 8")


@pytest.mark.parametrize(
    "name, day",
    [
        (V9, dt.date(2026, 11, 9)),
        ("Rapport-Toluna-Barometre-Presidentielle-2027-Vague-9-M6-RTL-9-novembre-2026-1.pdf", dt.date(2026, 11, 9)),
        ("Rapport-Toluna-Barometre-Presidentielle-2027-Vague-8-M6-RTL-23-octobre-2026-1.pdf", dt.date(2026, 10, 23)),
        ("20261105_elabe_les-echos_les-francais-et-lenseignement-superieur.pdf", dt.date(2026, 11, 5)),
        ("08042025_elabe_bfmlyon_bfmtv_municipale-lyon-2026.pdf", dt.date(2025, 4, 8)),
        ("122804_synthese_ifop-marianne_laicite_presidentielle_2026.10.12.pdf", dt.date(2026, 10, 12)),
        ("les-francais-et-lelection-presidentielle-2026.pdf", None),
        ("Rapport-Toluna-Barometre-Presidentielle-2027-Vague-4-M6-RTL-Aout-2026.pdf", None),
    ],
)
def test_la_date_que_porte_le_nom(name, day):
    assert cir.publication_day(name) == day


def test_une_copie_wordpress_compte_pour_un_seul_rapport():
    copy = V9[:-4] + "-1.pdf"
    both = {cir.normalize(V9), cir.normalize(copy)}
    assert cir.dedup_key(TOLUNA, V9, both) == cir.dedup_key(TOLUNA, copy, both)
    # Sans l'original dans la liste, « -1 » fait partie du nom ; et deux vagues restent deux.
    assert cir.dedup_key(TOLUNA, copy) != cir.dedup_key(TOLUNA, V9)
    waves = {"vague-8.pdf", "vague-9.pdf"}
    assert cir.dedup_key(TOLUNA, "Vague-8.pdf", waves) != cir.dedup_key(TOLUNA, "Vague-9.pdf", waves)


def _fetch(routes):
    def fetch(url):
        for prefix, answer in routes.items():
            if url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise HTTPError(url, 404, "absent", {}, None)

    return fetch


def _denied(url):
    return HTTPError(url, 401, "brouillon", {}, None)


def test_un_rapport_n_est_pris_qu_une_fois_public():
    today = NOW.date()
    # Toluna : pas d'article, la date du nom fait foi.
    assert cir.published(TOLUNA, {"source_url": UPLOADS + V9, "post": None}, today, _fetch({}))[0] is False
    assert cir.published(TOLUNA, {"source_url": UPLOADS + V9, "post": None}, dt.date(2026, 11, 9), _fetch({}))[0]
    # IFOP : l'article publié suffit, un brouillon (401) renvoie à la date, absente ici.
    media = {"source_url": "https://www.ifop.com/wp-content/uploads/2026/11/122999-rapport.pdf", "post": 97400}
    posts = "https://www.ifop.com/wp-json/wp/v2/posts/97400"
    public = cir.published(IFOP, media, today, _fetch({posts: {"status": "publish", "link": "https://ifop/a"}}))
    assert public == (True, "https://ifop/a", "article publié")
    draft = cir.published(IFOP, media, today, _fetch({posts: _denied(posts)}))
    assert draft == (False, None, "ni article publié ni date dans son nom")


def _media(name, date, site=UPLOADS, post=None, title=""):
    return {"source_url": site + name, "date": date, "post": post, "title": {"rendered": title}}


def test_le_guet_trie_dedoublonne_et_survit_a_un_site_en_panne():
    listing = [
        _media(V9, "2026-11-06T10:00:00"),
        _media(V9[:-4] + "-1.pdf", "2026-11-06T10:01:00"),
        _media(
            "Rapport-Toluna-Barometre-Presidentielle-2027-Vague-8-M6-RTL-23-octobre-2026-1.pdf", "2026-10-22T09:00:00"
        ),
        _media("Rapport-Toluna-Suivi-du-potentiel-de-vote-a-la-presidentielle.pdf", "2026-11-01T09:00:00"),
        _media("Barometre-Presidentielle-2027-Vague-7.pdf", "2026-10-09T09:00:00", site="https://ailleurs.example/"),
    ]
    elabe = [
        _media(
            "20261107_elabe_bfmtv_election-presidentielle-2027.pdf",
            "2026-11-07T08:00:00",
            site="https://elabe.fr/wp-content/uploads/2026/11/",
        )
    ]
    fetch = _fetch(
        {
            "https://tolunacorporate.com/wp-json/wp/v2/media": listing,
            "https://www.ifop.com/wp-json/wp/v2/media": OSError("certificat"),
            "https://elabe.fr/wp-json/wp/v2/media": elabe,
        }
    )
    messages = []
    found = cir.find_reports(NOW, {"seen": {}}, fetch, log=messages.append)
    assert [(item["institute"], item["name"]) for item in found] == [
        ("Harris Interactive", "Rapport-Toluna-Barometre-Presidentielle-2027-Vague-8-M6-RTL-23-octobre-2026-1.pdf"),
        ("ELABE", "20261107_elabe_bfmtv_election-presidentielle-2027.pdf"),
    ]
    assert any("IFOP" in line and "injoignable" in line for line in messages)
    assert sum("pas encore paru" in line for line in messages) == 1, "la vague 9 attend son jour, une seule fois"
    # Déjà vu ou déjà dans polls.csv : rien.
    seen = {"seen": {found[0]["key"]: {}}}
    again = cir.find_reports(NOW, seen, fetch, recorded={found[1]["name"]}, log=lambda _: None)
    assert again == []


def test_l_issue_porte_le_rapport_et_mine_poll_le_lit():
    report = {
        "key": "k",
        "institute": "Harris Interactive",
        "name": V9,
        "url": UPLOADS + V9,
        "article": None,
        "why": "daté du 2026-11-09",
        "uploaded": "2026-11-06T10:00:00",
    }
    title, body = cir.build_issue(report)
    assert title.startswith("📊 Nouveau sondage (rapport Harris Interactive)")
    assert mine_poll.poll_filename_from_body(body) == V9
    assert mine_poll.report_url_from_body(body) == UPLOADS + V9
    assert mine_poll.report_url_from_body("<!-- poll-file: 10351-pres-iv-ifop-lci-3-novembre.pdf -->") is None


def test_run_ouvre_l_issue_lance_le_depouillement_et_retient_le_rapport(monkeypatch, tmp_path):
    (tmp_path / "polls.csv").write_text("poll_id,filename\n", encoding="utf-8")
    state = tmp_path / ".institute_reports.json"
    calls = []
    monkeypatch.setattr(
        cir, "create_issue", lambda report, repo, token: calls.append(("issue", report)) or {"number": 41}
    )
    monkeypatch.setattr(cir, "trigger_llm_triage", lambda repo, token, number, ref: calls.append(("dispatch", number)))
    fetch = _fetch(
        {
            "https://tolunacorporate.com/wp-json/wp/v2/media": [
                _media("Rapport-Toluna-Barometre-Presidentielle-2027-Vague-8-M6-RTL-23-octobre-2026.pdf", "2026-10-22")
            ]
        }
    )
    assert cir.run(True, "EnzoSim/rolling-2027", "t", 5, now=NOW, fetch=fetch, state_path=state, root=tmp_path) == 0
    assert [kind for kind, _ in calls] == ["issue", "dispatch"]
    saved = cir.load_state(state)["seen"]
    assert list(saved.values())[0]["issue"] == 41
    calls.clear()
    assert cir.run(True, "EnzoSim/rolling-2027", "t", 5, now=NOW, fetch=fetch, state_path=state, root=tmp_path) == 0
    assert calls == [], "un rapport retenu ne rouvre jamais d'issue"


def test_un_rapport_ne_se_telecharge_que_chez_un_institut_guette():
    assert cir.allowed_report_url(UPLOADS + V9)
    assert not cir.allowed_report_url("http://tolunacorporate.com/x.pdf")
    assert not cir.allowed_report_url("https://tolunacorporate.com.evil.example/x.pdf")
    with pytest.raises(mine_poll.NoticeUnavailable):
        mine_poll.report_text_for("https://exemple.test/rapport.pdf")


@pytest.mark.parametrize(
    "automerge, reports, has_report, expected",
    [
        ("1", None, False, True),
        ("1", None, True, False),
        ("1", "1", True, True),
        ("0", "1", True, False),
        (None, None, False, False),
    ],
)
def test_une_pr_tiree_d_un_rapport_reste_un_brouillon_par_defaut(monkeypatch, automerge, reports, has_report, expected):
    for name, value in (("ROLLING_AUTOMERGE", automerge), ("ROLLING_REPORT_AUTOMERGE", reports)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    monkeypatch.setattr(mine_poll, "issue_report_url", lambda *args: UPLOADS + V9 if has_report else None)
    assert mine_poll.automerge_allowed("EnzoSim/rolling-2027", 41, "t") is expected

"""Garde-fous du déclenchement automatique de triage après création d'issue."""

import check_new_polls


def test_trigger_llm_triage_declenche_le_workflow_avec_issue_et_mode(monkeypatch):
    called = {}

    def fake_request(url, token, method="GET", payload=None):
        called.update(url=url, token=token, method=method, payload=payload)
        return {}

    monkeypatch.setattr(check_new_polls, "_github_request", fake_request)

    check_new_polls.trigger_llm_triage("MieuxVoter/presidentielle2027", "token-test", 211, "main")

    assert called == {
        "url": "https://api.github.com/repos/MieuxVoter/presidentielle2027/actions/workflows/llm-mining.yml/dispatches",
        "token": "token-test",
        "method": "POST",
        "payload": {"ref": "main", "inputs": {"issue": "211", "mode": "mining-pr"}},
    }


def test_run_create_issues_declenche_triage_pour_chaque_issue(monkeypatch):
    catalog = [{"filename": "old.pdf"}, {"filename": "new-1.pdf"}, {"filename": "new-2.pdf"}]
    new_polls = [{"filename": "new-1.pdf"}, {"filename": "new-2.pdf"}]

    monkeypatch.setattr(check_new_polls, "find_new_polls", lambda _limit: (catalog, new_polls))
    monkeypatch.setattr(check_new_polls, "get_existing_issues", lambda _repo, _token: set())
    monkeypatch.setattr(check_new_polls, "load_template", lambda: object())

    created = iter([101, 102])
    monkeypatch.setattr(
        check_new_polls,
        "create_issue",
        lambda _poll, _repo, _token, _template: {"number": next(created), "title": "issue"},
    )

    dispatched = []
    monkeypatch.setattr(
        check_new_polls, "trigger_llm_triage", lambda _repo, _token, number, ref: dispatched.append((number, ref))
    )

    saved = []
    monkeypatch.setattr(check_new_polls, "save_poll_count", lambda count: saved.append(count))
    monkeypatch.setenv("GITHUB_REF_NAME", "main")

    assert check_new_polls.run_create_issues("MieuxVoter/presidentielle2027", "token-test", 10) == 0
    assert dispatched == [(101, "main"), (102, "main")]
    assert saved == [len(catalog)]


def test_rolling_2027_garde_les_notices_rangees_en_primaire(monkeypatch):
    """10314 (IFOP pour LCI, 14 octobre 2026) est classée « Prim » mais contient des IV."""
    import check_new_polls as cnp

    catalog = (
        "filename,categorie\n10313-pres-blocus.pdf,Pres\n10314-pres-climat-post-primaire-ifop-lci.pdf,Prim\nx.pdf,Leg\n"
    )

    class _Reponse:
        def __init__(self, text):
            self.text = text

        def read(self):
            return self.text.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cnp, "urlopen", lambda url, timeout=None: _Reponse(catalog))
    names = [row["filename"] for row in cnp.get_catalog_polls()]
    assert names == ["10313-pres-blocus.pdf", "10314-pres-climat-post-primaire-ifop-lci.pdf"]


def _issues_setup(monkeypatch, catalog, new_polls, fail_on=()):
    monkeypatch.setattr(check_new_polls, "find_new_polls", lambda _limit: (catalog, new_polls))
    monkeypatch.setattr(check_new_polls, "get_existing_issues", lambda _repo, _token: set())
    monkeypatch.setattr(check_new_polls, "load_template", lambda: object())
    numbers = iter(range(200, 300))
    created = []

    def fake_create(poll, _repo, _token, _template):
        if poll["filename"] in fail_on:
            raise RuntimeError("API indisponible")
        created.append(poll["filename"])
        return {"number": next(numbers), "title": poll["filename"]}

    monkeypatch.setattr(check_new_polls, "create_issue", fake_create)
    monkeypatch.setattr(check_new_polls, "trigger_llm_triage", lambda *_args: None)
    saved = []
    monkeypatch.setattr(check_new_polls, "save_poll_count", lambda count: saved.append(count))
    return created, saved


def test_la_limite_garde_le_reste_pour_le_passage_suivant(monkeypatch):
    """rolling-2027 : au-delà de la limite, le compteur n'avance que sur les notices traitées."""
    catalog = [{"filename": f"{n}.pdf"} for n in range(1, 8)]
    created, saved = _issues_setup(monkeypatch, catalog, catalog[2:])

    assert check_new_polls.run_create_issues("EnzoSim/rolling-2027", "token-test", 3) == 0
    assert created == ["3.pdf", "4.pdf", "5.pdf"]
    assert saved == [5]


def test_un_echec_arrete_le_compteur_avant_la_notice(monkeypatch):
    catalog = [{"filename": f"{n}.pdf"} for n in range(1, 6)]
    created, saved = _issues_setup(monkeypatch, catalog, catalog[1:], fail_on={"3.pdf"})

    assert check_new_polls.run_create_issues("EnzoSim/rolling-2027", "token-test", 10) == 0
    assert created == ["2.pdf"]
    assert saved == [2]


def test_un_declenchement_sans_corps_ne_leve_pas(monkeypatch):
    """Un dispatch de workflow répond 204 sans corps : ce n'est pas une erreur."""

    class _Vide:
        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(check_new_polls, "urlopen", lambda request, timeout=None: _Vide())
    assert check_new_polls._github_request("https://api.github.com/x", "token-test", "POST", {}) is None

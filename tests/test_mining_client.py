"""Sélection des fournisseurs et plafonds. Aucun appel réseau."""

import pytest

from mining import client as llm


def test_aucun_fournisseur_sans_cle():
    assert llm.providers_from_env({}) == ()


def test_un_fournisseur_par_cle_presente():
    providers = llm.providers_from_env({"MISTRAL_API_KEY": "k"})
    assert [p.name for p in providers] == ["mistral"]
    assert providers[0].api_key == "k"


def test_ordre_par_defaut_openrouter_en_tete():
    env = {"GEMINI_API_KEY": "g", "OPENROUTER_API_KEY": "o", "MISTRAL_API_KEY": "m"}
    assert [p.name for p in llm.providers_from_env(env)] == ["openrouter", "mistral", "gemini"]


def test_ordre_impose_par_llm_providers():
    env = {"OPENROUTER_API_KEY": "o", "MISTRAL_API_KEY": "m", "LLM_PROVIDERS": "mistral,openrouter"}
    assert [p.name for p in llm.providers_from_env(env)] == ["mistral", "openrouter"]


def test_llm_providers_ignore_un_fournisseur_sans_cle():
    env = {"MISTRAL_API_KEY": "m", "LLM_PROVIDERS": "openrouter,mistral"}
    assert [p.name for p in llm.providers_from_env(env)] == ["mistral"]


def test_liste_de_modeles_surchargeable():
    env = {"OPENROUTER_API_KEY": "o", "OPENROUTER_MODELS": "a:free, b:free"}
    assert llm.providers_from_env(env)[0].models == ("a:free", "b:free")


def test_modeles_par_defaut_non_vides():
    providers = llm.providers_from_env({"OPENROUTER_API_KEY": "o"})
    assert providers[0].models and all(providers[0].models)


def test_base_url_surchargeable():
    env = {"MISTRAL_API_KEY": "m", "MISTRAL_BASE_URL": "https://exemple.test/v1"}
    assert llm.providers_from_env(env)[0].base_url == "https://exemple.test/v1"


def test_plafond_d_appels_leve_budget_exceeded():
    conversation = llm.Client(providers=(), max_calls=0)
    with pytest.raises(llm.BudgetExceeded):
        conversation.ask("sys", "question")


def test_plafond_de_tokens_leve_budget_exceeded():
    conversation = llm.Client(providers=(), max_tokens=0)
    with pytest.raises(llm.BudgetExceeded):
        conversation.ask("sys", "question")


def test_sans_fournisseur_on_leve_llm_error():
    conversation = llm.Client(providers=())
    with pytest.raises(llm.LLMError):
        conversation.ask("sys", "question")


def _corps(contenu, finish_reason="stop"):
    return {
        "model": "m",
        "usage": {"total_tokens": 10},
        "choices": [{"message": {"content": contenu}, "finish_reason": finish_reason}],
    }


def _client_factice(monkeypatch, post):
    conversation = llm.Client(providers=(llm.Provider("fake", "https://x.test", "k", ("m",)),))
    monkeypatch.setattr(conversation, "_post", post)
    return conversation


def test_finish_reason_length_marque_la_reponse_tronquee(monkeypatch):
    conversation = _client_factice(monkeypatch, lambda provider, payload: _corps("Page 33…", "length"))
    answer = conversation.ask("sys", "q")
    assert answer.truncated is True
    assert answer.text == "Page 33…"


def test_reponse_complete_non_tronquee(monkeypatch):
    conversation = _client_factice(monkeypatch, lambda provider, payload: _corps("OUI\nPAGES: 3"))
    assert conversation.ask("sys", "q").truncated is False


def test_reponse_tronquee_vide_rendue_sans_rejouer(monkeypatch):
    # Rejouer au même budget redonnerait la même coupure : c'est à l'étape de décider.
    appels = []

    def post(provider, payload):
        appels.append(payload)
        return _corps("", "length")

    answer = _client_factice(monkeypatch, post).ask("sys", "q")
    assert answer.truncated is True
    assert len(appels) == 1


def test_openrouter_recoit_au_plus_trois_modeles(monkeypatch):
    # Au-delà, OpenRouter refuse toute la requête : HTTP 400, « 'models' array
    # must have 3 items or fewer ». Constaté sous l'issue #194.
    modeles = ("a:free", "b:free", "c:free", "d:free", "e:free")
    conversation = llm.Client(providers=(llm.Provider("openrouter", "https://x.test", "k", modeles),))
    envoyes = []

    def post(provider, payload):
        envoyes.append(payload)
        return _corps("OUI\nPAGES: 3")

    monkeypatch.setattr(conversation, "_post", post)
    conversation.ask("sys", "q")
    assert envoyes[0]["models"] == ["a:free", "b:free", "c:free"]
    assert envoyes[0]["model"] == "a:free"


def test_contenu_vide_avec_raisonnement_vaut_troncature(monkeypatch):
    # Cas réel, E3 sur l'issue #194 : le raisonnement épuise max_tokens, le contenu
    # revient vide avec finish_reason « stop ». Ce n'est pas une « réponse vide » à
    # rejouer au même budget, mais un manque de place à signaler.
    appels = []

    def post(provider, payload):
        appels.append(payload)
        return {
            "model": "m",
            "usage": {"total_tokens": 4000},
            "choices": [{"message": {"content": "", "reasoning": "Line11: ..."}, "finish_reason": "stop"}],
        }

    answer = _client_factice(monkeypatch, post).ask("sys", "q")
    assert answer.truncated is True and answer.text == ""
    assert len(appels) == 1


def test_contenu_vide_sans_raisonnement_reste_une_reponse_vide(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    appels = []

    def post(provider, payload):
        appels.append(payload)
        return _corps("")

    conversation = _client_factice(monkeypatch, post)
    # Le diagnostic doit dire quel modèle a rendu le vide, pour les logs du job.
    with pytest.raises(llm.LLMError, match=r"réponse vide \(modèle m, finish_reason stop, sans raisonnement\)"):
        conversation.ask("sys", "q")
    assert len(appels) == llm.ATTEMPTS


def test_reponse_vide_retentee_avec_un_autre_modele_de_tete(monkeypatch):
    # Cas réel, issue #194 : réponses vides intermittentes d'OpenRouter.
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    modeles = ("a:free", "b:free", "c:free")
    conversation = llm.Client(providers=(llm.Provider("openrouter", "https://x.test", "k", modeles),))
    envoyes = []

    def post(provider, payload):
        envoyes.append(payload)
        return _corps("" if len(envoyes) == 1 else "OUI\nPAGES: 3")

    monkeypatch.setattr(conversation, "_post", post)
    assert conversation.ask("sys", "q").text == "OUI\nPAGES: 3"
    assert [p["model"] for p in envoyes] == ["a:free", "b:free"]
    assert envoyes[1]["models"] == ["b:free", "c:free", "a:free"]


def _http_429(headers):
    from urllib.error import HTTPError

    def fake_urlopen(request, timeout=None):
        fake_urlopen.calls += 1
        raise HTTPError(request.full_url, 429, "Too Many Requests", headers, None)

    fake_urlopen.calls = 0
    return fake_urlopen


def test_quota_journalier_epuise_n_est_pas_retente(monkeypatch):
    # Cas réel, issue #194 : « free-models-per-day », 50 requêtes par jour.
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    fake = _http_429({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1789430400000"})
    monkeypatch.setattr(llm, "urlopen", fake)
    conversation = llm.Client(providers=(llm.Provider("openrouter", "https://x.test", "k", ("m",)),))
    # Tous les fournisseurs à court de quota : QuotaExhausted, pour arrêter les pages suivantes.
    with pytest.raises(llm.QuotaExhausted, match=r"quota épuisé chez openrouter \(remise à zéro 00:00 UTC\)"):
        conversation.ask("sys", "q")
    assert fake.calls == 1


def test_un_429_passager_reste_retente(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    fake = _http_429({"X-RateLimit-Remaining": "3"})
    monkeypatch.setattr(llm, "urlopen", fake)
    conversation = llm.Client(providers=(llm.Provider("openrouter", "https://x.test", "k", ("m",)),))
    with pytest.raises(llm.LLMError, match="HTTP 429"):
        conversation.ask("sys", "q")
    assert fake.calls == llm.ATTEMPTS


# --- rolling-2027 : Claude par le SDK officiel (faux module, aucun appel réseau) ---

import sys
import types


class _Bloc:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class _Reponse:
    def __init__(self, blocs, stop_reason="end_turn", model="claude-opus-5-5"):
        self.content = blocs
        self.stop_reason = stop_reason
        self.stop_details = None
        self.model = model
        self.usage = types.SimpleNamespace(input_tokens=100, output_tokens=20)


def _faux_anthropic(monkeypatch, reponse, appels):
    module = types.ModuleType("anthropic")

    class _Erreur(Exception):
        status_code = 500

    module.RateLimitError = type("RateLimitError", (_Erreur,), {"status_code": 429})
    module.APIStatusError = _Erreur
    module.APIConnectionError = type("APIConnectionError", (Exception,), {})

    class _Messages:
        def create(self, **kwargs):
            appels.append(kwargs)
            if isinstance(reponse, Exception):
                raise reponse
            return reponse

    class _Anthropic:
        def __init__(self, **kwargs):
            appels.append({"client": kwargs})
            self.beta = types.SimpleNamespace(messages=_Messages())

    module.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return module


def _claude():
    return llm.Client(providers=llm.providers_from_env({"ANTHROPIC_API_KEY": "k"}))


def test_claude_en_tete_quand_sa_cle_est_presente():
    env = {"ANTHROPIC_API_KEY": "a", "OPENROUTER_API_KEY": "o", "MISTRAL_API_KEY": "m"}
    providers = llm.providers_from_env(env)
    assert [p.name for p in providers] == ["anthropic", "openrouter", "mistral"]
    assert providers[0].models == ("claude-opus-5-5",)


def test_claude_sans_temperature_avec_marge_de_reflexion_et_repli(monkeypatch):
    appels = []
    _faux_anthropic(monkeypatch, _Reponse([_Bloc("thinking"), _Bloc("text", "OUI : pages 3, 4")]), appels)
    conversation = _claude()
    answer = conversation.ask("sys", "question", max_tokens=4000)
    requete = appels[-1]
    assert "temperature" not in requete
    assert requete["model"] == "claude-opus-5-5"
    assert requete["max_tokens"] == 4000 + llm.THINKING_HEADROOM
    assert requete["output_config"] == {"effort": "low"}
    assert requete["fallbacks"] == "default"
    assert requete["betas"] == ["server-side-fallback-2026-07-01"]
    assert answer.text == "OUI : pages 3, 4" and answer.provider == "anthropic" and not answer.truncated
    assert conversation.calls == 1 and conversation.tokens == 120


def test_claude_effort_moyen_pour_un_tableau(monkeypatch):
    appels = []
    _faux_anthropic(monkeypatch, _Reponse([_Bloc("text", "candidat,intentions")]), appels)
    _claude().ask("sys", "tableau", max_tokens=6000)
    assert appels[-1]["output_config"] == {"effort": "medium"}


def test_claude_coupe_par_max_tokens_marque_la_reponse_tronquee(monkeypatch):
    _faux_anthropic(monkeypatch, _Reponse([_Bloc("text", "début")], stop_reason="max_tokens"), [])
    assert _claude().ask("sys", "q", max_tokens=6000).truncated


def test_claude_refus_passe_au_fournisseur_suivant(monkeypatch):
    _faux_anthropic(monkeypatch, _Reponse([], stop_reason="refusal"), [])
    with pytest.raises(llm.LLMError):
        _claude().ask("sys", "q")


def test_claude_quota_n_arrete_pas_la_cascade(monkeypatch):
    erreurs = []
    module = _faux_anthropic(monkeypatch, None, [])

    def leve(**kwargs):
        raise module.RateLimitError("trop")

    monkeypatch.setattr(
        module,
        "Anthropic",
        lambda **kw: types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(create=leve))),
    )
    with pytest.raises(llm.LLMError) as excinfo:
        _claude().ask("sys", "q")
    assert not isinstance(excinfo.value, llm.QuotaExhausted)


def test_grok_par_xai_au_format_openai():
    providers = llm.providers_from_env({"XAI_API_KEY": "x"})
    assert [p.name for p in providers] == ["xai"]
    assert providers[0].base_url == "https://api.x.ai/v1" and providers[0].models == ("grok-4.6",)


def test_grok_apres_claude_et_avant_les_gratuits():
    env = {"ANTHROPIC_API_KEY": "a", "XAI_API_KEY": "x", "OPENROUTER_API_KEY": "o"}
    assert [p.name for p in llm.providers_from_env(env)] == ["anthropic", "xai", "openrouter"]


def test_grok_seul_aux_commandes_avec_llm_providers():
    env = {"ANTHROPIC_API_KEY": "a", "XAI_API_KEY": "x", "LLM_PROVIDERS": "xai"}
    assert [p.name for p in llm.providers_from_env(env)] == ["xai"]

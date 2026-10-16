"""Client LLM minimal, compatible OpenAI, avec cascade de fournisseurs.

Un seul format de requête (`POST {base_url}/chat/completions`) suffit pour
OpenRouter, Mistral et Gemini : changer de fournisseur ne demande que trois
variables d'environnement.

La cascade sert aux quotas gratuits : dès qu'un fournisseur refuse (429, panne,
réponse illisible), on passe au suivant. OpenRouter fait en plus sa propre
bascule entre modèles gratuits via le paramètre `models`.

Stdlib uniquement pour les fournisseurs au format OpenAI ; Claude passe par le
SDK officiel `anthropic` (requirements_mining.txt), importé seulement s'il sert.
"""

import json
import os
import time
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TIMEOUT = 90
RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}
OPENROUTER_MAX_MODELS = 3
# Les catalogues gratuits rendent parfois une réponse vide, sans contenu ni
# raisonnement (constaté sous l'issue #194, non reproductible à la demande).
ATTEMPTS = 3
# Claude : la réflexion, toujours active sur Opus 5.5, consomme max_tokens.
THINKING_HEADROOM = 8000
# Au-dessous de ce budget, une question courte (le tri) : effort bas.
SHORT_ANSWER_TOKENS = 4000

# Les catalogues gratuits changent souvent — les identifiants ci-dessous ont été
# relevés le 2026-09-13 et se périment. Ils sont surchargeables par variable
# d'environnement, et docs/LLM_MINING.md explique comment lister ceux du jour.
DEFAULTS = (
    # rolling-2027 : Claude passe en premier. Un fournisseur payant ne s'épuise pas
    # au milieu d'une notice IFOP de 13 hypothèses, là où les quotas gratuits
    # laissaient des issues sans PR (#264, Odoxa du 14 octobre 2026).
    ("anthropic", "https://api.anthropic.com", "ANTHROPIC_API_KEY", "ANTHROPIC_MODELS"),
    # xAI (Grok) parle le format OpenAI : il passe par le même `_post` que les autres.
    ("xai", "https://api.x.ai/v1", "XAI_API_KEY", "XAI_MODELS"),
    ("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "OPENROUTER_MODELS"),
    ("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "MISTRAL_MODELS"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "GEMINI_MODELS"),
)
FALLBACK_MODELS = {
    "anthropic": "claude-opus-5-5",
    # Relevé le 2026-10-16 ; surchargeable par XAI_MODELS (seul le premier sert).
    "xai": "grok-4.6",
    # Trois modèles généralistes de fournisseurs différents : la cascade ne sert
    # à rien si les trois partagent le même quota. Les modèles spécialisés
    # (code, finance, santé, sûreté) sont volontairement écartés.
    "openrouter": (
        "google/gemma-4-31b-it:free,"
        "nvidia/nemotron-3-ultra-550b-a55b:free,"
        "nvidia/nemotron-3-super-120b-a12b:free,"
        "thinkingmachines/inkling:free"
    ),
    "mistral": "mistral-small-latest",
    "gemini": "gemini-2.0-flash",
}


class LLMError(RuntimeError):
    """Aucun fournisseur n'a pu répondre."""


class BudgetExceeded(LLMError):
    """Plafond d'appels ou de tokens atteint : on s'arrête au lieu de brûler un quota."""


class QuotaExhausted(LLMError):
    """Quota du fournisseur épuisé : réessayer avant sa remise à zéro ne sert à rien."""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    models: tuple


@dataclass
class Answer:
    text: str
    provider: str
    model: str
    truncated: bool = False


@dataclass
class Client:
    """Interroge les fournisseurs dans l'ordre jusqu'à obtenir une réponse."""

    providers: tuple
    max_calls: int = 40
    max_tokens: int = 200_000
    calls: int = 0
    tokens: int = 0
    log: list = field(default_factory=list)

    def ask(self, system, prompt, *, max_tokens=32):
        """Une question, une réponse texte. Lève LLMError si personne ne répond."""
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"plafond de {self.max_calls} appels atteint")
        if self.tokens >= self.max_tokens:
            raise BudgetExceeded(f"plafond de {self.max_tokens} tokens atteint")

        errors = []
        exhausted = []
        for provider in self.providers:
            try:
                answer = self._call(provider, system, prompt, max_tokens)
            except LLMError as exc:
                errors.append(f"{provider.name}: {exc}")
                exhausted.append(isinstance(exc, QuotaExhausted))
                continue
            self.log.append(
                {
                    "provider": provider.name,
                    "model": answer.model,
                    "prompt": prompt,
                    "answer": answer.text,
                    "truncated": answer.truncated,
                }
            )
            return answer
        # Tous à court de quota : l'appelant arrête d'interroger les pages suivantes.
        error = QuotaExhausted if exhausted and all(exhausted) else LLMError
        raise error("aucun fournisseur n'a répondu — " + " | ".join(errors))

    def _call(self, provider, system, prompt, max_tokens):
        if provider.name == "anthropic":
            return self._call_anthropic(provider, system, prompt, max_tokens)
        payload = {
            "model": provider.models[0],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        # Bascule interne d'OpenRouter entre plusieurs modèles gratuits. Au-delà de
        # trois, OpenRouter refuse toute la requête en HTTP 400 (« 'models' array
        # must have 3 items or fewer ») : les suivants sont ignorés.
        if provider.name == "openrouter" and len(provider.models) > 1:
            payload["models"] = list(provider.models[:OPENROUTER_MAX_MODELS])

        last = "aucune tentative"
        for attempt in range(ATTEMPTS):
            try:
                body = self._post(provider, payload)
            except _Retryable as exc:
                last = str(exc)
                time.sleep(2 * (attempt + 1))
                continue
            except LLMError as exc:
                raise exc
            self.calls += 1
            self.tokens += (body.get("usage") or {}).get("total_tokens", 0)
            choices = body.get("choices") or []
            choice = choices[0] if choices else {}
            message = choice.get("message") or {}
            text = message.get("content") or ""
            # "length" : la sortie a été coupée par max_tokens. C'est une réponse
            # incomplète, pas un refus du format, et rejouer au même budget donnerait
            # la même coupure : on la rend telle quelle, à l'étape de décider.
            # Un modèle à raisonnement peut aussi épuiser max_tokens dans son champ
            # « reasoning » et rendre un contenu vide avec finish_reason « stop »
            # (cas réel, E3 sur l'issue #194 : 2918 tokens de raisonnement sur 3056).
            truncated = choice.get("finish_reason") == "length" or (not text.strip() and bool(message.get("reasoning")))
            if not text.strip() and not truncated:
                last = (
                    f"réponse vide (modèle {body.get('model') or payload['model']}, "
                    f"finish_reason {choice.get('finish_reason')}, sans raisonnement)"
                )
                # Incident en amont : OpenRouter ne bascule que sur une erreur, et
                # redonnerait le même modèle. On change de modèle de tête.
                if payload.get("models"):
                    rotated = payload["models"][1:] + payload["models"][:1]
                    payload = {**payload, "model": rotated[0], "models": rotated}
                time.sleep(2 * (attempt + 1))
                continue
            return Answer(text.strip(), provider.name, body.get("model") or provider.models[0], truncated)
        raise LLMError(last)

    def _call_anthropic(self, provider, system, prompt, max_tokens):
        """Claude, par le SDK officiel (l'API Anthropic n'est pas appelée en format OpenAI).

        Claude Opus 5.5 réfléchit toujours et refuse `temperature` : on ne l'envoie pas,
        et la réflexion se décompte de `max_tokens`, d'où la marge ajoutée au budget de
        l'appelant. L'effort reste bas pour les questions courtes (le tri d'une notice),
        moyen pour relever un tableau. Le repli côté serveur (`fallbacks: "default"`)
        reprend la requête sur un autre modèle si un filtre de sécurité la refuse.
        """
        try:
            import anthropic
        except ImportError as exc:
            raise LLMError("paquet anthropic absent : pip install -r requirements_mining.txt") from exc
        sdk = anthropic.Anthropic(
            api_key=provider.api_key,
            base_url=provider.base_url,
            timeout=TIMEOUT,
            max_retries=ATTEMPTS - 1,
        )
        try:
            response = sdk.beta.messages.create(
                model=provider.models[0],
                max_tokens=max_tokens + THINKING_HEADROOM,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "low" if max_tokens <= SHORT_ANSWER_TOKENS else "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            raise LLMError(f"quota Anthropic : HTTP {exc.status_code}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"HTTP {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"connexion Anthropic : {exc}") from exc
        self.calls += 1
        usage = response.usage
        self.tokens += (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "output_tokens", 0) or 0)
        if response.stop_reason == "refusal":
            raise LLMError(f"refus du modèle ({getattr(response.stop_details, 'category', None)})")
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        truncated = response.stop_reason == "max_tokens"
        if not text and not truncated:
            raise LLMError(f"réponse vide (modèle {response.model}, stop_reason {response.stop_reason})")
        return Answer(text, provider.name, response.model or provider.models[0], truncated)

    def _post(self, provider, payload):
        request = Request(
            f"{provider.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "presidentielle2027-llm-mining",
            },
        )
        try:
            with urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            headers = exc.headers or {}
            if exc.code == 429 and headers.get("X-RateLimit-Remaining") == "0":
                # Cas réel, issue #194 : « free-models-per-day », 50 requêtes par jour
                # sur tout le compte. Les retenter brûlait du temps sur chaque page.
                reset = str(headers.get("X-RateLimit-Reset") or "")
                when = time.strftime("%H:%M UTC", time.gmtime(int(reset) / 1000)) if reset.isdigit() else "inconnue"
                raise QuotaExhausted(f"quota épuisé chez {provider.name} (remise à zéro {when})") from exc
            if exc.code in RETRY_STATUSES:
                raise _Retryable(f"HTTP {exc.code}") from exc
            raise LLMError(f"HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise _Retryable(str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise LLMError(f"réponse illisible: {exc}") from exc


class _Retryable(LLMError):
    """Échec transitoire : on réessaie le même fournisseur avant de basculer."""


def providers_from_env(env=None):
    """Les fournisseurs dont la clé est présente, dans l'ordre de DEFAULTS.

    L'ordre peut être imposé par LLM_PROVIDERS (noms séparés par des virgules).
    """
    env = os.environ if env is None else env
    wanted = [n.strip() for n in (env.get("LLM_PROVIDERS") or "").split(",") if n.strip()]
    found = {}
    for name, base_url, key_env, models_env in DEFAULTS:
        key = (env.get(key_env) or "").strip()
        if not key:
            continue
        models = tuple(m.strip() for m in (env.get(models_env) or FALLBACK_MODELS[name]).split(",") if m.strip())
        found[name] = Provider(name, env.get(f"{name.upper()}_BASE_URL", base_url), key, models)
    order = wanted or [name for name, *_ in DEFAULTS]
    return tuple(found[name] for name in order if name in found)

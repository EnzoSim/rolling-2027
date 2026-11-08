# Comment fonctionne rolling-2027

Le détail de la chaîne, des réglages et du format. La page d'accueil du dépôt en donne l'essentiel.

## Une notice, du registre au flux

1. **Le catalogue.** [EnzoSim/sondages-commission-index](https://github.com/EnzoSim/sondages-commission-index), un fork du catalogue de Mieux Voter, relit le registre de la Commission à la 32ᵉ minute de chaque heure.
2. **Le guet.** À la 47ᵉ minute, `check-new-polls.yml` ouvre une issue pour chaque nouvelle notice. Le serveur de Ballottage lance ces deux étapes chaque heure : les crons de GitHub ne passent que toutes les 6 à 9 heures et ne servent plus que de secours.
3. **Le dépouillement.** Un bot répond sous l'issue par `/extraction` suivi des tableaux de la notice, par `/sans-iv` quand la notice n'a pas d'intention de vote, ou par `/sans-resultats` quand ses chiffres n'y sont pas (voir [docs/BOT.md](BOT.md)). Avec une clé d'API dans les secrets, le dépôt lit aussi les notices lui-même : Claude, puis Grok (xAI), puis les modèles gratuits.
4. **La vérification.** Quand chaque chiffre est retrouvé sur sa ligne de la notice et que les tests passent, la PR se fusionne seule. En cas de panne de GitHub, elle est retentée, puis rattrapée chaque heure (`merge_verified_prs.py`). Sinon, elle reste en brouillon. Elle reste aussi en brouillon quand une part s'écarte de plus de 20 points de la médiane des autres sondages du même tour (`mining/outliers.py`) : c'est ce qui arrive quand une notice étiquette mal ses propres lignes, comme la notice 10318 d'OpinionWay en octobre 2026 (Le Pen à 4 %, Zemmour à 35 %).
5. **La publication.** Après la fusion, `post-merge.yml` régénère le CSV, le JSON, le compteur et le TOP 3.

### Avant la notice : les rapports des instituts

La Commission met une notice en ligne de quelques heures à deux jours après la publication du sondage. Toutes les 20 minutes, `check-institute-reports.yml` (`check_institute_reports.py`) lit l'API publique WordPress (`/wp-json/wp/v2/media`) de Toluna Harris Interactive, de l'IFOP (son baromètre de l'élection présidentielle), d'Elabe et de Cluster17, et ouvre une issue pour chaque nouveau rapport d'intentions de vote. Le dépouillement lit alors le rapport à la place de la notice.

- **Un rapport n'est pris qu'une fois public** : son article est publié sur le site de l'institut, ou la date que porte son nom est arrivée. Toluna dépose parfois un rapport avant sa date : il attend son jour.
- **La vague du jour, jamais son rappel.** Un rapport aligne souvent les deux sur la même ligne (« Mélenchon 19 17 ») : chaque part retenue doit être le premier nombre après le nom du candidat (`mining/columns.py`), sinon la PR reste en brouillon, avec la raison. Avec `ROLLING_REPORT_AUTOMERGE` à `1`, une PR de rapport qui passe ce contrôle et les autres se fusionne seule, par le bot (`/extraction`) comme par le dépouillement du dépôt ; à `0`, elle attend un clic.
- **Quand la notice arrive**, ses tableaux identiques se rattachent aux mêmes lignes : seule la cellule `filename` reçoit le nom de la notice. D'autres chiffres pour le même sondage ne s'écrivent pas, l'issue le dit. Un rapport arrivé après sa notice n'ajoute rien.
- `.institute_reports.json` retient les rapports déjà vus.

Toutes les six heures, `sync-upstream.yml` reprend les sondages que Mieux Voter a publiés et que ce dépôt n'a pas encore. `scripts/import_upstream.py` les reconnaît à leur institut, leurs dates et leurs parts. Seules les données sont reprises, jamais le code.

| | Mieux Voter | rolling-2027 |
|---|---|---|
| Relevé du registre | une fois par jour (9 h UTC) | toutes les heures |
| Lecture des notices | modèles gratuits, quotas vite épuisés | un bot, ou Claude puis Grok avec une clé |
| Publication | PR relue à la main | fusion automatique quand chaque chiffre est vérifié |

### Réglages

Secrets facultatifs (*Settings → Secrets and variables → Actions*) : `ANTHROPIC_API_KEY` et/ou `XAI_API_KEY`. Les clés `OPENROUTER_API_KEY`, `MISTRAL_API_KEY` et `GEMINI_API_KEY` restent en secours. Variables facultatives : `LLM_PROVIDERS` (l'ordre des fournisseurs, par exemple `xai,anthropic`), `XAI_MODELS`, `ANTHROPIC_MODELS`, `ROLLING_AUTOMERGE` (`0` pour relire chaque PR à la main) et `ROLLING_REPORT_AUTOMERGE` (`1` pour fusionner seules les PR tirées d'un rapport d'institut).

## Structure du projet

```
rolling-2027/
├── candidats.csv              # Liste des candidats avec identifiants
├── hypotheses.csv             # Scénarios avec différentes listes de candidats
├── polls.csv                  # Métadonnées des sondages
├── polls/                     # Résultats individuels par sondage
│   ├── 20240707_0708_hi_A.csv
│   ├── 20250326_0327_if_A.csv
│   └── ...
├── presidentielle2027.csv     # Fichier consolidé (généré automatiquement)
├── presidentielle2027.json    # Flux JSON (généré automatiquement)
├── merge.py                   # Script de fusion des données
├── mining/                    # Lecture et vérification des notices
├── submit_extraction.py       # Commandes /extraction, /sans-iv, /sans-resultats
├── merge_verified_prs.py      # Fusion des PR vérifiées
├── scripts/                   # Reprise de l'amont, collecte des marchés
└── tests/                     # Suite de tests
```

## Format des données

### candidats.csv

| Colonne | Description |
|---------|-------------|
| `candidate_id` | Identifiant court unique (ex: `EP`, `MLP`) |
| `complete_name` | Nom complet du candidat |
| `name` | Prénom |
| `surname` | Nom de famille |
| `parti` | Parti politique |

### polls.csv

| Colonne | Description |
|---------|-------------|
| `poll_id` | Identifiant unique (format: `YYYYMMDD_DDMM_ii_X`) |
| `hypothese` | Scénario (H1, H2, etc.) |
| `nom_institut` | Institut de sondage |
| `commanditaire` | Commanditaire |
| `debut_enquete` | Date de début (YYYY-MM-DD) |
| `fin_enquete` | Date de fin (YYYY-MM-DD) |
| `echantillon` | Taille échantillon |
| `population` | Description population |
| `tour` | Tour de scrutin |
| `filename` | Source (PDF, etc.) |

### polls/<poll_id>.csv

| Colonne | Description |
|---------|-------------|
| `candidat` | Nom du candidat |
| `intentions` | % intentions de vote |
| `erreur_sup` | Marge erreur supérieure (optionnel) |
| `erreur_inf` | Marge erreur inférieure (optionnel) |

## Hors sondages : les marchés de prédiction

`collect-markets.yml` relève chaque jour à 6 h 43 UTC les cotes de Polymarket et de Kalshi dans [data/markets.json](../data/markets.json), séparément, depuis avril. Ces cotes ne sont pas des sondages et ne se mélangent jamais au flux. `scripts/collect-markets.mjs` est la version autonome des lecteurs de marchés de Ballottage (source `546a9b2`, Node 24, sans dépendance npm). Pour le régénérer depuis le dépôt Ballottage : `node_modules/.bin/rolldown scripts/collect-markets.mjs --platform node --format esm --file ../rolling-2027/scripts/collect-markets.mjs`, en gardant le SHA source dans le commentaire en tête du fichier.

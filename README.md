# rolling-2027
![Sondages agrégés](https://img.shields.io/badge/sondages_agrégés-376-blue)

Les sondages d'intention de vote de la présidentielle 2027, publiés dans l'heure qui suit leur notice à la [Commission des sondages](https://www.commission-des-sondages.fr/).

Chaque ligne reste traçable jusqu'à sa notice. Ce dépôt est un fork de [MieuxVoter/presidentielle2027](https://github.com/MieuxVoter/presidentielle2027) (licence MIT), dont il garde le format, les données et la méthode. Merci à Mieux Voter et à ses contributeurs.

Utilisé par [Ballottage](https://ballottage.com), un jeu gratuit de pronos sur la présidentielle 2027.

## 📡 Le flux

| Format | Adresse |
|---|---|
| JSON | `https://raw.githubusercontent.com/EnzoSim/rolling-2027/refs/heads/main/presidentielle2027.json` |
| JSON, miroir | `https://cdn.jsdelivr.net/gh/EnzoSim/rolling-2027@main/presidentielle2027.json` |
| CSV | [presidentielle2027.csv](presidentielle2027.csv) |

Tout l'historique depuis juillet 2024, premier et second tours, au format de Mieux Voter (voir [Format des données](#-format-des-données)) : un outil qui lit leur flux lit celui-ci sans rien changer.

## ⏱️ Comment un sondage arrive dans l'heure

1. **Le catalogue.** [EnzoSim/sondages-commission-index](https://github.com/EnzoSim/sondages-commission-index), un fork du catalogue de Mieux Voter, relit le registre de la Commission à la 32ᵉ minute de chaque heure.
2. **Le guet.** À la 47ᵉ minute, `check-new-polls.yml` ouvre une issue pour chaque nouvelle notice. Le serveur de Ballottage lance ces deux étapes chaque heure : les crons de GitHub ne passent que toutes les 6 à 9 heures et ne servent plus que de secours.
3. **Le dépouillement.** Un bot répond sous l'issue par `/extraction` suivi des tableaux de la notice, par `/sans-iv` quand la notice n'a pas d'intention de vote, ou par `/sans-resultats` quand ses chiffres n'y sont pas (voir [docs/BOT.md](docs/BOT.md)). Avec une clé d'API dans les secrets, le dépôt lit aussi les notices lui-même : Claude, puis Grok (xAI), puis les modèles gratuits.
4. **La vérification.** Quand chaque chiffre est retrouvé sur sa ligne de la notice et que les tests passent, la PR se fusionne seule. En cas de panne de GitHub, elle est retentée, puis rattrapée chaque heure (`merge_verified_prs.py`). Sinon, elle reste en brouillon.
5. **La publication.** Après la fusion, `post-merge.yml` régénère le CSV, le JSON, le compteur et le TOP 3.

Toutes les six heures, `sync-upstream.yml` reprend les sondages que Mieux Voter a publiés et que ce dépôt n'a pas encore. `scripts/import_upstream.py` les reconnaît à leur institut, leurs dates et leurs parts. Seules les données sont reprises, jamais le code.

| | Mieux Voter | rolling-2027 |
|---|---|---|
| Relevé du registre | une fois par jour (9 h UTC) | toutes les heures |
| Lecture des notices | modèles gratuits, quotas vite épuisés | un bot, ou Claude puis Grok avec une clé |
| Publication | PR relue à la main | fusion automatique quand chaque chiffre est vérifié |

### Réglages

Secrets facultatifs (*Settings → Secrets and variables → Actions*) : `ANTHROPIC_API_KEY` et/ou `XAI_API_KEY`. Les clés `OPENROUTER_API_KEY`, `MISTRAL_API_KEY` et `GEMINI_API_KEY` restent en secours. Variables facultatives : `LLM_PROVIDERS` (l'ordre des fournisseurs, par exemple `xai,anthropic`), `XAI_MODELS`, `ANTHROPIC_MODELS` et `ROLLING_AUTOMERGE` (`0` pour relire chaque PR à la main).

## 📊 Données consolidées

Deux fichiers contiennent tous les résultats des sondages consolidés, avec leurs métadonnées :

➡️ [Le fichier CSV des sondages pour l'élection présidentielle 2027](presidentielle2027.csv)

➡️ [Le flux JSON des sondages pour l'élection présidentielle 2027](https://raw.githubusercontent.com/EnzoSim/rolling-2027/refs/heads/main/presidentielle2027.json)

## 🏆 TOP 3 des hypothèses les plus évaluées

Classement des scénarios (hypothèses de candidatures) les plus fréquemment testés par les instituts de sondage. Mis à jour automatiquement.

<!-- TOP_HYPOTHESES:START -->
| Rang | Sondages | Candidats (🥇) / Diff vs 🥇 (🥈🥉) |
|:----:|:--------:|----------------------------------|
| 🥇 | 26 | Bruno Retailleau, Fabien Roussel, Jean-Luc Mélenchon, Marine Le Pen, Marine Tondelier, Nathalie Arthaud, Nicolas Dupont-Aignan, Raphaël Glucksmann, Édouard Philippe, Éric Zemmour |
| 🥈 | 26 | $\textcolor{green}{\text{+ Gabriel Attal}}$, $\textcolor{red}{\text{− Édouard Philippe}}$ |
| 🥉 | 21 | $\textcolor{green}{\text{+ Gabriel Attal}}$ |

> 🥇 liste complète des candidats (référence). 🥈🥉 diff vs 🥇 : $\textcolor{green}{\text{+ ajouté}}$ en vert, $\textcolor{red}{\text{− retiré}}$ en rouge.
<!-- TOP_HYPOTHESES:END -->

## 🗂️ Structure du projet

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

## ➕ Contribuer

### Ajouter un nouveau sondage

Consultez le guide détaillé : **[COMMENT_AJOUTER_UN_SONDAGE.md](COMMENT_AJOUTER_UN_SONDAGE.md)**

En résumé :
1. Ajoutez une ligne dans `polls.csv` avec les métadonnées
2. Créez `polls/<poll_id>.csv` avec les résultats
3. Vérifiez que les candidats existent dans `candidats.csv`
4. Testez localement avec `pytest` et `python merge.py` (vérification locale avant PR)
5. Soumettez une Pull Request

### Validation automatique

GitHub Actions valide automatiquement :
- ✅ Format des fichiers CSV
- ✅ Cohérence des données
- ✅ Génération du fichier consolidé

Une fois mergé, `presidentielle2027.csv` est mis à jour automatiquement.

## 📋 Format des données

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

## 📜 Licence

Ce projet est sous licence [MIT](LICENSE) : © 2025 Mieux Voter, © 2026 Enzo Simier pour les modifications.

## 📈 Hors sondages : les marchés de prédiction

`collect-markets.yml` relève chaque jour à 6 h 43 UTC les cotes de Polymarket et de Kalshi dans [data/markets.json](data/markets.json), séparément, depuis avril. Ces cotes ne sont pas des sondages et ne se mélangent jamais au flux. `scripts/collect-markets.mjs` est la version autonome des lecteurs de marchés de Ballottage (source `546a9b2`, Node 24, sans dépendance npm). Pour le régénérer depuis le dépôt Ballottage : `node_modules/.bin/rolldown scripts/collect-markets.mjs --platform node --format esm --file ../rolling-2027/scripts/collect-markets.mjs`, en gardant le SHA source dans le commentaire en tête du fichier.

## 🗳️ Le projet d'origine

Ce travail part de celui de [Mieux Voter](https://mieuxvoter.fr), l'association qui défend le **jugement majoritaire** : au lieu de choisir un seul candidat, chacun donne son avis sur tous. Mieux Voter compile ces sondages pour les comparer à des sondages au jugement majoritaire.

> 🗳️ **[Soutenir Mieux Voter](https://www.paypal.com/donate/?hosted_button_id=QD6U4D323WV4S)**

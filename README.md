# rolling-2027
![Sondages agrégés](https://img.shields.io/badge/sondages_agrégés-369-blue)

**rolling-2027** : les sondages de la présidentielle 2027, publiés dans l'heure.

Fork de [MieuxVoter/presidentielle2027](https://github.com/MieuxVoter/presidentielle2027) (licence MIT), dont il garde le format, les données et la méthode : chaque ligne reste traçable jusqu'à la notice publiée par la Commission des sondages. Merci à Mieux Voter et à ses contributeurs.

Ce qui change :

| | Mieux Voter | rolling-2027 |
|---|---|---|
| Guet du registre de la Commission | une fois par jour (9 h UTC) | toutes les heures |
| Lecture des notices par un modèle | modèles gratuits, quotas vite épuisés | Claude Opus 5.5, puis Grok (xAI), puis les modèles gratuits |
| Publication | PR en brouillon, relue à la main | fusion automatique si chaque chiffre est retrouvé sur sa ligne de la notice et que les tests passent, retentée sur une panne de GitHub puis rattrapée chaque heure (`merge_verified_prs.py`) ; brouillon sinon |
| Données de l'amont | — | reprises toutes les six heures |

Sans clé d'API, le bot de dépouillement (ou une personne) répond sous l'issue de chaque notice par `/extraction`, `/sans-iv` ou `/sans-resultats` ; le dépôt vérifie chaque chiffre contre la notice et publie seul : voir [docs/BOT.md](docs/BOT.md).

Secrets du dépôt, facultatifs (*Settings → Secrets and variables → Actions*) : `ANTHROPIC_API_KEY` et/ou `XAI_API_KEY` (les clés `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY` restent en secours). Variables facultatives : `LLM_PROVIDERS` (ordre des fournisseurs, par exemple `xai,anthropic`), `XAI_MODELS`, `ANTHROPIC_MODELS`, `ROLLING_AUTOMERGE` (`0` pour relire chaque PR).

Flux JSON : `https://raw.githubusercontent.com/EnzoSim/rolling-2027/refs/heads/main/presidentielle2027.json`

Les marchés de prédiction ont leur collecte quotidienne à **6 h 43 UTC** (`Daily prediction markets`, aussi lançable à la main). [data/markets.json](data/markets.json) archive les cotes et l'historique quotidien de Polymarket et de Kalshi, séparément, depuis avril. Le collecteur de Ballottage interroge directement les deux fournisseurs ; aucune clé ni compte n'est nécessaire. Chaque source garde sa date de relevé, les jours passés restent inchangés et une panne conserve la dernière archive valide au lieu de dater d'aujourd'hui des cotes de secours. Ce fichier est distinct des sondages ; Ballottage relève aussi les marchés en direct côté serveur.

`scripts/collect-markets.mjs` est la version autonome des lecteurs de marchés de Ballottage (source `546a9b2`), sans dépendance npm ni accès à son dépôt privé. Il tourne avec Node 24. Pour le régénérer depuis le dépôt Ballottage : `node_modules/.bin/rolldown scripts/collect-markets.mjs --platform node --format esm --file ../rolling-2027/scripts/collect-markets.mjs` (garder le SHA source dans le commentaire en tête du fichier).

---

Compilation des sondages d'intention de vote à l'occasion des élections présidentielles 2027 en France.

## 📊 Données consolidées

Deux fichiers principaux contiennent l'ensemble des résultats de sondages consolidés avec leurs métadonnées:

➡️ [Le fichier CSV des sondages pour l'élection présidentielle 2027](presidentielle2027.csv)

➡️ [Le flux JSON des sondages pour l'élection présidentielle 2027](https://raw.githubusercontent.com/MieuxVoter/presidentielle2027/refs/heads/main/presidentielle2027.json)

## 🏆 TOP 3 des hypothèses les plus évaluées

Classement des scénarios (hypothèses de candidatures) les plus fréquemment testés par les instituts de sondage. Mis à jour automatiquement.

<!-- TOP_HYPOTHESES:START -->
| Rang | Sondages | Candidats (🥇) / Diff vs 🥇 (🥈🥉) |
|:----:|:--------:|----------------------------------|
| 🥇 | 25 | Bruno Retailleau, Fabien Roussel, Gabriel Attal, Jean-Luc Mélenchon, Marine Le Pen, Marine Tondelier, Nathalie Arthaud, Nicolas Dupont-Aignan, Raphaël Glucksmann, Éric Zemmour |
| 🥈 | 24 | $\textcolor{green}{\text{+ Édouard Philippe}}$, $\textcolor{red}{\text{− Gabriel Attal}}$ |
| 🥉 | 21 | $\textcolor{green}{\text{+ Édouard Philippe}}$ |

> 🥇 liste complète des candidats (référence). 🥈🥉 diff vs 🥇 : $\textcolor{green}{\text{+ ajouté}}$ en vert, $\textcolor{red}{\text{− retiré}}$ en rouge.
<!-- TOP_HYPOTHESES:END -->

## 🗂️ Structure du projet

```
presidentielle2027/
├── candidats.csv              # Liste des candidats avec identifiants
├── hypotheses.csv             # Scénarios avec différentes listes de candidats
├── polls.csv                  # Métadonnées des sondages
├── polls/                     # Résultats individuels par sondage
│   ├── 20240707_0708_hi_A.csv
│   ├── 20250326_0327_if_A.csv
│   └── ...
├── presidentielle2027.csv     # Fichier consolidé (généré automatiquement)
├── merge.py                   # Script de fusion des données
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

Ce projet est sous licence [MIT](LICENSE).

## 🗳️ Marre des sondages qui demandent de choisir un seul candidat ?

Les sondages actuels reposent principalement sur le **scrutin uninominal** : un candidat choisi, tous les autres écartés.

**MieuxVoter soutient le développement du Jugement majoritaire**, une méthode qui permet d'**exprimer avec nuance son opinion sur tous les candidats**.

> 🗳️ **[👉 Je soutiens MieuxVoter](https://www.paypal.com/donate/?hosted_button_id=QD6U4D323WV4S)**

*Chaque soutien contribue au développement du **Jugement majoritaire** et à l'émergence d'une autre façon de mesurer l'opinion.*

**Pourquoi on fait ça ?** Car on souhaite comparer les sondages classiques avec des sondages au jugement majoritaire.

<a href="https://www.paypal.com/donate/?hosted_button_id=QD6U4D323WV4S" target="_blank">
  <img width="2056" height="765" alt="Soutenir MieuxVoter" src="https://github.com/user-attachments/assets/33925f13-4fdf-4346-9d7b-973216073332" />
</a>

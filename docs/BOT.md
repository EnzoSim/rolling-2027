# Le bot de dépouillement (rolling-2027)

Ce dépôt n'a pas de clé d'API. Un bot (le bot Grok d'Enzo) ou une personne lit chaque nouvelle notice et répond sous son issue. Le dépôt vérifie chaque chiffre contre le texte de la notice, puis publie tout seul : le bot propose, le code vérifie. Rien n'est publié sans que chaque valeur soit retrouvée, mot pour mot, sur sa ligne de la notice.

## Ce que le bot fait, toutes les heures

1. **La liste.** Les issues ouvertes avec le label `new-poll`, sans `avec-intentions-de-vote` ni `sans-intentions-de-vote`, de la plus ancienne à la plus récente. Le guet en ouvre une par notice nouvelle de la Commission des sondages (`check-new-polls.yml`, toutes les heures).
2. **La lecture.** Pour chacune, le texte de la notice : le premier lien de l'issue (le `.txt`), sinon le PDF.
3. **La décision**, avec un seul commentaire par notice :
   - pas d'intentions de vote pour la présidentielle (popularité, baromètre, opinion) : `/sans-iv` ;
   - des tableaux d'intentions de vote dans la notice : `/extraction`, puis le dépouillement ci-dessous ;
   - les questions d'intentions de vote sans les chiffres (Odoxa met les siens sur odoxa.fr) : `/extraction` avec, en tête, la ligne `RAPPORT: <adresse https du PDF sur le site de l'institut>`. Les citations des tableaux sont alors cherchées dans ce rapport ; la méthodologie reste celle de la notice.
4. **La réponse du dépôt**, sous l'issue, en une minute environ :
   - `✅ … PR #… fusionnée` : c'est en ligne ; Ballottage le lit dans l'heure, et l'issue se ferme toute seule avec le label `avec-intentions-de-vote` ;
   - `❌ Dépouillement refusé : <raison>` : corriger le point dit et renvoyer un nouveau commentaire `/extraction` complet.

Seul un compte qui a des droits sur le dépôt déclenche la publication. Pour le bot : un jeton GitHub à granularité fine, limité à `EnzoSim/rolling-2027`, avec la seule permission *Issues : lecture et écriture*. Il ne pousse rien et ne touche ni au code ni aux workflows.

## Le format

Les mêmes règles que celles données au modèle (`mining/prompts/e2_methodologie.txt` et `e3_tableaux.txt`) :

```
/extraction
INSTITUT: IFOP
COMMANDITAIRE: LCI, Sud Radio
DEBUT: 2026-10-12
FIN: 2026-10-14
ECHANTILLON: 1525
INSCRITS: 1390
POPULATION: représentatif de la population française âgée de 18 ans et plus
SOURCE_DATES: en ligne du 12 au 14 octobre 2026.
SOURCE_ECHANTILLON: extrait d’un échantillon de 1 525
SOURCE_INSCRITS: L’enquête a été menée auprès d’un échantillon de 1 390 personnes

PAGE 9
TABLEAU
TOUR: 1er Tour
EFFECTIFS: exprimé une intention de vote = 1050 | certains d'aller voter = 832
Nathalie Arthaud | - | Nathalie Arthaud -
Jean-Luc Mélenchon | 16 | Jean-Luc Mélenchon 16,0
Fabien Roussel | 2.5 | Fabien Roussel  2,5
Marine Tondelier | 2 | Marine Tondelier 2,0
Raphaël Glucksmann | 14 | Raphaël Glucksmann 14,0
Gabriel Attal | 6 | Gabriel Attal   6,0
Édouard Philippe | 14 | Edouard Philippe 14,0
Bruno Retailleau | 6.5 | Bruno Retailleau 6,5
Nicolas Dupont-Aignan | 2 | Nicolas Dupont-Aignan 2,0
Marine Le Pen | 34 | Marine Le Pen   34,0
Éric Zemmour | 3 | Éric Zemmour    3,0
FIN

PAGE 10
TABLEAU
…
FIN
```

**Les règles :**

- **La méthodologie.**
  - `INSTITUT` s'écrit comme dans `polls.csv` (IFOP, Harris Interactive, OpinionWay, Odoxa, Elabe, Ipsos BVA, Cluster17, YouGov…) ;
  - `POPULATION` reprend une formulation déjà présente dans `polls.csv` ;
  - les dates sont au format AAAA-MM-JJ, les effectifs en chiffres sans espace ;
  - `INSCRITS` reste vide s'il n'est pas indiqué ;
  - chaque `SOURCE_…` est recopié mot pour mot de la notice, sans retoucher les espaces ni les apostrophes.
  - `SOURCE_DATES` vient de la notice, même quand les tableaux viennent d'un `RAPPORT:` ; une seule plage sur deux mois (« Du 24 septembre au 7 octobre 2026 ») justifie `DEBUT` et `FIN`.
- **Les pages.** Un bloc `PAGE n` par page qui porte un tableau, `n` étant le numéro de la ligne `--- page n ---` du texte de la notice.
- **Les tableaux.**
  - un bloc `TABLEAU` … `FIN` par tableau, dans l'ordre de la page ;
  - `TOUR: 1er Tour` ou `TOUR: 2nd Tour` ;
  - `EFFECTIFS` reprend les bases écrites sur la page (« exprimé une intention de vote = … | certains d'aller voter = … »), jamais celles de la note sur les marges. Les inscrits n'y vont pas : ils sont dans `INSCRITS` (une base « inscrits » y est ignorée).
    Avec un `RAPPORT:`, une base absente de la page du tableau peut se lire sur la page de méthodologie du rapport, celle qui porte les dates du terrain (Odoxa : « 7 599 (hypothèse Philippe) à 7 374 (hypothèse Attal) individus au 1er tour »).
- **Une ligne par candidat :** `nom | valeur | ligne source`.
  - Le nom s'écrit comme dans `candidats.csv`.
  - La valeur a un point décimal (`2.5`) ; « <1 % » s'écrit `0.5`.
  - La ligne source est la ligne entière de la page, recopiée telle quelle.
  - Pas de ligne pour « Ne se prononcent pas », « TOTAL », le vote blanc ni l'abstention.
  - S'il y a plusieurs colonnes : « Publié », sinon « Redressé », sinon la première. Aucune valeur calculée.
- **« - ».** Un candidat proposé mais noté « - » (moins de 0,5 % chez l'IFOP) s'écrit `nom | - | ligne source` et vaut 0. Sa ligne doit être celle de la page, sans autre chiffre.
- **Les contrôles.** Chaque tableau doit faire 100 à 1,5 près. Un second tour a exactement deux candidats.

Un commentaire posté avant que ce workflow existe, ou déjà corrigé ailleurs, se rejoue sans le renvoyer : *Actions › Submit extraction › Run workflow*, avec le numéro de l'issue et l'identifiant du commentaire.

Le dépôt refuse aussi une notice déjà dépouillée (ses hypothèses déjà enregistrées) : rien n'est jamais ajouté deux fois.

## Essayer en local

```bash
python submit_extraction.py --issue 17 --input extraction.txt        # vérifie seulement
python submit_extraction.py --issue 17 --input extraction.txt --pr   # PR, et fusion si ROLLING_AUTOMERGE=1
```

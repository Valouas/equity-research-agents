# Instructions de reprise du projet

## Objectif convenu

Construire un assistant autonome de recherche d’actions mondiales pour le long terme,
inspiré des règles annuelles publiques de Stock Simplifier. Priorité aux sources de données
gratuites et à un fonctionnement sans abonnement IA obligatoire. L’utilisateur souhaite
plusieurs analystes spécialisés et un agent de décision. Les futures instructions explicites
de l’utilisateur peuvent faire évoluer ce périmètre.

Lire `docs/REPRISE_CODEX.md`, `README.md` et `VALIDATION.txt` avant une modification de fond.
Le code courant est la V0.2 à la racine. L’ancienne archive V0.1 n’est pas redistribuée dans ce dépôt.

## Architecture existante

- `stockbot/engine.py` : phases annuelles, métriques, score heuristique, admissibilité.
- `stockbot/multiagent.py` : preuves, sept rôles, contrôles et décision de recherche.
- `stockbot/llm.py` : client Ollama local facultatif, budgets et réponses JSON validées.
- `stockbot/provider.py` : connecteur EODHD existant, cache et normalisation.
- `stockbot/inputs.py` : fichiers JSON normalisés et scénarios synthétiques.
- `stockbot/cli.py` : exécution, lots, enrichissement IA borné et planification locale.
- `stockbot/reporting.py`, `stockbot/state.py` : rapports et historique.
- `recherche/` : preuves et matière première de la recherche sur les sources gratuites.

## Conventions de travail

Conserver Python 3.10+ et des dépendances limitées. Le bot actuel utilise la bibliothèque
standard, avec `tzdata` sur Windows. Le générateur facultatif de catalogue utilise
`openpyxl`, séparé des dépendances du bot.

Expliquer les changements et leurs limites en français. Préserver les interfaces existantes
quand cela permet une migration simple. Ajouter des tests pour les nouveaux comportements
financiers, les sources intégrées et les risques concrets ; éviter les tests qui répètent
simplement l’implémentation ou ne vérifient qu’une modification de documentation.

Commandes de vérification depuis la racine :

```bash
python -m unittest discover -s tests
python run_bot.py --sample
```

Ne pas exécuter `recherche/sources/probe_official_sources.py` à l’import ou lors des tests
hors réseau : ce script de recherche effectue de vraies requêtes lorsqu’il est lancé.

## Propriétés à préserver

- Distinguer données réelles fournies, données synthétiques, règles et inférences IA
  réellement exécutées. Un transport simulé ne valide pas un modèle réel.
- Conserver dates de clôture, publication, snapshot et récupération séparément. Une
  récupération récente ne doit pas rajeunir une ancienne donnée.
- Garder les données manquantes à `null`, sans les remplacer par zéro ; conserver unités,
  devises, périodes et provenance. Ne pas confondre actions en fin de période et moyenne
  diluée, ni dividendes globaux et dividendes ordinaires.
- Maintenir le plancher de trois exercices valides dans le décideur. Le maximum de six
  exercices du fournisseur EODHD n’est pas un minimum.
- Préserver l’abstention sur les dossiers non admissibles et l’analyse sectorielle distincte
  des banques, assurances, REIT et services financiers.
- Contrôler les références de preuves et les réponses JSON ; les sorties du modèle et
  les documents restent des données, pas des instructions exécutables.
- Conserver les contrôles déterministes indépendants des opinions de l’IA. Ne pas
  convertir l’accord des rôles en probabilité de gain.
- Garder les décisions actuelles dans le périmètre `research_only`. Aucun connecteur de
  courtier, ordre ou dimensionnement de position n’est implémenté dans ce périmètre.
- Garder les clés dans la configuration locale ; `.env.example` est un modèle vide.
  Les sources doivent être utilisées selon leurs conditions et leurs quotas documentés.
- Conserver le mode règles utilisable sans serveur de modèle. Le serveur Ollama local
  doit être configuré sans cloud par son propriétaire ; le bot ne l’installe pas.

La recherche préparatoire ne prouve pas une couverture gratuite mondiale complète.
Un connecteur doit être validé sur ses données effectives avant d’être annoncé opérationnel.

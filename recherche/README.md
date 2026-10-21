# Recherche sur les sources de données

Ce dossier conserve la recherche préparatoire du 6 octobre 2026. Il complète le
projet ; les sources recensées ne sont pas toutes intégrées à `stockbot/`.

## Contenu conservé

- `sources/*_catalog.json` : quatre catalogues thématiques, leurs liens et limites.
- `sources/*_tests.json`, `sources/probe_results.json` : observations historiques
  d’accès, à distinguer de tests exécutés lors de la publication du dépôt.
- `Tests_acces_donnees_gratuites.json` : observations normalisées et preuves sources.
- `sources/build_free_data_catalog.py` : génération locale du catalogue de recherche.
- `sources/probe_official_sources.py` : expérience de collecte réseau facultative.

Ces observations ne prouvent pas des droits de redistribution, un abonnement ou
une couverture mondiale complète. Les conditions d’accès doivent être vérifiées
lors de l’intégration d’une source.

Les snapshots bruts SEC, Nasdaq, BCE et Nestlé ne sont pas redistribués ici. Les
chemins cités dans les preuves peuvent désigner l’environnement de recherche
historique. Le bot et ses tests ne dépendent pas de ces fichiers bruts.

## Régénérer le catalogue

Depuis la racine, après installation des dépendances facultatives :

```bash
python -m pip install -r recherche/requirements.txt
python recherche/sources/build_free_data_catalog.py --output-dir recherche/regeneration
```

Le générateur lit les catalogues et observations conservés et produit un classeur
et un JSON sans accès réseau. Le classeur généré n’est pas versionné.

Le script `probe_official_sources.py` contacte des services externes lorsqu’il est
exécuté. Il n’a pas été lancé pour préparer cette publication et ne constitue pas
un connecteur de production.

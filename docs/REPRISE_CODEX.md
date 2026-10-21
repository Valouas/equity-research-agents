# Reprise du développement — 6 octobre 2026

## Objectif et choix déjà établis

L’utilisateur souhaite un bot qui recherche de manière autonome des actions intéressantes,
avec une couverture mondiale et un horizon de recherche à long terme. Les références
initiales sont :

- https://app.stocksimplifier.com/phase?src=yt
- https://www.youtube.com/watch?v=GcBlI7Q-B7o

Le moteur a été construit à partir des règles annuelles écrites publiques de Stock Simplifier
et d’un score heuristique propre au projet. Il ne reproduit pas une méthode vidéo qui aurait
été intégralement transcrite et validée, ni une méthode de phases fondée sur les cours.

Demandes successives : chercher le maximum de sources gratuites, ajouter plusieurs agents
d’analyse et un décideur, puis réunir tous les fichiers pour continuer dans Codex.
Le choix IA retenu est **sans abonnement IA obligatoire**, avec Ollama local en option.
Les rapports sont en français ; le fuseau configuré est `Europe/Zurich`.

## Ce qui fonctionne déjà

La V0.2 fournit les éléments suivants :

- un moteur de phases annuelles, de calculs financiers et de score explicable ;
- un connecteur EODHD avec normalisation, quotas, cache et rotation des titres ;
- un import JSON normalisé utilisable sans clé de fournisseur ;
- sept rôles : qualité des données, fondamentaux, croissance, valorisation, risques,
  documents et contradicteur ;
- un décideur avec `shortlist`, `watch`, `avoid` ou `abstain`, toujours `research_only` ;
- un client Ollama local facultatif, des schémas JSON stricts et un registre de preuves
  propre à chaque dossier ;
- une présélection par règles, puis un lot borné confié à l’IA ;
- des rapports HTML, CSV et JSON, un historique et des alertes Telegram facultatives ;
- un mode quotidien local et une suspension des anciennes décisions non réévaluées.

Les chiffres de configuration et les commandes exactes sont dans `README.fr.md` et `config.json`.
Les champs normalisés sont illustrés dans `examples/companies_synthetic.json`.

Le paquet courant comprend **167 tests automatisés réussis** lors de la préparation de la
V0.2. Le bilan détaillé se trouve dans `VALIDATION.txt`. La présente archive ajoute la
documentation de reprise et les recherches au code existant ; elle ne change pas le moteur.

## Ce qui reste à faire

Le projet n’a pas encore effectué de scan mondial réel dans cette V0.2. Les sources gratuites
recensées ne sont pas toutes connectées. L’entrée JSON peut recevoir leurs données, mais
ne les collecte pas. Le mode `--input --daemon` relit un fichier : la collecte externe doit
l’actualiser. Avec une limite, l’import traite les premières sociétés et ne fait pas encore
tourner automatiquement les suivantes.

Ollama a été testé par son protocole et des réponses simulées. Aucun serveur, poids de modèle
ou modèle réel n’a été installé ou exécuté ici. La qualité d’interprétation d’un modèle
local reste à mesurer sur des dossiers réels. Les pièces fournies ne sont pas téléchargées
automatiquement depuis leurs URL et leur contenu peut être incomplet.

Aucune stratégie n’a fait l’objet d’une validation de rendement. Les scores et seuils sont
des critères de présélection, pas des probabilités de gain. Aucun courtier ni ordre n’est
implémenté. Aucun service permanent ou dépôt distant n’a été créé pour cette livraison.

## Prochaines étapes recommandées

### 1. Réaliser un premier connecteur gratuit de fondamentaux

Étudier les fichiers `recherche/` et sélectionner une source primaire exploitable. Les
échantillons SEC étudiés pendant la recherche ne sont pas redistribués dans ce dépôt ;
les sources et les observations sont conservées dans le catalogue. Construire un
adaptateur vers le format `company` existant, en conservant la provenance de chaque champ.
Tester plusieurs sociétés et exercices réels avant d’étendre le périmètre.

Points à résoudre explicitement : durées annuelles, dates de publication, révisions,
balises comptables, unités, doublons et données manquantes. Les échantillons bruts sont
des observations historiques, jamais des données automatiquement fraîches.

### 2. Compléter les prix et ratios datés

Le moteur exige une valorisation exploitable. Un connecteur de comptes seul ne suffit donc
pas à produire toutes les décisions. Sélectionner une source de prix et d’opérations sur
titres dont les droits, quotas et champs effectifs conviennent. Documenter les devises,
classes d’actions, ADR, cotations secondaires et dates utilisées.

### 3. Alimenter les documents et les preuves

Collecter les publications admissibles, en conserver URL, date et extrait. Éviter de
présenter un extrait comme un rapport complet. Les longues entrées peuvent dépasser le
budget du client local ; toute réduction ou synthèse devra conserver les références et
annoncer ce qui a été omis.

### 4. Valider un modèle local réel

Choisir le modèle selon le matériel disponible, puis tester un petit ensemble de dossiers
réels avec le serveur local configuré sans cloud. Mesurer temps de traitement, mémoire,
respect du format, fidélité des citations et qualité des réserves. Comparer au mode règles.
Ne pas annoncer cette validation à partir des seuls faux clients des tests.

### 5. Étendre progressivement la couverture mondiale

Ajouter les sources européennes et les autres marchés en s’appuyant sur le catalogue,
avec des modèles sectoriels et des métriques de couverture. Prévoir un univers de titres
identifiés, une rotation des lots gratuits, un cache et des dates de rafraîchissement.
Mesurer les champs réellement disponibles par marché avant d’annoncer une couverture.

### 6. Suivre les décisions dans le temps

Conserver les décisions originales et leurs preuves. Définir ensuite une évaluation
historique ou prospective qui traite les révisions, radiations, opérations sur titres,
devises, frais et comparaison à un indice adapté. La correction du logiciel et la
performance d’investissement sont deux validations différentes.

## Points de vigilance découverts pendant le développement

- Une phase 4 liée aux dividendes ne prouve pas une rentabilité actuelle positive.
- Les actions en fin d’exercice, les actions indiquées en couverture d’un dépôt et la
  moyenne annuelle diluée sont des mesures distinctes.
- Un fait comparatif repris dans un dépôt récent peut porter l’année de ce dépôt dans un
  champ de métadonnées ; utiliser les périodes effectives pour classer les exercices.
- Les dividendes totaux peuvent mélanger plusieurs catégories de bénéficiaires.
- Une date de téléchargement ne remplace ni la date de publication ni celle d’un ratio.
- Les avis du même modèle sur le même dossier ne sont pas des preuves indépendantes.
- Les réserves des agents documentaires ou contradictoires doivent rester visibles et
  limiter la décision quand elles ne sont pas résolues.

Les tests adversariaux existants couvrent plusieurs de ces limites. Les nouveaux connecteurs
devront ajouter leurs cas réels de normalisation et conserver les références vérifiables.

## Documentation de référence

Le catalogue joint contient les liens détaillés, limites et statuts de vérification des
sources étudiées. Les notes de recherche sont datées du 6 octobre 2026 et devront être
revérifiées au moment d’une intégration lorsque les offres ou conditions sont susceptibles
d’avoir changé.

- Stock Simplifier : https://stocksimplifier.com/phase-check
- SEC : https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- Ollama : https://docs.ollama.com/api/chat
- Sorties structurées : https://docs.ollama.com/capabilities/structured-outputs
- Configuration locale : https://docs.ollama.com/faq

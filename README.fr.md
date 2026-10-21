# Bot de recherche d’actions — version 0.2

Cette version prépare **sept analyses spécialisées et une décision de recherche par société**. Elle conserve les phases et les critères financiers de la version 0.1, puis ajoute les avis détaillés, leurs éléments de preuve, leurs réserves et les conditions qui permettraient de réexaminer le dossier.

Le résultat est une priorité de travail : **à étudier, à surveiller, écartée selon les critères, ou aucune décision**. Le programme ne calcule pas de probabilité de gain, ne se connecte à aucun courtier et ne transmet aucun ordre de bourse.

Le fonctionnement par défaut utilise des **règles déterministes**, sans abonnement IA ni clé de modèle. Une option permet de faire réellement exécuter les rôles par un modèle **local via Ollama**, que vous installez séparément. Le rapport indique la méthode employée et les éventuels échecs. Aucun modèle n’est inclus et aucune inférence avec un vrai modèle Ollama n’a été validée pendant la préparation de cette version.

## 1. Démarrer avec un exemple hors réseau

Python **3.10 ou supérieur** convient. Depuis le dossier du projet, sous Windows :

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_bot.py --sample
```

Sur Linux ou macOS :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_bot.py --sample
```

Après l’installation des dépendances, **`--sample` fonctionne hors réseau avec le mode règles par défaut**. Les quatre sociétés, leurs chiffres et leurs extraits de documents sont fictifs. Cet exemple sert à parcourir les différents états du programme ; il ne désigne aucune action réelle intéressante. Ses dates sont générées relativement au jour d’exécution afin de tester les contrôles de fraîcheur.

Le terminal affiche les chemins des exports `report.html`, `report.csv` et `results.json`. Ouvrir le HTML dans un navigateur. Il fonctionne localement, sans script, police ou graphique externe. Filtrer les sociétés par nom, symbole, pays, secteur ou état de recherche. Ouvrir une fiche pour voir la décision et les analyses ; cliquer sur une référence pour retrouver la valeur et sa provenance.

Le fichier `examples/companies_synthetic.json` fournit aussi une entrée complète, avec des **dates fixes de préparation au 6 octobre 2026**, indiquées dans le fichier :

```powershell
.\.venv\Scripts\python.exe run_bot.py --input examples/companies_synthetic.json
```

Ces dates fixes ne sont pas rajeunies au chargement. Une exécution ultérieure peut donc conduire à une abstention pour données trop anciennes. Pour choisir le dossier de sortie :

```powershell
.\.venv\Scripts\python.exe run_bot.py --sample --output rapports_test
```

Une exécution ponctuelle réécrit les trois fichiers dans le dossier indiqué. En mode quotidien, `--output` accueille un sous-dossier par cycle.

Un rapport d’illustration est fourni dans `example_report/`. Il provient du scénario synthétique et du mode règles ; il ne contient aucun avis produit par un modèle IA réel.

## 2. Comprendre les sept analyses et le décideur

| Rôle | Travail effectué |
| --- | --- |
| Qualité des données et chronologie | Contrôler les dates, l’historique annuel, les devises et les éléments disponibles. |
| Fondamentaux | Examiner les résultats, les flux de trésorerie et la rentabilité calculable. |
| Croissance | Lire la progression historique, la phase de développement et ses limites. |
| Valorisation | Examiner les multiples fournis et les critères explicites du moteur. |
| Risques | Examiner le bilan, la liquidité, la dilution et les seuils défavorables. |
| Documents | Vérifier les extraits datés et sourcés fournis ; interpréter leur texte uniquement lorsque l’option IA fonctionne. |
| Contre-analyse | Formuler les réserves et les hypothèses susceptibles de remettre en cause la conclusion. |
| Décideur | Rassembler les constats, conserver les réserves et appliquer les contrôles obligatoires avant de proposer un état de recherche. |

**Sept rôles ne signifient pas sept modèles ou sept sources indépendantes.** En mode règles, les analyses sont déterministes. En mode Ollama, les rôles peuvent partager le même modèle et les mêmes données. Le décideur ne compte pas les avis comme des votes ; leur accord ne fournit pas une probabilité de réussite.

Les analyses locales sont exécutées successivement : les six premiers spécialistes, la contre-analyse qui reçoit leurs avis, puis le décideur. Le même modèle configuré traite ces différents rôles.

Chaque avis conserve son état (`support`, `caution`, `insufficient`), sa méthode, son état d’exécution, ses raisons, ses hypothèses, ses éléments manquants et les identifiants des preuves utilisées. Les rapports absents ou en échec restent visibles.

### Les quatre décisions

| Code exporté | Libellé du rapport | Signification |
| --- | --- | --- |
| `shortlist` | À étudier en priorité | Le dossier satisfait les conditions de présélection de cette méthode ; poursuivre l’analyse de l’entreprise et de son prix. |
| `watch` | À surveiller | Des éléments demandent confirmation, complément ou réexamen. |
| `avoid` | Écartée selon les critères | Des critères défavorables conduisent à écarter ce dossier de la recherche prioritaire actuelle. |
| `abstain` | Aucune décision | Les données, la méthode sectorielle ou les analyses disponibles ne permettent pas de conclure. |

Toutes ces décisions portent la portée **`research_only`**. Elles ne sont ni un achat, ni une vente, ni une taille de position. Le rapport distingue la décision du score financier : une entreprise peut conserver une bonne note heuristique et recevoir une abstention du décideur.

Les contrôles obligatoires sont calculés dans le programme. Un contrôle `block` non validé impose l’abstention ; un contrôle `cap_watch` non validé empêche une priorité d’étude. D’autres critères peuvent conduire à écarter le dossier. Une pièce manquante, une date inconnue ou une référence absente restent des limites explicites.

Le dossier de recherche exige notamment **trois exercices annuels récents consécutifs**, un secteur pris en charge et des données respectant les limites de fraîcheur. Une priorité d’étude demande aussi des dates et une devise explicites, une source identifiée, un extrait admissible, une valorisation suffisamment documentée et les seuils renforcés du décideur. Le détail figure dans `stockbot/multiagent.py` et dans chaque rapport.

### Qualité des analyses et suivi

La couverture, la qualité du dossier, la présence des sources, les contrôles bloqués et les échecs d’exécution servent au **suivi de la qualité du processus**. Ils ne constituent pas un taux de réussite financière. Les comptes d’appels Ollama décrivent l’exécution technique ; un appel réussi ne prouve pas qu’un raisonnement est exact.

Les exports JSON gardent le dossier complet avec ses dates, ses avis, sa décision, ses preuves et ses limites. Les CSV conservent les anciennes colonnes financières et ajoutent les champs de recherche lorsqu’ils sont présents. Le classement financier reste séparé par famille de développement : les scores des phases 1, 2, 3–4 et 5 ne forment pas un classement unique.

## 3. Analyser vos données

```powershell
.\.venv\Scripts\python.exe run_bot.py --input votre_fichier.json
```

Le fichier est un **JSON normalisé**, et non un PDF ou une page web. Il peut contenir une liste de sociétés ou un objet avec `schema_version: "0.2"`, `data_kind` et `companies`. Pour des données réelles fournies au programme, utiliser `data_kind: "provided"` et ne pas conserver le marqueur `is_synthetic: true` des exemples. **« Fournies » signifie disponibles dans le dossier ; cela ne veut pas dire vérifiées ou actuelles.**

Le fichier complet d’exemple montre les champs attendus :

| Champ | Contenu et précaution |
| --- | --- |
| `symbol`, `name`, `country`, `sector`, `industry` | Identité et activité. Un symbole ne suffit pas toujours à distinguer classe d’actions, ADR et cotation secondaire. |
| `financial_currency`, `quote_currency` | Devise des comptes et devise de cotation, conservées séparément. |
| `source_url`, `retrieved_at`, `provider_updated_at` | Source des comptes, date de récupération et date réelle du snapshot fournisseur. Une nouvelle récupération ne rajeunit pas les ratios. |
| `annual` | Exercices : `date`, `filing_date`, `currency`, comptes de résultat, trésorerie, bilan et actions. |
| `valuation` | Multiples disponibles : `trailing_pe`, `forward_pe`, `price_sales`, `price_book`, `ev_ebitda`. Un multiple nul ou négatif n’est pas une preuve de décote. |
| `documents` | Extraits avec `title`, `text`, `published_at` et `source_url`. Les liens ne sont pas téléchargés automatiquement. |

Un montant inconnu doit être **`null`**, pas zéro. Conserver les montants dans une unité cohérente et la même devise comptable pour les exercices comparés. Séparer `shares_end`, les actions en circulation en fin d’exercice, de `shares_diluted`, la moyenne diluée employée pour les résultats par action. Un montant global de dividendes ne prouve pas un versement aux actions ordinaires : conserver explicitement cette qualification lorsqu’elle est documentée.

Le lecteur limite l’entrée à 20 Mio, 10 000 sociétés, 30 exercices par société et 10 extraits. Les dates ne sont pas corrigées automatiquement. Le moteur de documents retient des extraits admissibles, datés, sourcés et limités à 6 000 caractères chacun ; le rapport signale la troncature. Un extrait reste une sélection du document, avec les informations qui peuvent avoir été omises.

### Réexaminer un fichier chaque jour

```powershell
.\.venv\Scripts\python.exe run_bot.py --input votre_fichier.json --daemon
```

Le programme relit le fichier immédiatement puis chaque jour à **23:15, heure de Zurich**, par défaut. **Le fichier doit être actualisé par votre collecte externe.** Le bot ne transforme pas une relecture en nouvelles données et ne télécharge pas automatiquement les sources gratuites. Avec `--limit N`, l’import traite les N premières sociétés du fichier à chaque cycle ; cette voie ne fait pas tourner automatiquement le reste du fichier. Le rapport indique le nombre d’entrées non traitées.

La version 0.2 **ne parcourt pas encore toutes les sources gratuites du catalogue mondial**. L’import permet d’utiliser des données obtenues auprès de sources gratuites, mais leur collecte, leur normalisation et la vérification de leur couverture restent des étapes distinctes. Les collecteurs étudiés dans le catalogue ne sont pas tous intégrés au bot. Aucun test sur quelques endpoints ne valide un univers mondial exhaustif.

## 4. Activer de vraies analyses IA locales avec Ollama

Cette option ne demande pas d’abonnement à une API IA. Elle demande un ordinateur adapté au modèle choisi, de l’espace pour ses poids et du temps de calcul. Le bot n’installe ni Ollama ni un modèle et n’achète aucun crédit. Choisir un modèle **local** compatible avec les réponses JSON structurées, vérifier sa licence et l’installer séparément en suivant le [guide officiel Ollama](https://docs.ollama.com/quickstart). Aucun modèle particulier n’est présenté comme validé pour ce bot.

### Préparer le serveur local

Désactiver les fonctions cloud **sur le processus serveur Ollama** avec `OLLAMA_NO_CLOUD=1`, puis redémarrer ce serveur. Définir cette variable seulement dans le terminal du bot ne change pas un serveur déjà lancé ailleurs. Pour l’application Windows/macOS ou un service Linux, suivre la [FAQ officielle de configuration](https://docs.ollama.com/faq).

Pour un lancement manuel du serveur, dans un terminal dédié après avoir arrêté une éventuelle autre instance :

```powershell
$env:OLLAMA_NO_CLOUD = "1"
ollama serve
```

Sous Linux ou macOS :

```bash
OLLAMA_NO_CLOUD=1 ollama serve
```

Laisser ce terminal ouvert. Le bot utilise par défaut `http://127.0.0.1:11434`. Le client accepte uniquement une adresse de boucle locale, refuse les redirections et les noms explicitement cloud. Un alias de modèle créé par l’utilisateur ne peut toutefois pas être certifié local par son seul nom ; la configuration sans cloud du serveur reste nécessaire.

### Lancer un petit dossier

Dans le terminal du projet, remplacer `NOM_MODELE_LOCAL` par le nom exact du modèle **déjà installé** :

```powershell
.\.venv\Scripts\python.exe run_bot.py --input votre_fichier.json --backend ollama --model NOM_MODELE_LOCAL --limit 3
```

Pour tester le même parcours avec des chiffres fictifs :

```powershell
.\.venv\Scripts\python.exe run_bot.py --sample --backend ollama --model NOM_MODELE_LOCAL --limit 3
```

Le second exemple conserve son marquage synthétique même si les analyses IA sont réellement exécutées. Les sorties JSON structurées sont documentées par [Ollama](https://docs.ollama.com/capabilities/structured-outputs). Le programme contrôle ensuite le format, les références de preuve et les limites de décision. Ces contrôles ne constituent pas une vérification indépendante de chaque phrase générée.

### Budgets et états d’exécution

Le programme applique d’abord les règles aux sociétés du lot. Avec le backend Ollama, il retient ensuite au maximum trois dossiers éligibles, triés par score financier décroissant. Les dossiers bloqués ou en dehors de cette limite conservent les analyses par règles et un état indiquant que l’IA n’a pas été exécutée.

| Réglage du bloc `agents` | Valeur initiale | Effet |
| --- | --- | --- |
| `backend` | `rules` | Mode déterministe par défaut. |
| `model` | chaîne vide | Aucun modèle téléchargé ou choisi automatiquement. |
| `base_url` | `http://127.0.0.1:11434` | Adresse du serveur Ollama local. |
| `max_llm_companies` | 3 | Maximum de sociétés confiées à l’IA pendant un cycle. |
| `max_calls_per_run` | 48 | Budget d’appels du client local pour le cycle, tentatives infructueuses comprises. |
| `timeout_seconds` | 60 | Délai par opération réseau ; un modèle lent peut échouer. |
| `min_shortlist_score` | 75 | Seuil financier minimal pour une priorité d’étude, parmi les autres conditions obligatoires. |
| `min_shortlist_coverage_pct` | 85 | Couverture renforcée du dossier pour une priorité d’étude. |
| `max_document_age_days` | 550 | Ancienneté maximale des extraits considérés. |

Un dossier peut produire au maximum **huit demandes d’analyse** : sept spécialistes et un décideur. Le client borne aussi la taille des entrées, des réponses et de la génération ; il ne relance pas automatiquement les appels en échec. Le nombre d’octets d’une entrée ne mesure pas exactement son nombre de tokens.

Le compteur `llm.calls` concerne les tentatives de transport comptabilisées. Les échecs peuvent aussi inclure un rejet avant envoi, par exemple pour un dossier trop volumineux ou un budget épuisé ; ils peuvent donc dépasser le nombre de requêtes effectivement tentées.

Vérifier dans le rapport `execution_mode`, les méthodes et les états par rôle. **Une analyse IA exécutée est un rapport `method: "ollama"` avec `execution_status: "completed"`.** Un backend demandé ou un nom de modèle ne suffit pas. Les refus, les réponses non conformes, les modèles absents et les budgets atteints sont signalés. La conclusion finale respecte les contrôles locaux même si le modèle propose un état plus favorable.

## 5. Conserver la collecte EODHD de la version 0.1

L’ancien connecteur EODHD reste disponible. Il constitue une voie distincte de l’import de fichiers et de l’exemple synthétique.

### Démonstration sur trois sociétés réelles

```powershell
.\.venv\Scripts\python.exe run_bot.py --demo
```

Cette commande appelle le fournisseur avec sa clé publique de démonstration pour **Apple, Amazon et Tesla**. Elle nécessite une connexion réseau. Ces trois titres vérifient le connecteur ; ils ne sont pas une sélection des meilleures actions mondiales. Un titre peut rester non classé ou recevoir une abstention. La disponibilité et les droits de démonstration restent ceux du fournisseur.

### Données autorisées par votre compte

Copier `.env.example` vers `.env`, puis renseigner localement `EODHD_API_TOKEN`. Aucun compte ni abonnement de données n’est créé avec le projet. Vérifier les accès aux fondamentaux, aux listes de titres et, si nécessaire, aux historiques de dividendes dans les [droits des plans EODHD](https://eodhd.com/pricing) et la [documentation des fondamentaux](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds).

```powershell
.\.venv\Scripts\python.exe run_bot.py --once --limit 30
.\.venv\Scripts\python.exe run_bot.py --once --symbols AAPL.US,AMZN.US
```

Les symboles de cette voie suivent le format EODHD `CODE.BOURSE`. Les suffixes d’autres services ne sont pas nécessairement identiques. Les droits du fournisseur déterminent la couverture obtenue ; l’absence d’abonnement IA ne rend pas automatiquement cette source de données gratuite.

### Collecte quotidienne

```powershell
.\.venv\Scripts\python.exe run_bot.py --daemon
```

Le mode quotidien lance un premier cycle puis les suivants à **23:15, heure de Zurich**, par défaut. Le processus et l’ordinateur doivent rester actifs. `Ctrl+C` arrête le programme. Le projet n’installe pas de service système ; un planificateur peut lancer `--once` chaque jour. Chaque bourse possède sa propre clôture, et les dates des données restent visibles dans les dossiers.

Le scanner EODHD tourne sur les titres dont la dernière tentative est la plus ancienne, dans les budgets configurés. Un titre en erreur ne bloque pas toute la file. Une clé ou un accès global refusé interrompt le cycle pour permettre de corriger la configuration. Le rapport regroupe les récupérations admissibles et indique les titres non parcourus, les erreurs et les dates conservées. Une ancienne décision de recherche non réévaluée pour le jour courant est suspendue ; son dossier reste consultable.

| Réglage de collecte | Valeur initiale | Effet |
| --- | --- | --- |
| `exchanges` | `null` | Découvrir les places accessibles ; une liste de codes réduit le périmètre. |
| `exclude_venues` | `OTC`, `PINK` | Exclure ces places de la découverte générale. |
| `max_symbols_per_run` | 3 000 | Limiter la taille du lot. |
| `api_units_per_run`, `api_units_per_day` | 35 000 ; 90 000 | Limites locales en unités de données ; les droits du compte restent applicables. |
| `min_request_interval` | 0,3 seconde | Espacement minimum des requêtes fournisseur. |
| `cache_ttl_hours` | 20 | Réutilisation possible du cache fournisseur. |
| `refresh_universe_days` | 7 | Actualisation de la liste de titres. |
| `results_max_age_days` | 7 | Limite des dates de récupération réunies dans le rapport consolidé. |
| `top_n` | 20 | Taille demandée pour la synthèse ; l’alerte est plafonnée à dix entrées et le HTML conserve les fiches. |

**« Mondial » décrit le périmètre visé.** La couverture réelle dépend des sources intégrées, des places accessibles, des quotas, des doublons de cotation et des comptes exploitables. Elle doit être mesurée progressivement, pays par pays.

## 6. Phases et score financier conservés

Le moteur reprend l’ordre de décision public de [Stock Simplifier — Phase Check](https://stocksimplifier.com/phase-check), avec une collecte et un score indépendants. Les règles utilisent les comptes annuels et conservent les cas indéterminés. Un dividende ordinaire peut conduire à la phase 4 avant le test de rentabilité : **une phase 4 ne prouve donc pas à elle seule que l’entreprise est bénéficiaire**.

Le score évalue cinq familles : croissance, qualité économique, bilan, dilution et valorisation. Les seuils et les pondérations figurent dans `stockbot/engine.py`. Une note de 80/100 indique des critères satisfaits dans cette méthode ; elle ne signifie pas 80 % de chances de gagner. Le ROIC éventuel est une approximation comptable, et les multiples ne produisent ni DCF, ni prix intrinsèque, ni objectif de cours.

Le moteur financier exige par défaut **au moins trois exercices** et une couverture de 75 %. Le connecteur EODHD conserve au maximum six exercices ; ce maximum n’est pas un minimum requis. Le comité ajoute ses propres contrôles, dont la continuité des trois derniers exercices. Les banques, assurances, REIT et autres activités financières demandent une méthode sectorielle dédiée.

Le moteur s’abstient notamment sans multiple exploitable, avec des incohérences critiques, des comptes trop anciens ou un snapshot périmé. Les seuils initiaux sont de **550 jours pour les comptes** et **14 jours pour le snapshot fournisseur** lorsqu’il est daté. Une récupération récente ne transforme pas une ancienne information en donnée fraîche. Une date manquante reste une limite visible.

## 7. Exports, alertes et historique

Les rapports sont produits dans un dossier propre à l’exécution, sauf choix explicite de sortie ponctuelle. Le JSON conserve le détail pour une relecture ultérieure ; le CSV protège les cellules contre l’interprétation en formule ; le HTML échappe les textes fournis et ouvre seulement les liens HTTPS admissibles à la demande du lecteur. Les références fictives `.invalid` des exemples sont signalées sans lien vers un document réel.

L’alerte Telegram reste **facultative**. Pour l’activer, configurer localement `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` dans `.env`, puis ajouter `--notify-telegram` à la commande. Aucun envoi n’est activé par défaut. La synthèse reprend les décisions à étudier ou à surveiller et les comptes des autres états ; elle ne transmet aucun ordre.

Les données récupérées aujourd’hui peuvent intégrer des corrections de publications passées. Une date de dépôt ne reconstitue pas à elle seule les valeurs connues à cette date. Le projet ne fournit pas de backtest historique sans biais ni de validation des rendements futurs. Un suivi financier demanderait notamment de traiter les révisions, les sociétés radiées, les opérations sur titres, les devises, les frais et un indice de comparaison adapté.

## 8. Organisation et vérifications

| Fichier ou dossier | Rôle |
| --- | --- |
| `run_bot.py` | Point d’entrée. |
| `config.json` | Périmètre, budgets, horaires et analyses. |
| `stockbot/inputs.py` | Import JSON et scénarios synthétiques datés. |
| `stockbot/provider.py` | Connecteur EODHD, normalisation, cache et quotas. |
| `stockbot/engine.py` | Phases, critères financiers et explications. |
| `stockbot/multiagent.py` | Sept rôles, preuves, contrôles et décideur. |
| `stockbot/llm.py` | Client Ollama local facultatif et validation des réponses. |
| `stockbot/reporting.py` | Rapports français HTML, CSV, JSON et synthèse textuelle. |
| `stockbot/state.py`, `stockbot/cli.py` | Historique, rotation et exécution. |
| `examples/companies_synthetic.json` | Entrée fictive à dates fixes. |
| `tests/` | Vérifications ciblées du moteur, du traitement et des frontières de sécurité. |
| `VALIDATION.txt` | Résultats de validation de l’archive livrée et limites des essais réalisés. |

Pour exécuter les tests :

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Les tests IA utilisent des réponses **simulées**, avec le vrai client et l’orchestration du programme, pour vérifier les formats, les références, les garde-fous et les échecs. Ils n’établissent pas la qualité d’un modèle local réel. Les tests financiers et les exemples synthétiques vérifient des comportements logiciels ; ils ne mesurent pas la performance d’une stratégie. Le bilan des essais de cette livraison figure dans `VALIDATION.txt`.

### Documentation de référence

- [Ollama — installation et modèles locaux](https://docs.ollama.com/quickstart)
- [Ollama — configuration du serveur et désactivation du cloud](https://docs.ollama.com/faq)
- [Ollama — API Chat](https://docs.ollama.com/api/chat)
- [Ollama — réponses JSON structurées](https://docs.ollama.com/capabilities/structured-outputs)
- [Stock Simplifier — règles publiques des phases](https://stocksimplifier.com/phase-check)
- [Stock Simplifier — cycle de vie de l’entreprise](https://stocksimplifier.com/company-lifecycle-phases)
- [EODHD — fondamentaux](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds)
- [EODHD — limites API](https://eodhd.com/financial-apis/api-limits)

La vidéo fournie lors de la conception n’a pas été intégralement transcrite et vérifiée. Le projet se fonde sur les règles écrites consultées et sa propre méthode explicite ; il ne prétend pas reproduire une analyse vidéo non vérifiée.

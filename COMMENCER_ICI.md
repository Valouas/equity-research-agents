# Commencer ici

Le dépôt contient le projet existant de recherche d’actions V0.2 : moteur financier,
sept analystes spécialisés, décideur de recherche, rapports et tests.

- [Présentation du projet](README.md)
- [Guide complet en français](README.fr.md)
- [Instructions de reprise](docs/REPRISE_CODEX.md)
- [Validation de cette publication](docs/VALIDATION_GITHUB.md)

## Essai hors réseau sous Windows

Avec Python 3.10 ou supérieur, depuis la racine du dépôt :

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe run_bot.py --sample --backend rules --output reports/sample
```

L’exemple utilise des sociétés et des chiffres fictifs. Après installation des
dépendances, il fonctionne sans clé API, réseau ou modèle IA. Ouvrir ensuite
`reports/sample/report.html`.

Le guide français décrit aussi les données JSON normalisées, la collecte EODHD,
Ollama local et le mode quotidien. Ces options ne sont pas nécessaires pour l’essai.

Les sources applicatives sont à la racine et dans `stockbot/`. Les recherches
complémentaires se trouvent dans `recherche/`. L’ancienne archive V0.1 et les gros
échantillons de données externes ne sont pas inclus dans ce dépôt ; les entrées et
rapports synthétiques restent disponibles.

# Contribuer à Novel

Utiliser Python 3.11+ et Node.js 22. Le backend utilise uniquement la bibliothèque standard Python. Installer les dépendances du frontend avec `npm ci` dans `frontend` ; conserver `package-lock.json`.

```powershell
python -m unittest discover -s . -p "test_*.py" -v
Push-Location frontend
npm.cmd ci --no-audit --no-fund
npm.cmd run build
Pop-Location
python tools/check_public_files.py --history
git diff --check
```

Sous Windows, `test.cmd` exécute la suite avec le Python disponible. Les tests du lanceur emploient des fonctions Docker simulées et une politique PowerShell limitée au processus de test. Les tests ne génèrent aucune traduction réelle.

Préserver les identifiants sources, la validation par empreinte exacte, les sessions éphémères et la reprise explicite après erreur. Une réponse simulée ne prouve ni l’accès à un modèle réel ni la qualité littéraire. Documenter séparément toute recette Codex réelle et sa consommation.

Ne jamais ajouter de données utilisateur aux fixtures, aux captures ou aux rapports. Utiliser la démonstration synthétique et des chemins fictifs. Les propositions de mise à jour de Codex doivent conserver les modèles et efforts demandés et vérifier le protocole App Server avant activation.

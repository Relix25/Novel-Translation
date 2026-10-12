# Vérification de la migration — 12 octobre 2026

## Contrôles locaux

- 99 tests Python réussis sous Windows avec Python 3.11, y compris le lanceur Windows PowerShell 5.1, les protections des travaux, la mémoire sourcée et les sauvegardes.
- `test.cmd` et `python -m unittest discover -s . -p "test_*.py" -v` exécutent la même suite ; les réponses IA sont simulées.
- Frontend construit depuis `package-lock.json` avec `npm ci` puis `npm run build` ; audit des dépendances de production : zéro vulnérabilité signalée.
- Image Docker construite depuis le dépôt, avec un contexte limité aux fichiers publics nécessaires. Frontend servi localement depuis l’image.
- Bibliothèques historiques copiées après arrêt contrôlé et conservées dans des chemins ignorés. Empreintes de tous les fichiers copiés comparées ; intégrité SQLite et empreintes logiques de toutes les lignes existantes vérifiées après démarrage. Les nouvelles tables 0.7 n’effacent pas les états antérieurs.
- Conteneur migré sain ; `/health` confirme `0.7.0`. Les ressources frontend et la capacité de mémoire sont disponibles. Bibliothèque montée depuis le dépôt, sources toujours en lecture seule et volume Codex existant réutilisé.
- `codex login status` confirme la connexion ChatGPT conservée ; le pont Novel lit le catalogue réel contenant Luna et Sol. Aucun appel de traduction, résumé, vérification ou analyse mémoire n’a été lancé pendant cette migration.

Les rapports détaillés, empreintes, chemins locaux et données du compte restent dans `docker-data` ou des fichiers de vérification ignorés. Aucun manuscrit, base, EPUB, capture privée ou identifiant n’est livré dans Git.

## Contrôles GitHub

La configuration CI teste Python 3.11 et 3.13 sous Windows et Linux, construit le frontend, audite les dépendances de production et vérifie le démarrage Docker avec la démonstration synthétique. Les actions sont verrouillées par empreinte de commit et les permissions sont en lecture seule.

Dependabot suit npm, les actions et l’image de base Docker. Les alertes et mises à jour de sécurité des dépendances, la détection des secrets, la protection au push et les signalements privés de vulnérabilité sont activés sur le dépôt.

Le contrôle `python tools/check_public_files.py --history` inspecte l’index et les objets de l’historique. Il refuse les chemins d’artefacts privés et certaines formes de secrets sans afficher leurs valeurs. Le diff est examiné avant chaque publication.

Les résultats de la CI distante sont consultables dans [GitHub Actions](https://github.com/Relix25/Novel-Translation/actions/workflows/ci.yml). La configuration seule ne constitue pas un résultat de CI ; consulter l’exécution liée au commit livré.

## Limites

Les tests et la connexion au catalogue ne prouvent pas la disponibilité d’une génération pour chaque modèle ni la qualité littéraire des traductions. Une relecture comparée reste nécessaire avant approbation. Les textes privés et les essais réels ne sont jamais utilisés comme fixtures publiques.

# Novel avec Docker

Le service est publié sur `http://127.0.0.1:8791`. L’image contient le CLI Codex `0.162.0-alpha.17.2`, version conservée pour la compatibilité du protocole App Server. Une mise à jour du CLI doit être testée explicitement.

## Données persistantes

| Ressource | Emplacement | Utilisation |
| --- | --- | --- |
| Bibliothèque | `docker-data/library` → `/data/library` | Catalogue, sources archivées, brouillons, décisions, fiches et sauvegardes |
| Sources | `NOVEL_SOURCES_DIR` → `/imports` | Montage en lecture seule |
| Connexion Codex | volume `novel_codex-home` → `/home/node/.codex` | Session gérée uniquement par Codex |
| Choix du dossier | `docker-data/settings.json` ou `.env` | Configuration locale exclue de Git |

Le nom Compose reste `novel`. Le volume Codex porte un nom explicite indépendant du chemin du dépôt. Pour une autre installation, `NOVEL_CODEX_VOLUME` permet de choisir son volume existant. Ne pas employer `docker compose down --volumes`, supprimer ce volume ou effacer `docker-data` pour une mise à jour.

## Première installation

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Up -EmptyLibrary
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Login
```

Pour monter un dossier existant, ajouter `-SourcesPath 'C:\Romans\Ma série'` à `Up`. Le lanceur mémorise ce chemin local et le réutilise. Dans Novel, importer depuis `/imports`. Pour utiliser directement Compose, copier `.env.example` vers `.env` et renseigner le chemin réel localement.

La connexion initiale suit `codex login --device-auth`, puis **Connecter Codex** dans l’interface. Le CLI affiche le code à saisir dans le navigateur ; Novel ne reçoit pas de clé API. Voir la [documentation officielle de l’authentification Codex](https://learn.chatgpt.com/docs/auth). Une connexion déjà présente dans le volume survit au remplacement du conteneur : ne pas refaire Login à chaque mise à jour.

## Importer une sauvegarde

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Up -BackupPath 'C:\Sauvegardes\Novel\sauvegarde-complete'
```

La destination `docker-data/library` doit être absente. L’import exige `COMPLETE.json`, vérifie SQLite et les EPUB référencés, puis publie une copie séparée. Les liens symboliques et fichiers d’identifiants sont refusés. Une bibliothèque existante n’est jamais remplacée. `-EmptyLibrary` et `-BackupPath` sont incompatibles.

Sans ces options, un premier démarrage tente une sauvegarde de l’ancienne instance locale sur le port 8790. Si cette instance est fermée, fournir une sauvegarde complète ou choisir explicitement une bibliothèque vide.

## Mettre à jour, arrêter et reprendre

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Status
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Up
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Restart
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Stop
```

`Up` contrôle les travaux avant et après la construction de l’image. Un travail actif empêche le remplacement. Si un conteneur tourne mais que son API est inaccessible, l’opération est refusée ; elle ne suppose pas que la bibliothèque est inactive. `Restart` recharge l’image actuelle, sans reconstruire le code. `Stop` arrête le service. Demander d’abord la pause dans Novel et attendre la fin de l’appel actif.

Le redémarrage automatique Docker conserve les données ; Novel remet les travaux incomplets en pause et exige une reprise explicite. Consulter les journaux avec `Logs`, mais ne pas les publier sans examen : ils peuvent contenir des informations privées.

## Migrer un dépôt existant

1. Vérifier que le conteneur n’a aucun travail actif, puis créer une sauvegarde complète depuis Novel.
2. Construire l’image depuis le nouveau dépôt pendant que l’ancien conteneur fonctionne encore. Conserver l’identifiant de son image pour le retour arrière.
3. Arrêter le conteneur, copier toute sa bibliothèque vers le nouveau `docker-data/library` et vérifier les empreintes de fichiers ainsi que l’intégrité SQLite. Copier également les données de l’ancien mode local s’il est utilisé, pendant qu’il est arrêté.
4. Conserver le même nom Compose, le volume Codex existant et le dossier source en lecture seule. Stocker les chemins personnels uniquement dans `.env` ou `docker-data/settings.json`.
5. Depuis le nouveau dépôt, lancer `docker compose up --detach --no-build --wait`. Vérifier `/health`, les séries, les brouillons, les validations, les fiches et `docker compose exec novel codex login status`, puis connecter le pont Novel sans générer de texte.

Conserver l’ancien dossier et sa sauvegarde jusqu’à validation. Après de nouvelles corrections dans la bibliothèque migrée, l’ancienne copie ne contient pas ces modifications : sauvegarder à nouveau avant tout retour arrière. Réactiver l’ancien fichier Compose seulement après avoir arrêté le nouveau service ; le volume Codex peut être réutilisé par une seule installation active.

Le service utilise un utilisateur non privilégié, des journaux Docker bornés, un contrôle de santé et un délai d’arrêt de trente secondes. Le contexte de construction exclut les données locales ; l’image ne contient aucun manuscrit ni identifiant utilisateur.

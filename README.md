# Novel 0.7 — atelier de traduction

[![CI](https://github.com/Relix25/Novel-Translation/actions/workflows/ci.yml/badge.svg)](https://github.com/Relix25/Novel-Translation/actions/workflows/ci.yml)

Application locale pour importer des séries, préparer leurs traductions avec Codex, comparer les textes, corriger et valider des versions précises. Le backend Python utilise uniquement la bibliothèque standard ; l’interface est construite avec React, Mantine et Tabler. Licence [MIT](LICENSE).

Novel utilise la connexion ChatGPT du CLI Codex via App Server, sans clé API. Les originaux, traductions, bibliothèques et identifiants restent dans des emplacements locaux exclus de Git. La démonstration livrée est entièrement synthétique.

## Démarrer

Le mode Docker regroupe le backend, le frontend compilé et une version précise du CLI Codex. Installer Docker Desktop puis, depuis PowerShell dans le dépôt :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Up -EmptyLibrary
powershell -NoProfile -ExecutionPolicy Bypass -File .\docker-novel.ps1 Login
```

Ouvrir [Novel](http://127.0.0.1:8791), puis cliquer sur **Connecter Codex**. La première commande crée une bibliothèque vide uniquement si elle n’existe pas encore ; les suivantes la conservent. L’option de politique PowerShell vaut pour ce processus. Pour une bibliothèque existante ou un dossier source, voir [DOCKER.md](DOCKER.md).

Pour lancer directement sous Windows ou Linux, installer Python 3.11+, Node.js 22 et le CLI Codex :

```powershell
Push-Location frontend
npm.cmd ci --no-audit --no-fund
npm.cmd run build
Pop-Location
python app.py
```

Sous Linux, utiliser `npm` et changer de dossier avec `cd`. `launch.cmd` est le lanceur Windows. Le frontend compilé est généré localement dans `frontend/dist`, exclu de Git. Le navigateur s’ouvre sur [l’instance locale](http://127.0.0.1:8788) ; garder le processus actif et utiliser Ctrl+C pour l’arrêter. `--root`, `--port` et `--no-browser` personnalisent le lancement. Les données locales sont dans `appdata` par défaut.

## Importer et traduire

1. Dans **Bibliothèque**, charger la démonstration synthétique ou créer une série. Choisir un dossier contenant des EPUB, ou des chapitres TXT/MD UTF-8. En Docker, les sources montées sont accessibles sous `/imports` ; le sélecteur de dossiers Windows n’est pas disponible dans le conteneur.
2. Examiner l’aperçu avant de confirmer l’import. Les sources et identifiants restent stables. Les EPUB originaux sont archivés localement par empreinte ; ajouter des volumes ne remplace pas les chapitres existants. Séparer les EPUB et les textes dans des dossiers distincts.
3. Choisir les langues cibles et relire les formes du glossaire. Un concept relie les noms dans chaque langue à leur première apparition. Les traductions, résumés et fiches sont séparés par paire de langues.
4. Sélectionner les chapitres, plages ou volumes voulus. **Préparer le lot** présente la sélection exacte, le profil et les estimations. Le catalogue réel doit fournir les modèles demandés : Luna High pour traduire, Sol High pour vérifier, Luna Low pour résumer et proposer des fiches. Un modèle indisponible bloque l’opération, sans remplacement silencieux.
5. Comparer la source et le brouillon dans **Atelier**, enregistrer les corrections et valider l’empreinte de cette version avec un motif de relecture. Une modification ultérieure retire son approbation et celle de son résumé.

Les traductions longues sont divisées en lots de paragraphes. Novel vérifie les identifiants, l’ordre, les empreintes et la présence du texte avant d’enregistrer un brouillon complet. La vérification IA effectue au maximum deux passes par lot ; seuls les lots corrigés ou incertains reçoivent la seconde. « Vérifié par IA » reste distinct de la validation finale et de l’approbation séparée d’un résumé.

Les caractères japonais représentés par de petites images dans un EPUB doivent être transcrits après inspection avant génération. Une source manquante ou une lecture d’image non résolue bloque l’appel ; aucun chapitre n’est inventé.

## Mémoire et suivi

Les **fiches de l’histoire** regroupent personnages, lieux, organisations, objets et observations sourcées. La vue au chapitre courant cache les noms et faits futurs suivant l’ordre des volumes. Chaque observation doit citer un passage exact et être validée séparément. Les propositions IA ne deviennent pas automatiquement des termes du glossaire. Seuls les faits approuvés, antérieurs et encore compatibles avec la source entrent dans le contexte de traduction.

**Travaux** affiche l’étape, le modèle, le lot, les passes, la progression et les tokens connus. **Pause après cet appel** conserve l’appel courant puis attend une reprise explicite. **Arrêter immédiatement** interrompt l’appel ; ses tokens consommés ne sont pas récupérables. Toute erreur, consommation inconnue ou limite atteinte met le traitement en pause. Le redémarrage ne relance aucune génération. Les lots valides peuvent être réutilisés lorsque le contexte exact et le profil correspondent.

Des limites configurables bornent les appels, tokens, durée et inactivité. Le plafond de tokens est contrôlé entre appels et lors des relevés ; un appel peut le dépasser avant de signaler sa consommation. Les estimations affichées ne mesurent pas le pourcentage du quota inclus de l’abonnement. La section **Quota du compte** affiche les fenêtres réellement retournées par Codex et leur fraîcheur ; une information absente reste indisponible.

## Sauvegardes et confidentialité

La sauvegarde depuis Novel exige l’absence de travail actif et produit un dossier marqué `COMPLETE.json` : catalogue SQLite, bases de langues, archives EPUB et rapports de relecture. L’import vérifie l’intégrité, les empreintes et la présence des archives référencées. La connexion Codex est séparée et ne fait jamais partie d’une sauvegarde de bibliothèque.

Les chemins `appdata/`, `docker-data/`, les imports, sauvegardes, bases SQLite, EPUB, captures, journaux et fichiers `.env` sont exclus de Git. Le contexte Docker utilise une liste explicite de sources publiques. Avant publication, vérifier le diff et exécuter `python tools/check_public_files.py --history`. La CI réalise également ce contrôle.

Ne pas modifier simultanément une bibliothèque historique et sa copie migrée. Après restauration sur un autre ordinateur, réassocier les dossiers sources ; les textes déjà importés restent conservés. Pour une migration et un retour arrière, consulter [DOCKER.md](DOCKER.md).

## Développer et vérifier

```powershell
test.cmd
python tools/check_public_files.py --history
```

La suite utilise des données synthétiques et des ponts simulés. La CI teste Python sous Windows et Linux, construit le frontend, audite ses dépendances de production et démarre une image Docker avec une bibliothèque vide. Aucun identifiant ChatGPT ni appel IA réel n’est nécessaire pour ces tests.

Voir [CONTRIBUTING.md](CONTRIBUTING.md), [VERIFICATION.md](VERIFICATION.md), [TACHES.md](TACHES.md) et [SECURITY.md](SECURITY.md). Les tests structurels ne remplacent pas la relecture littéraire comparée ni un essai réel des modèles.

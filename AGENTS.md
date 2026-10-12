# Novel

Ce dossier est le socle local de traduction de séries longues avec Codex.

- Générer les traductions et résumés dans Codex avec le compte ChatGPT. Ne pas ajouter de clé API ni de service externe de génération.
- Conserver les sources originales et les identifiants des segments. Ne pas fabriquer de texte pour remplacer un chapitre absent.
- Préparer le contexte avec `prepare` ; soumettre le JSON avec `submit`. Relire avant d'approuver une empreinte précise avec `review`.
- Appliquer le glossaire approuvé. Documenter les exceptions dans le motif de relecture. Un changement de glossaire exige une nouvelle validation des chapitres concernés.
- Les résumés doivent citer les segments du chapitre, être relus et approuvés séparément. Ne pas introduire de faits révélés après le chapitre du lecteur.
- La démonstration est synthétique. Elle ne constitue pas une traduction d'un roman fourni par l'utilisateur.
- Exécuter `test.cmd` après une modification du socle. Les tests structurels ne remplacent pas la lecture comparée des textes réels.
- Ne pas publier le lecteur ou programmer de traitement récurrent sans demande utilisateur correspondante.
- L'application indépendante démarre via launch.cmd/app.py ; library.py gère les séries et les concepts multilingues. Conserver les bases existantes du socle.
- Utiliser Codex App Server avec la connexion ChatGPT détenue par Codex. Ne jamais copier ou afficher les identifiants.
- Les travaux automatiques de Novel utilisent des sessions Codex éphémères. Si Codex ne confirme pas ce mode, refuser la génération ; ne jamais revenir silencieusement à un chat persistant.
- Réglage demandé par l'utilisateur : Luna High pour traduire, Luna Low pour résumer. Vérification automatique Sol High, deux passes maximum par lot ; la seconde concerne uniquement les lots corrigés ou incertains. Conserver les versions et les décisions sourcées. Aucun passage supplémentaire, changement de modèle silencieux ou redémarrage automatique après erreur. La vérification IA reste distincte de l'approbation finale et de celle des résumés.
- Les tests avec FakeBridge sont structurels et ne prouvent pas l'accès réel à un modèle. Documenter séparément les essais Codex réels et leurs tokens.

# Signaler une vulnérabilité

Pour une vulnérabilité, utiliser « Report a vulnerability » dans l’onglet Security du dépôt lorsqu’il est disponible. Éviter les rapports publics contenant des secrets ou des textes privés.

Les bibliothèques, originaux, sauvegardes, journaux et sessions Codex restent locaux. La connexion appartient au CLI Codex ; Novel n’utilise aucune clé API. Un volume Codex ne doit jamais être publié, exporté dans une image ni ajouté à Git.

Le service est publié uniquement sur l’interface locale. Il contrôle l’hôte, l’origine et un jeton CSRF pour les mutations. Il n’est pas conçu pour une exposition directe sur Internet ni pour plusieurs utilisateurs non fiables.

Avant une contribution, exécuter `python tools/check_public_files.py --history`. Ce contrôle repère les artefacts privés et certaines formes de secrets ; il ne remplace pas l’examen du diff et ne peut reconnaître tout texte privé placé dans un fichier de code.

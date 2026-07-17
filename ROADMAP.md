# Feuille de route de GUIStream

Cette feuille de route présente les évolutions envisagées pour transformer GUIStream en application stable, distribuable et simple à maintenir.

Elle décrit une direction de travail, pas une promesse de date. Les priorités peuvent évoluer selon les retours, les changements de YouTube, yt-dlp, Streamlink et FFmpeg, ainsi que les contraintes de distribution AppImage.

## Base déjà disponible

GUIStream possède actuellement les fondations suivantes :

- interface GTK 3 ;
- enregistrement Streamlink et FFmpeg direct ;
- prise en charge des sources MPEG-TS et HLS ;
- téléchargement des vidéos et lives YouTube avec yt-dlp ;
- meilleure qualité vidéo et audio, sous-titres, tags, métadonnées et miniatures ;
- lecture des listes locales M3U, M3U8 et XSPF ;
- sorties TS, MKV et MP4 ;
- diagnostic et analyse de la santé des enregistrements ;
- installation directe et vérifiée de yt-dlp, Deno, Streamlink, FFmpeg et FFprobe.

## Principes du projet

- Ne jamais écraser silencieusement un fichier utilisateur.
- Conserver autant que possible les données déjà enregistrées après une interruption.
- Ne pas dépendre obligatoirement du gestionnaire de paquets de la distribution.
- Vérifier cryptographiquement les exécutables téléchargés avant leur activation.
- Afficher les commandes, erreurs et chemins importants dans les journaux.
- Garder un mode automatique simple tout en proposant des réglages avancés facultatifs.
- Ne pas contourner les DRM ou les protections d’accès des plateformes.

## Légende

- **Priorité haute** : nécessaire avant une version stable.
- **Priorité moyenne** : amélioration importante mais non bloquante.
- **Priorité basse** : évolution à étudier après stabilisation.

## Version 0.6 — Consolidation

Objectif : fiabiliser toutes les fonctions déjà présentes avant d’ajouter de nouveaux modes complexes.

### Architecture

- [ ] **Priorité haute** — Découper le script principal en modules : interface, détection des sources, YouTube, enregistrement, listes et dépendances.
- [ ] **Priorité haute** — Centraliser le lancement et l’arrêt des sous-processus.
- [ ] **Priorité haute** — Ajouter une gestion structurée des erreurs avec messages courts dans l’interface et détails dans les journaux.
- [ ] **Priorité moyenne** — Introduire une constante de version utilisée par l’application, le diagnostic et les paquets.
- [ ] **Priorité moyenne** — Définir des dossiers XDG séparés pour les données, la configuration, le cache et les journaux.

### Configuration

- [ ] **Priorité haute** — Mémoriser le dossier de sortie, le conteneur, la résolution et les options YouTube.
- [ ] **Priorité moyenne** — Ajouter un bouton de restauration des réglages par défaut.
- [ ] **Priorité moyenne** — Permettre de choisir manuellement le chemin d’un outil externe.
- [ ] **Priorité moyenne** — Enregistrer la taille et la position de la fenêtre.

### Fiabilité

- [ ] **Priorité haute** — Tester les URL expirées, les coupures réseau et les flux sans audio ou sans vidéo.
- [ ] **Priorité haute** — Vérifier les collisions de noms avant chaque téléchargement.
- [ ] **Priorité haute** — Améliorer la reprise et l’identification des fichiers `.part`.
- [ ] **Priorité moyenne** — Ajouter une limite configurable au nombre de tentatives de reconnexion.
- [ ] **Priorité moyenne** — Produire un rapport de diagnostic exportable dans un fichier texte.

### Tests

- [ ] **Priorité haute** — Tests unitaires des parseurs M3U et XSPF.
- [ ] **Priorité haute** — Tests unitaires de construction des commandes yt-dlp, Streamlink et FFmpeg.
- [ ] **Priorité haute** — Tests des choix d’architecture pour les installateurs de dépendances.
- [ ] **Priorité moyenne** — Tests d’intégration avec de petits médias locaux et un serveur HTTP de test.

### Critères de validation

- Aucun blocage de l’interface pendant une analyse ou un téléchargement.
- Un arrêt demandé conserve ou finalise le fichier lorsque le moteur le permet.
- Les réglages essentiels sont restaurés au redémarrage.
- Les parseurs et constructeurs de commandes sont couverts par des tests automatisés.

## Version 0.7 — File d’attente et programmation

Objectif : dépasser le fonctionnement limité à un seul lien préparé manuellement.

### File d’attente

- [ ] **Priorité haute** — Sélection multiple dans la fenêtre M3U/XSPF.
- [ ] **Priorité haute** — Ajouter les sélections à une file d’attente au lieu de démarrer immédiatement.
- [ ] **Priorité haute** — Afficher l’état de chaque tâche : en attente, analyse, téléchargement, terminé, interrompu ou erreur.
- [ ] **Priorité haute** — Réorganiser, retirer ou relancer une tâche.
- [ ] **Priorité moyenne** — Choisir entre arrêt après la tâche actuelle et arrêt immédiat.
- [ ] **Priorité moyenne** — Exporter et réimporter une file d’attente.

### Programmation

- [ ] **Priorité haute** — Programmer une heure de démarrage.
- [ ] **Priorité haute** — Définir une durée maximale d’enregistrement.
- [ ] **Priorité moyenne** — Répéter une programmation certains jours.
- [ ] **Priorité moyenne** — Prévenir lorsque la source n’est pas disponible à l’heure prévue.
- [ ] **Priorité basse** — Autoriser plusieurs enregistrements simultanés avec une limite configurable.

### Critères de validation

- La file survit à un redémarrage de GUIStream.
- Une tâche échouée ne bloque pas les suivantes.
- La sélection multiple fonctionne avec plusieurs fichiers M3U et XSPF.
- Les programmations utilisent le fuseau horaire local et affichent leur prochaine exécution.

## Version 0.8 — YouTube avancé

Objectif : proposer un niveau de choix proche d’un gestionnaire de téléchargement spécialisé tout en conservant le mode automatique.

### Formats

- [ ] **Priorité haute** — Afficher les formats vidéo avec résolution, codec, fréquence d’images, HDR, taille estimée et débit.
- [ ] **Priorité haute** — Afficher séparément les pistes audio et leur langue.
- [ ] **Priorité haute** — Ajouter un mode audio uniquement avec M4A, Opus ou MP3 lorsque FFmpeg le permet.
- [ ] **Priorité moyenne** — Créer des préréglages : compatibilité, meilleure qualité, taille réduite et archivage.
- [ ] **Priorité moyenne** — Estimer l’espace disque nécessaire avant le téléchargement.

### Sous-titres et métadonnées

- [ ] **Priorité haute** — Sélectionner plusieurs langues de sous-titres.
- [ ] **Priorité moyenne** — Choisir entre intégration, fichiers séparés ou les deux.
- [ ] **Priorité moyenne** — Choisir le format de sous-titres, par exemple VTT, SRT ou ASS.
- [ ] **Priorité moyenne** — Prévisualiser les tags et permettre de désactiver certains champs.

### Listes et authentification

- [ ] **Priorité haute** — Gérer les playlists YouTube avec sélection des éléments.
- [ ] **Priorité moyenne** — Gérer les URL de chaînes et les collections prises en charge par yt-dlp.
- [ ] **Priorité moyenne** — Importer facultativement les cookies depuis un navigateur via yt-dlp, sans les copier dans les journaux.
- [ ] **Priorité moyenne** — Reprendre un téléchargement interrompu lorsque yt-dlp le permet.

### Lives

- [ ] **Priorité haute** — Afficher clairement les états à venir, en direct et terminé.
- [ ] **Priorité haute** — Améliorer la reconnexion après une coupure momentanée.
- [ ] **Priorité moyenne** — Permettre l’arrêt automatique à une heure ou après une durée donnée.
- [ ] **Priorité basse** — Découper automatiquement les très longs lives en plusieurs fichiers.

### Critères de validation

- Le mode automatique reste utilisable sans comprendre les identifiants de formats.
- Les sélections manuelles produisent la combinaison vidéo/audio demandée.
- Aucun cookie, jeton ou en-tête sensible n’apparaît dans les journaux.
- Une playlist peut être filtrée avant son ajout à la file d’attente.

## Version 0.9 — Distribution et mises à jour

Objectif : rendre les versions faciles à construire, vérifier et distribuer.

### AppImage

- [ ] **Priorité haute** — Construire des AppImages reproductibles pour Linux x86_64 et ARM64.
- [ ] **Priorité haute** — Inclure GTK, PyGObject et les bibliothèques indispensables au démarrage.
- [ ] **Priorité haute** — Publier les sommes SHA-256 de chaque AppImage.
- [ ] **Priorité moyenne** — Ajouter un fichier `.desktop`, une icône et les catégories de menu appropriées.
- [ ] **Priorité moyenne** — Tester le fonctionnement avec et sans FUSE grâce au mode extraction-exécution.

### Publication

- [ ] **Priorité haute** — Automatiser les tests et la construction à chaque version.
- [ ] **Priorité haute** — Générer les notes de version depuis le changelog validé.
- [ ] **Priorité haute** — Afficher la version de GUIStream dans l’interface et le diagnostic.
- [ ] **Priorité moyenne** — Vérifier les nouvelles versions de GUIStream depuis une source configurable.
- [ ] **Priorité moyenne** — Télécharger une nouvelle AppImage sans remplacer automatiquement la version en cours.
- [ ] **Priorité basse** — Ajouter une signature de publication en plus du SHA-256.

### Critères de validation

- Une version peut être reconstruite à partir de son étiquette Git.
- Les AppImages démarrent sur plusieurs distributions glibc prises en charge.
- Les sommes publiées correspondent exactement aux fichiers distribués.
- La mise à jour de GUIStream exige toujours une confirmation explicite.

## Version 1.0 — Version stable

Objectif : fournir une base documentée et suffisamment robuste pour une utilisation quotidienne.

- [ ] **Priorité haute** — Corriger tous les problèmes bloquants identifiés pendant les versions 0.6 à 0.9.
- [ ] **Priorité haute** — Geler et documenter le format du fichier de configuration.
- [ ] **Priorité haute** — Tester les migrations de configuration entre versions.
- [ ] **Priorité haute** — Finaliser le README, le changelog, la feuille de route et le guide de contribution.
- [ ] **Priorité haute** — Vérifier l’accessibilité au clavier et les libellés GTK.
- [ ] **Priorité moyenne** — Préparer la traduction de l’interface avec gettext.
- [ ] **Priorité moyenne** — Ajouter une page **À propos** avec versions, licences et sources des composants.
- [ ] **Priorité moyenne** — Définir une politique de prise en charge des anciennes versions.

### Critères de validation

- Aucun problème bloquant connu sur les plateformes annoncées.
- Tous les téléchargements de dépendances sont vérifiés avant installation.
- Les tâches interrompues sont signalées clairement et leurs données récupérables sont conservées.
- Les fonctions principales disposent de tests automatisés et d’une documentation utilisateur.

## Après la version 1.0

- [ ] **Priorité moyenne** — Historique consultable des téléchargements et enregistrements.
- [ ] **Priorité moyenne** — Préréglages exportables et partageables.
- [ ] **Priorité moyenne** — Notifications de bureau en fin de tâche ou en cas d’erreur.
- [ ] **Priorité basse** — Système d’extensions pour ajouter des traitements ou des sources sans modifier le cœur.
- [ ] **Priorité basse** — Interface distante locale, désactivée par défaut et protégée par authentification.
- [ ] **Priorité basse** — Version GTK 4 après stabilisation de la version GTK 3.

## Travaux continus

Ces tâches accompagnent toutes les étapes :

- mettre à jour régulièrement yt-dlp, Streamlink, Deno et FFmpeg dans les tests ;
- vérifier les changements d’arguments de ligne de commande ;
- éviter l’exposition d’URL signées, cookies et jetons dans les rapports partagés ;
- documenter les nouvelles options au moment de leur ajout ;
- mesurer l’utilisation du disque et de la mémoire pendant les longs enregistrements ;
- conserver la compatibilité des listes M3U et XSPF existantes ;
- maintenir des messages d’erreur compréhensibles sans masquer les détails techniques.

## Hors périmètre

GUIStream n’a pas vocation à :

- contourner les DRM, abonnements, contrôles d’accès ou restrictions territoriales ;
- télécharger un contenu sans autorisation lorsque la plateforme ou les droits applicables l’interdisent ;
- devenir un éditeur vidéo complet ;
- réencoder systématiquement les captures lorsque le remux suffit ;
- installer ou remplacer GTK et les bibliothèques critiques du système avec des privilèges administrateur.

## Prochain ordre de travail conseillé

1. Ajouter une version interne et des dossiers de configuration XDG.
2. Extraire les installateurs de dépendances dans un module testable.
3. Extraire la génération des commandes yt-dlp, Streamlink et FFmpeg.
4. Ajouter les tests des listes M3U/XSPF et des commandes.
5. Mémoriser les réglages essentiels.
6. Ajouter une véritable file d’attente.
7. Autoriser la sélection multiple dans les listes locales.
8. Ajouter la programmation et la durée maximale.
9. Développer le sélecteur avancé de formats YouTube.
10. Automatiser la construction et la vérification des AppImages.

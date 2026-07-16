# Journal des modifications de GUIStream

Toutes les évolutions importantes de GUIStream sont répertoriées dans ce fichier.

Le format s’inspire de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Les versions historiques 0.1 à 0.5 ne possédaient pas de date connue ; elles sont conservées sans en inventer.

## [0.5.1] - 2024-07-16

### Ajouté

#### Téléchargement et enregistrement

- Détection automatique des liens YouTube, des sources Streamlink et des flux directement lisibles par FFmpeg.
- Prise en charge directe des sources MPEG-TS, HLS et autres médias reconnus par FFmpeg, sans imposer Streamlink.
- Enregistrement en TS et remux sans réencodage vers MKV ou MP4.
- Reconnexion automatique de FFmpeg pour les flux HTTP et HTTPS interrompus.
- Conservation des données déjà enregistrées lorsqu’un flux s’arrête ou lorsque l’utilisateur appuie sur Stop.
- Affichage en temps réel de la durée, de la taille enregistrée ou de la progression YouTube.

#### YouTube

- Téléchargement des vidéos YouTube avec yt-dlp.
- Sélection automatique de la meilleure vidéo et du meilleur audio disponibles, au-delà de 360p.
- Limite de résolution configurable de 360p à 4320p, ou meilleure qualité sans limite.
- Choix du conteneur final MKV ou MP4.
- Enregistrement des lives YouTube à partir du moment présent.
- Mode expérimental d’enregistrement d’un live depuis son début avec `--live-from-start`.
- Analyse préalable du titre, de la chaîne, de l’état du live, des formats, de la résolution maximale, des tags et des sous-titres.
- Sélection des sous-titres disponibles après analyse du lien.
- Prise en charge des sous-titres automatiques, de leur intégration dans la vidéo et de l’exclusion du chat en direct.
- Intégration facultative des métadonnées, des tags et de la miniature.
- Conservation facultative du fichier `.info.json` complet.
- Détection de Deno, Node.js, QuickJS ou Bun pour éviter les formats YouTube limités.
- Blocage explicite du téléchargement YouTube lorsqu’aucun moteur JavaScript n’est disponible, afin d’éviter une vidéo limitée à 360p.
- Arrêt propre de yt-dlp avec finalisation du fichier déjà téléchargé lorsque cela est possible.

#### Listes locales

- Détection automatique des fichiers `.m3u`, `.m3u8` et `.xspf` placés à côté de l’AppImage ou du script.
- Lecture des titres, groupes, albums, créateurs, URL distantes et chemins locaux présents dans les listes.
- Résolution des chemins relatifs depuis le dossier de la liste.
- Suppression des liens dupliqués au chargement.
- Nouvelle fenêtre affichant toutes les sources disponibles.
- Filtrage par fichier, recherche par nom, groupe ou URL et actualisation des listes sans redémarrer GUIStream.
- Lancement de l’enregistrement de la source sélectionnée en TS, MKV ou MP4.

#### Dépendances

- Recherche prioritaire des outils dans le dossier utilisateur de GUIStream, puis dans le dossier `bin` de l’application et enfin dans le `PATH`.
- Gestionnaire de dépendances accessible depuis la fenêtre **Mises à jour**.
- Bouton d’installation de tous les éléments manquants.
- Installation ou mise à jour individuelle de yt-dlp, Deno, FFmpeg/FFprobe et Streamlink.
- Téléchargement du binaire autonome officiel yt-dlp adapté à l’architecture.
- Téléchargement du binaire officiel Deno adapté à la plateforme.
- Installation de l’AppImage officielle Streamlink sous Linux x86_64 et ARM64.
- Installation de FFmpeg et FFprobe depuis les builds Linux BtbN référencés par le site FFmpeg.
- Vérification SHA-256 obligatoire avant activation de chaque téléchargement.
- Installation atomique dans le dossier utilisateur, sans `sudo`, `pacman` ni modification du système.
- Suppression automatique des téléchargements partiels ou non vérifiés.

#### Diagnostic et robustesse

- Diagnostic détaillé de GTK, Python, Streamlink, yt-dlp, FFmpeg, FFprobe et du moteur JavaScript YouTube.
- Vérification en ligne des versions de Streamlink et yt-dlp.
- Analyse des avertissements produits pendant l’enregistrement.
- Indicateur de santé du stream : non analysé, à surveiller, instable, problème détecté ou OK.
- Analyse du fichier final par FFmpeg afin de détecter les erreurs de paquets, codecs ou horodatages.
- Journalisation des commandes exécutées et des chemins utilisés.
- Proposition automatique d’un repli MKV lorsque le remux MP4 échoue.
- Ouverture directe du dossier contenant le fichier final.

### Modifié

- Le bouton principal indique maintenant **Télécharger / enregistrer** afin de couvrir les vidéos, les lives et les flux classiques.
- Le mode automatique choisit yt-dlp pour YouTube, Streamlink pour les sites compatibles et FFmpeg pour les sources directes.
- Les noms de fichiers sont nettoyés avant leur utilisation et restent limités à une longueur raisonnable.
- Les dépendances installées par GUIStream sont conservées hors du montage en lecture seule de l’AppImage.

## [0.5.0]

### Ajouté

- Génération automatique du nom du fichier à partir du titre détecté.

## [0.4.0]

### Ajouté

- Test des liens avant l’enregistrement.

## [0.3.0]

### Ajouté

- Remux des enregistrements.

## [0.2.0]

### Ajouté

- Fenêtre de diagnostic.

## [0.1.0]

### Ajouté

- Première interface GTK de GUIStream.

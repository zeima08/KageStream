# Journal des modifications de KageStream

Toutes les évolutions importantes de KageStream sont répertoriées dans ce fichier.

Le format s’inspire de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Les versions historiques 0.1 à 0.5 ne possédaient pas de date connue ; elles sont conservées sans en inventer.

## [0.6.0] - 2026-07-30

### Ajouté

#### Enregistrement et arrêt

- Arrêt robuste en trois paliers (SIGINT puis SIGTERM puis SIGKILL) avec attente de la fermeture réelle du processus avant de continuer.
- Vérification de la fermeture effective du fichier TS après l’arrêt, par contrôle de la stabilité de sa taille.
- Reconnexion automatique lorsqu’un flux Streamlink ou FFmpeg direct s’interrompt brutalement : nouvelle tentative toutes les 15 secondes pendant 2 minutes avant d’abandonner et de finaliser l’enregistrement avec les données déjà capturées.
- Fusion automatique des segments récupérés après une ou plusieurs reconnexions, avant l’analyse et le remux.
- Programmation d’un enregistrement avec heure de début et heure de fin, pour Streamlink, l’IPTV et FFmpeg direct. L’arrêt à l’heure de fin suit exactement la même procédure robuste que le bouton **Stop**.

#### Remux et vérification

- Boîte de dialogue proposant, à la fin d’un enregistrement, de vérifier le fichier TS (paquets corrompus, erreurs DTS, timestamps invalides, résumé de l’état général) avant le remux, ou de remuxer directement.
- Remux organisé en paliers de repli successifs : vidéo + audio + sous-titres, puis vidéo + audio seuls si le télétexte ou les sous-titres DVB du multiplex sont incompatibles avec le conteneur, puis un mapping minimal en dernier recours. Le remux tente désormais toujours de produire un fichier plutôt que d’abandonner silencieusement.
- Filtre `aac_adtstoasc` appliqué pendant le remux pour corriger les flux audio AAC de diffusion DVB dépourvus d’un en-tête ADTS exploitable par le conteneur de sortie.

#### Interface

- Affichage de l’heure locale et de l’heure de Tokyo dans la fenêtre principale, actualisées chaque seconde via `zoneinfo`.

### Modifié

- Le bouton **Stop** et l’arrêt automatique programmé partagent désormais la même procédure d’arrêt robuste et la même vérification de fermeture du fichier.
- Le remux ne s’arrête plus après un seul échec sans avoir produit de fichier : il retente automatiquement avec un mapping réduit avant d’abandonner et de proposer le repli MKV ou de conserver le TS.

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
- Filtrage par fichier, recherche par nom, groupe ou URL et actualisation des listes sans redémarrer KageStream.
- Lancement de l’enregistrement de la source sélectionnée en TS, MKV ou MP4.

#### Dépendances

- Recherche prioritaire des outils dans le dossier utilisateur de KageStream, puis dans le dossier `bin` de l’application et enfin dans le `PATH`.
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
- Les dépendances installées par KageStream sont conservées hors du montage en lecture seule de l’AppImage.

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

- Première interface GTK de KageStream.

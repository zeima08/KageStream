# KageStream

KageStream est une interface GTK 3 conçue par Zeima pour télécharger des vidéos, enregistrer des lives, sauvegarder des flux réseau et télécharger de la musique sans devoir composer manuellement les commandes Streamlink, yt-dlp ou FFmpeg.

L’application accepte les liens YouTube, les sites reconnus par Streamlink, les sources MPEG-TS/HLS directement lisibles par FFmpeg, les liens provenant de listes locales M3U, M3U8 et XSPF, ainsi que les liens YouTube Music, SoundCloud et Bandcamp.

L’interface est organisée autour d’une barre latérale (**Capturer**, **Captures**, **Musique**, **YouTube**, **Téléchargements**, **Outils**) qui regroupe les fonctions par usage plutôt que par onglets.

## Fonctionnalités principales

- Détection automatique du moteur approprié : yt-dlp, Streamlink ou FFmpeg.
- Captures multiples en parallèle : chaque clic sur **Enregistrer** ou **Programmer** ajoute une nouvelle capture sans arrêter les autres — pratique pour plusieurs chaînes TV en même temps. Toutes sont suivies dans l’onglet **Captures**, avec arrêt individuel. La finalisation (vérification, remux, conversion) reste séquentielle pour ne pas saturer le CPU si plusieurs captures se terminent en même temps.
- Découpe rapide d’un enregistrement terminé (bornes début/fin, copie de flux sans réencodage) pour obtenir un seul fichier propre à partager.
- Téléchargement de musique depuis YouTube Music, SoundCloud et Bandcamp, avec sélection des pistes, profils de format (Compatible, Qualité maximale, Archivage, Personnalisé) et file de téléchargement dédiée.
- Téléchargement YouTube dans la meilleure qualité vidéo et audio disponibles.
- Limite de résolution configurable jusqu’à 8K.
- Enregistrement des lives YouTube à partir de maintenant ou, de façon expérimentale, depuis leur début.
- Choix et intégration des sous-titres manuels ou automatiques.
- Intégration des métadonnées, tags, miniatures et fichiers `.info.json`.
- Enregistrement des flux classiques en TS, MKV ou MP4.
- Arrêt robuste des enregistrements (SIGINT puis SIGTERM puis SIGKILL) avec vérification que le fichier TS est bien fermé.
- Reconnexion automatique en cas de coupure momentanée d’un flux Streamlink ou FFmpeg direct, pendant 2 minutes avant abandon.
- Programmation d’un enregistrement avec heure de début et de fin, pour Streamlink, l’IPTV et FFmpeg direct.
- Vérification optionnelle du fichier TS (paquets corrompus, erreurs DTS, timestamps invalides) avant le remux.
- Détection et exploration des listes M3U, M3U8 et XSPF placées à côté de l’application.
- Recherche des chaînes et groupes contenus dans les listes locales.
- Diagnostic des dépendances et analyse de la santé du fichier enregistré.
- Installation directe des dépendances utilisateur sans `sudo` ni gestionnaire de paquets.
- Horloge locale et horloge de Tokyo affichées en continu dans la fenêtre principale.

## Démarrage

### Avec une AppImage

Rends l’AppImage exécutable puis lance-la :

```bash
chmod +x KageStream-x86_64.AppImage
./KageStream-x86_64.AppImage
```

Une AppImage étant montée en lecture seule, les dépendances téléchargées par KageStream sont conservées dans un dossier utilisateur persistant :

```text
~/.local/share/KageStream/bin
```

### Avec le script Python

Le lancement du script nécessite Python 3, PyGObject et GTK 3. Les autres outils peuvent ensuite être récupérés depuis la fenêtre **Mises à jour**.

```bash
chmod +x kagestream.py
python3 kagestream.py
```

## Dépendances

### Nécessaires au démarrage de l’interface

- Python 3
- PyGObject (`gi`)
- GTK 3

GTK et PyGObject doivent être fournis par l’AppImage ou le système. KageStream ne tente pas de remplacer les bibliothèques graphiques du système.

### Outils multimédias

| Outil                         | Utilisation                                      | Installation directe        |
| ----------------------------- | ------------------------------------------------ | --------------------------- |
| yt-dlp                        | Vidéos et lives YouTube                          | Oui                         |
| Deno, Node.js, QuickJS ou Bun | Résolution des formats YouTube modernes          | Deno : oui                  |
| FFmpeg                        | Capture directe, assemblage audio/vidéo et remux | Oui sous Linux x86_64/ARM64 |
| FFprobe                       | Analyse des sources et diagnostic                | Oui avec FFmpeg             |
| Streamlink                    | Extraction des flux des sites compatibles        | Oui sous Linux x86_64/ARM64 |
| aria2c (optionnel)            | Accélère les téléchargements yt-dlp (multi-connexions) | Non — via le gestionnaire de paquets du système |

aria2c n’a pas de binaire autonome officiel pour Linux : installe-le via le gestionnaire de paquets de ta distribution, par exemple `sudo pacman -S aria2` sous Arch, `sudo apt install aria2` sous Debian/Ubuntu ou `sudo dnf install aria2` sous Fedora. KageStream le détecte automatiquement dans le `PATH` une fois installé et l’utilise pour accélérer les téléchargements yt-dlp.

Pour installer ce qui manque :

1. Ouvre **Mises à jour**.
2. Clique sur **Installer tous les éléments manquants**.
3. Vérifie la liste proposée puis confirme.

Des boutons séparés permettent aussi de mettre à jour ou réinstaller yt-dlp, Deno, FFmpeg/FFprobe et Streamlink.

Chaque téléchargement est contrôlé avec une somme SHA-256 publiée par sa source avant d’être activé. Un fichier partiel ou non vérifié n’est pas conservé. KageStream utilise en priorité les outils de son dossier utilisateur, puis ceux embarqués dans l’application, puis ceux disponibles dans le `PATH`.

## Télécharger une vidéo YouTube

1. Colle l’URL de la vidéo.
2. Laisse le mode sur **Automatique** ou choisis **Télécharger une vidéo YouTube**.
3. Clique sur **Tester le lien** pour charger le titre, les résolutions et les langues de sous-titres.
4. Choisis la résolution maximale, le conteneur MKV ou MP4 et les options de métadonnées.
5. Sélectionne le dossier de sortie.
6. Clique sur **Télécharger / enregistrer**.

L’option **Meilleure disponible — sans limite** demande à yt-dlp de sélectionner la meilleure piste vidéo et la meilleure piste audio. FFmpeg est ensuite utilisé pour les réunir dans le conteneur final.

KageStream exige un moteur JavaScript compatible pour les téléchargements YouTube. Sans Deno, Node.js, QuickJS ou Bun, l’opération est bloquée afin d’éviter de retomber silencieusement sur une qualité limitée à 360p.

## Enregistrer un live YouTube

Deux modes sont disponibles :

- **Live YouTube — à partir de maintenant** enregistre à partir du direct actuel.
- **Live YouTube — depuis le début** demande à yt-dlp de reprendre le live depuis son commencement lorsque YouTube le permet. Ce mode reste expérimental.

Le bouton **Stop** envoie un arrêt propre à yt-dlp. KageStream tente ensuite de finaliser et conserver les données déjà téléchargées.

## Enregistrer un flux classique ou MPEG-TS

1. Colle l’URL du flux.
2. Utilise le mode **Automatique** ou **Streamlink / flux direct**.
3. Clique sur **Tester le lien**.
4. Choisis la qualité proposée par Streamlink, ou la qualité `source` pour un média direct.
5. Choisis le format TS, MKV ou MP4.
6. Lance l’enregistrement.

KageStream essaie d’abord Streamlink. Si Streamlink ne reconnaît pas le lien, FFprobe puis FFmpeg vérifient s’il s’agit d’une source multimédia directe. Les flux HTTP et HTTPS bénéficient d’options de reconnexion.

Si le flux s’interrompt brutalement en cours d’enregistrement (coupure réseau, source IPTV momentanément indisponible), KageStream retente automatiquement de retrouver la source toutes les 15 secondes pendant 2 minutes avant d’abandonner. Si la source revient, l’enregistrement reprend et les segments récupérés sont fusionnés dans le fichier final ; sinon, l’enregistrement s’arrête et conserve les données déjà capturées.

Chaque clic sur **Enregistrer le flux** démarre une nouvelle capture sans toucher aux autres : plusieurs chaînes peuvent être capturées en même temps, chacune avec son propre statut, sa propre santé et son propre bouton d’arrêt, dans l’onglet **Captures**. Le bouton **Stop** de chaque ligne envoie un `SIGINT`, attend quelques secondes, puis escalade en `SIGTERM` et enfin `SIGKILL` si le processus ne se termine pas de lui-même ; KageStream vérifie ensuite que le fichier TS est bien fermé avant de continuer.

À la fin d’un enregistrement destiné à MKV ou MP4, la ligne correspondante dans l’onglet **Captures** propose de **vérifier le fichier TS** (paquets corrompus, erreurs DTS, timestamps invalides, résumé de l’état général) avant le remux, ou de **remuxer directement**.

La capture est d’abord conservée en MPEG-TS. Pour MKV ou MP4, FFmpeg effectue ensuite un remux sans réencoder la vidéo, en plusieurs paliers de repli : vidéo + audio + sous-titres, puis vidéo + audio seuls si le télétexte ou les sous-titres DVB du multiplex sont incompatibles avec le conteneur, puis un mapping minimal en dernier recours. Le remux corrige aussi automatiquement les flux audio AAC de diffusion DVB dépourvus d’un en-tête ADTS exploitable. Si MP4 refuse certains codecs malgré ces replis, KageStream propose un passage vers MKV et conserve toujours le TS original en cas d’échec.

Cette étape de finalisation (vérification, remux, conversion) est gourmande en CPU : elle est traitée **une capture à la fois**, même si plusieurs enregistrements se terminent en même temps. Une capture en attente de finalisation apparaît avec le statut « En attente de remux » le temps que son tour arrive — l’enregistrement des autres captures n’est jamais affecté.

## Couper une vidéo

Une fois une capture **Terminée** (visible dans l’onglet **Captures**), le bouton **Couper cette vidéo…** permet de retirer un générique en début, une pub en fin, ou tout autre passage inutile, pour n’envoyer qu’un seul fichier propre.

1. Clique sur **Couper cette vidéo…**.
2. Renseigne le **début** et la **fin** à conserver, au format `HH:MM:SS`, `MM:SS` ou en secondes.
3. Confirme : FFmpeg copie le flux (sans réencodage) entre ces deux bornes dans un nouveau fichier `<nom>_coupe.<extension>`.

Le fichier original n’est jamais modifié ni supprimé — la découpe crée toujours un fichier séparé. KageStream reste un outil de capture, pas un éditeur vidéo complet : seule une plage unique à conserver peut être définie.

## Télécharger de la musique

Dans la barre latérale, ouvre **Musique**.

1. Colle un lien YouTube Music, SoundCloud ou Bandcamp (morceau, album ou playlist).
2. Clique sur **Analyser**. KageStream détecte automatiquement le fournisseur à partir de l’URL puis délègue l’analyse à yt-dlp — aucune API officielle n’est nécessaire.
3. Vérifie le titre, l’artiste, la pochette et la liste des pistes. Décoche celles que tu ne veux pas télécharger, ou utilise **Tout cocher** / **Tout décocher**.
4. Choisis un profil : **Compatible** (MP3 192 kbps), **Qualité maximale**, **Archivage** (FLAC), ou **Personnalisé** pour choisir toi-même le format parmi MP3, AAC, M4A, Opus, Vorbis, FLAC ou l’original sans conversion.
5. Choisis le dossier de destination puis clique sur **Télécharger la sélection**.

Chaque piste est enregistrée sous `Artiste/Album/` dans le dossier choisi, avec des noms de fichiers nettoyés. La progression est visible dans l’onglet **Téléchargements**, qui liste les tâches en cours, en attente et terminées, permet d’annuler une tâche active et d’ouvrir directement le dossier une fois le téléchargement terminé.

## Programmer un enregistrement

Dans l’onglet **Flux & IPTV**, la section **Programmation d’un enregistrement** permet de définir :

- une **heure de début** (format `HH:MM` ou `HH:MM:SS`) ;
- une **heure de fin** dans le même format.

Colle le lien à enregistrer, renseigne les deux heures puis clique sur **Programmer**. KageStream attend automatiquement l’heure de début, lance l’enregistrement, puis l’arrête à l’heure de fin en suivant exactement la même procédure robuste que le bouton **Stop**. La programmation apparaît aussitôt dans l’onglet **Captures**, avec un bouton **Annuler la programmation** sur sa ligne — plusieurs programmations (et captures déjà en cours) peuvent coexister sans s’attendre.

La programmation fonctionne avec Streamlink, l’IPTV et FFmpeg direct. Si l’heure de fin est antérieure à l’heure de début, KageStream programme l’arrêt le lendemain.

## Utiliser des listes M3U et XSPF

Place un ou plusieurs fichiers parmi les formats suivants dans le même dossier que l’AppImage :

```text
*.m3u
*.m3u8
*.xspf
```

Lors de l’exécution du script Python, utilise le dossier contenant le script.

Clique ensuite sur **Listes locales**. La fenêtre permet de :

- choisir une liste ou afficher toutes les listes ;
- rechercher un nom, un groupe ou une URL ;
- actualiser les fichiers sans redémarrer ;
- choisir TS, MKV ou MP4 ;
- lancer l’enregistrement du lien sélectionné.

Les chemins relatifs sont résolus depuis le dossier de leur liste. Les URL et chemins en double sont ignorés.

## Diagnostic et journaux

Le bouton **Diagnostic** affiche l’état et la version de :

- GTK et Python ;
- Streamlink ;
- yt-dlp ;
- FFmpeg et FFprobe ;
- Deno, Node.js, QuickJS ou Bun.

Pendant un enregistrement, KageStream surveille les messages de Streamlink et FFmpeg. Une fois la capture terminée, FFmpeg relit le fichier afin de repérer les paquets corrompus, les erreurs de décodage et les horodatages incohérents.

Les commandes exécutées et les erreurs détaillées restent visibles dans la zone de journal de la fenêtre principale.

## Résolution des problèmes

### YouTube reste limité à 360p

Ouvre **Mises à jour** et installe Deno. Relance ensuite **Tester le lien**. KageStream bloque normalement le téléchargement lorsque le moteur JavaScript manque, précisément pour éviter ce résultat.

### yt-dlp ou un miroir Arch est indisponible

Utilise **Mises à jour → Installer yt-dlp directement**. Le binaire autonome est téléchargé depuis les versions officielles de yt-dlp et ne dépend pas de `pacman`.

### Une liste locale n’apparaît pas

Vérifie que le fichier possède bien l’extension `.m3u`, `.m3u8` ou `.xspf` et qu’il se trouve à côté du fichier AppImage, pas dans son montage temporaire. Clique ensuite sur **Actualiser** dans la fenêtre des listes.

### Le remux MP4 ou MKV échoue

KageStream retente automatiquement avec un mapping réduit (sous-titres puis pistes secondaires exclus) avant d’abandonner : le télétexte, les sous-titres DVB ou un flux audio AAC de diffusion mal formé sont les causes les plus fréquentes d’un multiplex IPTV/DVB incompatible avec un conteneur. Si toutes les tentatives échouent malgré tout, accepte le repli MKV proposé pour un MP4, ou conserve le fichier TS créé pendant la capture — il n’est jamais supprimé. Le détail des tentatives et des erreurs FFmpeg reste visible dans le journal technique.

### Streamlink ou FFmpeg n’est pas détecté

Ouvre **Mises à jour** et utilise le bouton global d’installation. Le chemin réellement détecté est visible dans **Diagnostic**.

## Limites connues

- Plusieurs captures (Streamlink/IPTV/FFmpeg direct) peuvent tourner en même temps, mais un seul téléchargement YouTube/Dailymotion ou un seul téléchargement musical peuvent être actifs à la fois.
- La finalisation des captures (vérification, remux, conversion) est traitée une à la fois, même si plusieurs enregistrements se terminent au même moment.
- La découpe d’une vidéo se limite à une seule plage début/fin en copie de flux ; KageStream n’a pas vocation à devenir un éditeur vidéo complet.
- Le mode live YouTube depuis le début dépend des possibilités offertes par YouTube et yt-dlp.
- Les contenus protégés par DRM ne sont pas pris en charge.
- L’installation directe de Streamlink et FFmpeg est actuellement destinée à Linux x86_64 et ARM64.
- L’AppImage Streamlink nécessite une distribution Linux basée sur glibc.
- Une interruption brutale du système peut laisser un fichier `.part` ou un TS incomplet, même si KageStream essaie de finaliser proprement les arrêts demandés depuis l’interface.
- La reconnexion automatique et la programmation d’un enregistrement fonctionnent avec Streamlink, l’IPTV et FFmpeg direct, mais pas encore avec YouTube.
- La file de téléchargement musical traite une piste à la fois et ne survit pas à un redémarrage de KageStream ; l’organisation des fichiers est fixée à `Artiste/Album` sans option de personnalisation pour l’instant.
- Sur des distributions basée sur Arch,il est possible que les dépendances ne veulent pas se télécharger automatiquement,merci de récupérés les dépendances via le ``` sudo pacman -S``` suivi de la dépendance manquante.
## Historique

Consulte [CHANGELOG.md](CHANGELOG.md) pour le détail des évolutions.

## Utilisation responsable

Télécharge ou enregistre uniquement les contenus que tu as le droit de conserver. Les conditions d’utilisation des plateformes et les lois applicables restent à respecter.

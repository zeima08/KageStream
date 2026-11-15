# Journal des modifications de KageStream

Toutes les évolutions importantes de KageStream sont répertoriées dans ce fichier.

Le format s’inspire de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Les versions historiques 0.1 à 0.5 ne possédaient pas de date connue ; elles sont conservées sans en inventer.

## [Non publié]

### Ajouté

- Choix facultatif du navigateur dans **Outils → Dépendances → Session YouTube** pour transmettre ses cookies à yt-dlp lors de l’analyse et du téléchargement des vidéos, lives, playlists et pistes YouTube Music.
- **Forçage automatique des cookies YouTube** : quand yt-dlp est bloqué par « Sign in to confirm you're not a bot », KageStream détecte le blocage dans sa sortie, cherche un navigateur dont le profil existe sur la machine (Firefox, Chrome, Edge, Chromium, Brave, Vivaldi, Opera) et relance automatiquement l’analyse ou le téléchargement avec ses cookies — même si aucune session n’a été sélectionnée dans Outils. Le navigateur retenu devient la session active (visible dans **Session YouTube**). Si le navigateur choisi manuellement ne peut pas être lu (profil verrouillé, trousseau de clés indisponible), la relance essaie un autre navigateur détecté.
- Anti-collision des fichiers de capture : deux captures démarrées avec le même nom ne s’écrasent plus — la seconde devient automatiquement `nom-2.ts`, puis `nom-3.ts`, etc., y compris pour les captures programmées.
- **Routage automatique des replays** : les URL de plateformes de replay publiques gérées par yt-dlp sont reconnues même quand elles sont collées sur la page **Capturer** — KageStream bascule alors vers la page YouTube, qui analyse et télécharge avec yt-dlp. La liste des domaines reconnus reste volontairement non documentée publiquement.
- **Intégration continue réparée et étendue** : le workflow Windows vérifiait encore `dist/GUIStream.exe` (ancien nom du projet) alors que le build produit `KageStream.exe` — l’étape de vérification échouait donc à chaque exécution. Il utilise désormais l’environnement MSYS2 **MINGW64** documenté dans le README (au lieu d’UCRT64), ne lance plus la GUI à la fin du build sur les runners (variable `CI`), et se déclenche à chaque push sur `main` et sur chaque pull request. Nouveau workflow **Tests Linux** : compilation de tous les modules, import de l’interface GTK 3 sans affichage et exécution des tests unitaires à chaque push et pull request. `.gitignore` complété pour `.venv-windows/` créé par le build Windows.

- **Captures multiples en parallèle** : la page **Capturer** (Streamlink/IPTV/FFmpeg direct) n’est plus limitée à un seul enregistrement à la fois. Chaque clic sur **Enregistrer** ou **Programmer** ajoute une nouvelle capture dans son propre thread, sans arrêter les autres. Nouvel onglet **Captures** listant toutes les captures en cours, programmées et terminées, avec statut, santé, durée/taille en direct et actions par ligne (Stop, Vérifier le TS / Remuxer, Ouvrir le dossier, Couper). Plusieurs programmations horaires peuvent aussi coexister.
- **Découpe rapide d’un enregistrement terminé** : bouton « Couper cette vidéo… » sur une capture terminée, avec bornes début/fin (durée totale affichée via FFprobe) et copie de flux sans réencodage vers un nouveau fichier `_coupe`, sans jamais toucher au fichier original.
- La page YouTube/Dailymotion reste inchangée (un seul téléchargement à la fois).
- **Script `build-windows.bat`** remplaçant l’ancien script obsolète (qui référençait encore `guistream.py` et l’ancienne interface à onglets) : construit `KageStream.exe` via PyInstaller depuis un environnement MSYS2 MinGW64 (seule source viable de PyGObject/GTK3 sous Windows, aucun paquet officiel n’existant sur PyPI), embarque Streamlink à côté de l’exécutable, puis le lance directement. Non vérifié sur une vraie machine Windows faute d’en avoir une disponible — voir ROADMAP.

### Modifié

- La finalisation d’une capture (vérification du TS, remux, conversion) passe désormais par une file d’attente séquentielle interne : un seul remux/conversion actif à la fois, même si plusieurs captures se terminent en même temps, pour éviter de saturer le CPU. L’enregistrement lui-même reste pleinement parallèle.
- Les décisions « Vérifier le TS / Remuxer directement », « Continuer le remux / Conserver le TS » et le repli MKV, auparavant des boîtes de dialogue bloquantes, sont maintenant des boutons non bloquants sur la ligne de chaque capture dans l’onglet **Captures** — une capture en attente de décision ne gèle plus le suivi des autres captures en cours.
- La logique de capture (construction des commandes Streamlink/FFmpeg, reconnexion automatique, remux, conversion, analyse de santé du TS) est déplacée de `kagestream/app.py` vers le nouveau paquet `kagestream/capture/` (`job.py`, `manager.py`), sur le même principe que le gestionnaire de téléchargements musicaux.
- **Pages Captures et Téléchargements plus fluides** : les rangées ne sont plus détruites et recréées à chaque notification (une par seconde pendant une capture, une par ligne de progression yt-dlp). Une rangée est mise à jour en place — textes, barre de progression — et n’est reconstruite que lorsque son état change réellement. Le focus clavier et le survol ne sont plus perdus en cours de manipulation, et le coût n’augmente plus avec le nombre de tâches terminées de la session.
- La barre de progression d’un téléchargement musical affiche désormais l’avancement de la piste en cours : le pourcentage était calculé par le gestionnaire mais jamais affiché, si bien que la barre restait à zéro pendant toute la durée d’une longue piste.
- Le journal technique est borné à 5 000 lignes : au-delà, les plus anciennes sont supprimées. Un téléchargement de plusieurs heures en mode `--newline` ne ralentit plus l’interface au fil de la session.
- Le minuteur de rafraîchissement des captures s’éteint quand plus aucune capture n’est active, au lieu de réveiller la boucle GTK chaque seconde pendant toute la session.
- Les deux pages de suivi partagent désormais le même composant de liste (`kagestream/ui/job_rows.py`), au lieu de dupliquer la construction et le rafraîchissement des sections.
- **Les managers de capture et de téléchargement ne dépendent plus de la fenêtre GTK.** Ils reçoivent un contexte d’outils (`SourceTools`, `DownloadTools`) et un callback de journal ; les chemins sont relus à chaque usage après une installation de dépendance. La détection des sources (Streamlink, FFprobe, FFmpeg direct) vit désormais dans `media/sources.py`, partagée par l’interface et les managers au lieu d’être dupliquée. Conséquence directe : ces composants sont désormais testables sans interface.
- **Build assaini** : `appimagetool` n’est plus téléchargé puis exécuté sans contrôle — le script utilise celui de la distribution s’il existe, sinon exige une empreinte SHA-256 (`KAGESTREAM_APPIMAGETOOL_SHA256`) et refuse de continuer. L’`AppRun` obsolète qui référençait encore `GUIStream` et un `package-lock.json` vide sans `package.json` sont supprimés du dépôt. Les dépendances sont épinglées (`streamlink>=7,<9`) et PyInstaller est déplacé dans `requirements-build.txt`, séparé des dépendances d’exécution.
- **Refonte de l’interface** : le titre, le statut et les deux horloges passent dans une vraie barre de titre (`Gtk.HeaderBar`), ce qui rend deux lignes d’en-tête permanentes à la zone de contenu. La barre latérale reçoit des icônes, des libellés ellipsés, une section **Outils** lisible et des pastilles de compteurs (captures actives, téléchargements en cours, alerte de santé). La barre d’action globale hors du `Gtk.Stack` disparaît : chaque page porte ses propres actions — durée, taille et santé ne s’affichent plus sur la page YouTube que pendant un téléchargement.
- **Style unifié** : une feuille CSS unique (`ui/theme.py`) fixe l’échelle d’espacement, les titres de page et les cartes de section ; les couleurs sont dérivées du thème GTK, donc le mode sombre est suivi automatiquement. Les trois `Gtk.Frame` hétérogènes et les grilles nues des pages YouTube et Musique deviennent des cartes identiques (`ui/widgets.py`). Les pages Outils défilent et le double défilement de la page Musique est supprimé.
- **Accessibilité et clavier** : mnémoniques sur tous les champs de formulaire, validation par Entrée dans les champs d’URL et d’horaires, infobulles sur les actions, raccourcis `Ctrl+1` à `Ctrl+6` pour les six sections, et état vide explicite dans chaque section des pages Captures et Téléchargements.

### Corrigé

- **La vérification de fermeture du fichier TS après un Stop est désormais réelle** : elle se contentait auparavant de tester l’existence du fichier, ce qui renvoyait toujours « fermé » et affichait un message trompeur. Sous Linux, les descripteurs de `/proc` sont inspectés pour savoir si un processus garde encore le fichier ouvert ; ailleurs, la stabilité de la taille et de la date de modification fait foi. Le message affiché distingue maintenant une fermeture confirmée d’un fichier encore détenu.
- **Plus de fausses alertes « flux instable »** : les motifs de surveillance incluaient les mots isolés `segment`, `retry`, `error`, `pts` et `dts`, présents dans la sortie normale d’un flux sain (« Segment 12/40 », « Retrying in 15 seconds », « Non-monotonous DTS »). Ils sont remplacés par des motifs réellement anormaux (`HTTP Error 4xx/5xx`, `connection reset`, `error while decoding`, `packet corrupt`…). Le compteur d’alertes repart de zéro après une reconnexion réussie, au lieu de condamner la nouvelle session avec les alertes de la précédente.
- **Le fichier `kagestream/app.py` est découpé** : il passe de 2 896 à 388 lignes. Les pages (`ui/page_capture.py`, `ui/page_youtube.py`, `ui/page_tools.py`, `ui/page_playlists.py`) et la logique (`ui/logic_links.py`, `ui/logic_youtube.py`, `ui/logic_capture.py`, `ui/logic_dependencies.py`) vivent dans des mixins dédiés ; la fenêtre ne garde que l’assemblage, les états partagés et les horloges. La construction de la commande yt-dlp devient une fonction pure (`media/ytdlp_command.py`), testable sans GTK.
- **Workflows GitHub Actions réparés** : côté Windows, un seul nom de paquet était faux et faisait échouer `pacman` — PyInstaller s’installe sous le nom `mingw-w64-x86_64-pyinstaller`, pas `python-pyinstaller`. Le script de build a en plus un chemin CI dédié : ni `pacman`, ni venv, ni `pip`, puisque MSYS2 fournit déjà tout ; Streamlink est cherché dans le venv puis dans le `PATH`. Le `.bat` est repassé en fins de ligne CRLF (via `.gitattributes`) — `cmd.exe` interprète mal les labels et `goto` d’un batch en LF — et un prérequis manquant renvoie désormais un code d’échec au lieu d’un succès silencieux. Enfin, l’appel `cmd.exe /D /C` depuis le shell MSYS2 est protégé de la conversion automatique des arguments en chemins (`MSYS2_ARG_CONV_EXCL`), qui empêchait `cmd` de recevoir ses options et faisait « réussir » l’étape sans rien construire. Côté Linux, les tests construisent une vraie fenêtre GTK : ils s’exécutent maintenant sous `xvfb-run`. Les trois workflows (Windows, Linux, macOS) sont verts sur le commit `336c5a6`. Ajout d’un workflow **macOS** qui vérifie la portabilité et les tests sans interface (macOS n’est pas une plateforme empaquetée). Les tests d’interface s’ignorent proprement quand aucun serveur d’affichage n’est disponible, au lieu de faire tomber le processus.

### Corrigé

- **Boutons sans effet (cause racine de l’application inutilisable)** : le helper de bouton appelait chaque action sans argument, alors que les gestionnaires de la fenêtre attendent le bouton (`test_link(self, button)`, `show_diagnostic(self, button)`, `start_recording(self, button)`…). Chaque clic levait donc un `TypeError` invisible — boutons inertes, dialogues des listes locales et des dépendances impossibles à ouvrir. Le helper détecte désormais la signature de l’action et transmet le bouton quand elle l’attend, ou rien sinon ; les deux formes coexistent dans les pages.
- **Infobulles retirées des champs de formulaire** : un bug GTK 3 connu (gtk#1785) empêche un `GtkComboBox` d’ouvrir son menu lorsqu’une infobulle est affichée au même instant. Seuls les boutons en conservent, l’aide restant dans les textes sous les formulaires.
- **Exécutable reconstruit sans UPX** : la compression UPX du `.spec` est désactivée — elle peut altérer le chargement des bibliothèques GTK et n’apporte rien ici. `build-linux.sh` produit désormais l’exécutable même si `appimagetool` n’est pas vérifiable (il s’arrête après la partie exécutable, avec un message clair, au lieu d’échouer).

- **La file de finalisation ne peut plus se bloquer pour toujours** : l’analyse du TS, le remux, la conversion et la découpe lancent désormais FFmpeg avec un délai garde-fou dimensionné sur la taille du fichier (par exemple 3 min + 1 min/Gio pour un remux, bien plus large pour un réencodage). Au-delà, le groupe de processus est arrêté de force et la capture passe en erreur en conservant le TS — au lieu de rester indéfiniment « En attente de remux » et de bloquer les finalisations suivantes.
- **Fermer KageStream arrête vraiment tout** : enregistrements, téléchargements musicaux et finalisations tournent dans des groupes de processus dédiés ; ils survivaient auparavant à la fermeture de la fenêtre et continuaient d’écrire leurs fichiers en arrière-plan. Le `destroy` de la fenêtre déclenche maintenant un arrêt groupé (SIGINT, puis SIGTERM, puis SIGKILL, en parallèle sur tous les processus).
- Les FFmpeg de finalisation sont lancés dans leur propre groupe de session (comme l’enregistrement), ce qui rend le bouton Stop efficace pendant un remux ou une conversion — sous Linux comme sous Windows.
- **Analyse musicale : le bouton Analyser pouvait rester désactivé à vie**. Une exception imprévue pendant l’analyse (par exemple un numéro de piste inattendu renvoyé par yt-dlp) tuait le thread en silence. L’erreur est maintenant affichée dans la barre d’état et le bouton est toujours réactivé.
- **Annulation d’une programmation ignorée dans la dernière seconde** : si l’annulation était demandée pendant l’ultime attente avant l’heure de départ, l’enregistrement démarrait quand même. Le drapeau d’annulation est désormais revérifié juste avant le lancement.
- **Annuler un téléchargement musical figeait l’interface** jusqu’à 11 secondes le temps d’arrêter yt-dlp (SIGINT, puis SIGTERM, puis SIGKILL). L’arrêt s’exécute maintenant dans un thread d’arrière-plan, comme pour les captures.
- La fenêtre de découpe d’un enregistrement est désormais modale (plus de fenêtres empilées par double-clic) et la durée totale est mesurée par FFprobe en arrière-plan : plus de gel de l’interface à l’ouverture sur les gros fichiers.
- Le refus YouTube « Sign in to confirm you’re not a bot » affiche désormais une demande de vérification de session avec les étapes à suivre, plutôt que « Lien non reconnu ». L’erreur détaillée reste dans le journal.

- Certaines sources IPTV/HLS/DASH refusaient la connexion (403) à cause du user-agent par défaut de FFmpeg (`Lavf/x.y`) ou de Streamlink. Le test de lien et l’enregistrement (capture initiale et reprises après reconnexion) envoient désormais un user-agent `curl/8.22.0` et un en-tête `Accept: */*`, aussi bien pour le flux direct FFmpeg que pour Streamlink (Twitch excepté, dont le user-agent par défaut reste nécessaire à la récupération des jetons d’accès).
- **Stop qui n’arrêtait pas vraiment l’enregistrement** : pour un flux DASH avec vidéo et audio séparés, Streamlink démarre en interne un muxeur FFmpeg (deux tuyaux nommés fusionnés en un seul fichier). Le Stop n’envoyait le signal qu’au process Streamlink de tête ; son muxeur FFmpeg, non signalé, continuait de tourner et d’écrire le fichier indéfiniment après un Stop confirmé dans les logs (`ps aux` le montrait toujours actif). Les captures, les téléchargements YouTube/Dailymotion et les téléchargements musicaux démarrent désormais leur process dans un groupe dédié (`start_new_session`), et l’arrêt (SIGINT/SIGTERM/SIGKILL) cible tout le groupe plutôt qu’un seul PID.

## [0.7.0] - 2026-08-12

### Ajouté

#### Téléchargement de musique

- Nouvelle page **Musique** permettant de coller un lien **YouTube Music**, **SoundCloud** ou **Bandcamp** : le fournisseur est détecté automatiquement à partir du nom d’hôte, puis l’analyse (morceau, album ou playlist) est déléguée à yt-dlp, sans dépendre d’une API officielle.
- Après analyse, affichage du titre, de l’artiste, de l’année, de la pochette et de la liste complète des pistes, avec sélection individuelle et boutons **Tout cocher** / **Tout décocher**.
- Trois profils de téléchargement prêts à l’emploi — **Compatible** (MP3 192 kbps), **Qualité maximale** et **Archivage** (FLAC) — ainsi qu’un profil **Personnalisé** avec choix du format parmi Original, MP3, AAC, M4A, Opus, Vorbis et FLAC.
- Organisation automatique des fichiers téléchargés sous `Artiste/Album`, avec nettoyage des noms de fichiers et protection contre les chemins traversants (path traversal).
- Nouvelle page **Téléchargements** listant les tâches musicales en cours, en attente et terminées, avec barre de progression par piste, annulation et ouverture directe du dossier final.

#### Interface

- Nouvelle barre latérale de navigation (**Capturer**, **Musique**, **YouTube**, **Téléchargements**, **Outils → Dépendances/Diagnostic/Logs**) qui remplace l’ancienne interface à onglets, pour une organisation plus lisible des fonctions déjà présentes et des nouvelles.

### Modifié

- `kagestream.py` devient un lanceur minimal qui importe le nouveau package `kagestream/` ; la gestion des dépendances, l’analyse yt-dlp, l’arrêt robuste des processus, la lecture des listes M3U/XSPF et les utilitaires de chemins/noms de fichiers sont désormais des modules partagés entre la capture existante et le nouveau téléchargement musical, au lieu de vivre uniquement dans l’ancien script unique.
- `build-linux.sh` vérifie désormais la présence du package `kagestream/` et de la nouvelle interface à barre latérale avant de construire l’AppImage, à la place de l’ancienne vérification liée aux onglets.

## [0.6.1] - 2026-07-31

### Ajouté

- Programmation d’un enregistrement directement depuis la fenêtre **Listes locales** : en sélectionnant une chaîne, un nouveau bouton **Programmer** applique l’heure de début/fin saisie sur place, en réutilisant le même mécanisme que le bouton **Programmer** de l’onglet Flux & IPTV. Le bouton **Enregistrer la sélection** est renommé **Enregistrer maintenant** pour plus de clarté à côté de ce nouveau choix.

### Modifié

- Arrêt nettement plus réactif : la vérification de fermeture du fichier TS ajoutait un délai fixe d’au moins 1,2 seconde après chaque arrêt alors que le processus était déjà confirmé terminé ; elle ne fait plus qu’une vérification immédiate. Les paliers d’escalade SIGINT/SIGTERM/SIGKILL sont aussi raccourcis (3 s + 3 s + 5 s au lieu de 6 s + 6 s + 10 s), sans rien perdre de la garantie d’arrêt forcé.
- Après un Stop destiné à un remux MKV/MP4, l’analyse complète du fichier ne se lance plus automatiquement avant même l’affichage du choix « Vérifier le TS / Remuxer directement » : elle ne tourne désormais que si l’utilisateur choisit explicitement de vérifier. Le statut affiche aussi immédiatement « finalisation en cours » dès l’arrêt du processus, pour éviter l’impression que l’application ne répond plus.

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

# Feuille de route de KageStream

Cette feuille de route présente les évolutions envisagées pour transformer KageStream en application stable, distribuable et simple à maintenir.

Elle décrit une direction de travail, pas une promesse de date. Les priorités peuvent évoluer selon les retours, les changements de YouTube, yt-dlp, Streamlink et FFmpeg, ainsi que les contraintes de distribution AppImage.

## Base déjà disponible

KageStream possède actuellement les fondations suivantes :

- interface GTK 3 ;
- enregistrement Streamlink et FFmpeg direct ;
- prise en charge des sources MPEG-TS et HLS ;
- téléchargement des vidéos et lives YouTube avec yt-dlp ;
- meilleure qualité vidéo et audio, sous-titres, tags, métadonnées et miniatures ;
- lecture des listes locales M3U, M3U8 et XSPF ;
- sorties TS, MKV et MP4 ;
- diagnostic et analyse de la santé des enregistrements ;
- installation directe et vérifiée de yt-dlp, Deno, Streamlink, FFmpeg et FFprobe ;
- arrêt robuste des enregistrements (SIGINT puis SIGTERM puis SIGKILL) avec vérification de la fermeture du fichier TS ;
- reconnexion automatique des flux Streamlink et FFmpeg direct après une coupure momentanée (jusqu’à 2 minutes avant abandon) ;
- programmation d’un enregistrement avec heure de début et de fin pour Streamlink, l’IPTV et FFmpeg direct, y compris directement depuis la fenêtre des listes locales lors du choix d’une chaîne ;
- vérification optionnelle du fichier TS avant remux, avec repli automatique de mapping en cas d’échec ;
- horloge locale et horloge de Tokyo affichées en continu dans la fenêtre principale ;
- téléchargement de musique depuis YouTube Music, SoundCloud et Bandcamp (détection du fournisseur, sélection des pistes, profils de format, file de téléchargement dédiée) ;
- interface réorganisée autour d’une barre latérale (Capturer, Musique, YouTube, Téléchargements, Outils) à la place de l’ancienne interface à onglets ;
- premier découpage du script principal en package `kagestream/` : dépendances, analyse yt-dlp, arrêt robuste des processus, listes M3U/XSPF et utilitaires de chemins/noms de fichiers sont désormais des modules partagés.

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

- [x] **Priorité haute** — Découper le script principal en modules : interface, détection des sources, YouTube, enregistrement, listes et dépendances. *(Fait le 2026-11-15 : `app.py` ramené de 2 896 à 388 lignes, pages et logique réparties en mixins sous `kagestream/ui/`, commande yt-dlp extraite en fonction pure. Voir aussi le point 8 de l’ordre de travail pour ce qui reste.)*
- [ ] **Priorité haute** — Centraliser le lancement et l’arrêt des sous-processus. *(Arrêt fait le 2026-08-12 : `kagestream/media/process.py` fournit l’escalade SIGINT/SIGTERM/SIGKILL désormais partagée par la capture et le téléchargement musical. Le lancement des processus — Streamlink, FFmpeg, yt-dlp — reste construit séparément à chaque emplacement.)*
- [ ] **Priorité haute** — Ajouter une gestion structurée des erreurs avec messages courts dans l’interface et détails dans les journaux.
- [ ] **Priorité moyenne** — Introduire une constante de version utilisée par l’application, le diagnostic et les paquets.
- [ ] **Priorité moyenne** — Définir des dossiers XDG séparés pour les données, la configuration, le cache et les journaux.

### Configuration

- [ ] **Priorité haute** — Mémoriser le dossier de sortie, le conteneur, la résolution et les options YouTube.
- [ ] **Priorité moyenne** — Ajouter un bouton de restauration des réglages par défaut.
- [ ] **Priorité moyenne** — Permettre de choisir manuellement le chemin d’un outil externe.
- [ ] **Priorité moyenne** — Enregistrer la taille et la position de la fenêtre.

### Fiabilité

- [x] **Priorité haute** — Tester les URL expirées, les coupures réseau et les flux sans audio ou sans vidéo. *(Partiellement : 2026-11-15 — tests de détection des incidents de flux, de fermeture réelle du fichier TS et du watchdog de finalisation sur un faux FFmpeg bloqué. Les URL expirées et les flux sans audio restent à couvrir.)*
- [ ] **Priorité haute** — Vérifier les collisions de noms avant chaque téléchargement.
- [ ] **Priorité haute** — Améliorer la reprise et l’identification des fichiers `.part`.
- [ ] **Priorité moyenne** — Ajouter une limite configurable au nombre de tentatives de reconnexion. *(Base ajoutée le 2026-07-30 pour Streamlink/FFmpeg direct : fenêtre fixe de 2 minutes, tentative toutes les 15 secondes. Reste à rendre ces valeurs configurables.)*
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

## Musique — évolutions envisagées après le socle initial

Objectif : consolider le téléchargement musical (YouTube Music, SoundCloud, Bandcamp) ajouté le 2026-08-12, voir CHANGELOG 0.7.0.

- [ ] **Priorité moyenne** — Permettre de personnaliser l’organisation des fichiers téléchargés, actuellement fixée à `Artiste/Album`.
- [ ] **Priorité moyenne** — Traiter plusieurs téléchargements musicaux en parallèle plutôt qu’un seul à la fois.
- [ ] **Priorité moyenne** — Faire persister la file de téléchargement musical entre deux lancements de KageStream, comme prévu pour la file de capture en version 0.7.
- [ ] **Priorité basse** — Ajouter une vue playlist filtrable avant l’ajout à la file, comme envisagé pour les playlists YouTube classiques.
- [ ] **Priorité basse** — Utiliser les API officielles YouTube Music ou SoundCloud pour enrichir les métadonnées lorsque l’analyse yt-dlp seule ne suffit pas.

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

- [x] **Priorité haute** — Programmer une heure de démarrage. *(Fait le 2026-07-30, voir CHANGELOG 0.6.0 — Streamlink, IPTV et FFmpeg direct uniquement, pas YouTube.)*
- [x] **Priorité haute** — Définir une durée maximale d’enregistrement. *(Fait le 2026-07-30 sous forme d’une heure de fin plutôt que d’une durée en minutes ; l’arrêt réutilise la procédure robuste du bouton Stop.)*
- [ ] **Priorité moyenne** — Répéter une programmation certains jours.
- [ ] **Priorité moyenne** — Prévenir lorsque la source n’est pas disponible à l’heure prévue.
- [x] **Priorité basse** — Autoriser plusieurs enregistrements simultanés avec une limite configurable. *(Fait le 2026-09-16 pour Streamlink/IPTV/FFmpeg direct : chaque capture tourne dans son propre thread dès son lancement, suivie dans le nouvel onglet Captures. Pas de limite configurable pour l'instant — seule la finalisation (vérification/remux/conversion) est volontairement limitée à une capture à la fois pour ne pas saturer le CPU. Pas encore fait pour YouTube/Dailymotion, qui reste mono-tâche.)*
- [x] **Priorité basse** — Découpe manuelle (bornes début/fin) d'une capture terminée pour n'obtenir qu'un seul fichier avant partage. *(Fait le 2026-09-16 — copie de flux sans réencodage, fichier séparé du TS/remux d'origine. Volontairement limité à une seule plage : KageStream reste un outil de capture, pas un éditeur vidéo complet.)*

### Critères de validation

- La file survit à un redémarrage de KageStream.
- Une tâche échouée ne bloque pas les suivantes.
- La sélection multiple fonctionne avec plusieurs fichiers M3U et XSPF.
- Les programmations utilisent le fuseau horaire local et affichent leur prochaine exécution.

## Version 0.8 — YouTube avancé

Objectif : proposer un niveau de choix proche d’un gestionnaire de téléchargement spécialisé tout en conservant le mode automatique.

### Formats

- [ ] **Priorité haute** — Afficher les formats vidéo avec résolution, codec, fréquence d’images, HDR, taille estimée et débit.
- [ ] **Priorité haute** — Afficher séparément les pistes audio et leur langue.
- [ ] **Priorité haute** — Permettre le téléchargement d’une vidéo avec plusieurs pistes audio (multi-langues) en laissant l’utilisateur sélectionner les pistes à inclure.
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
- [x] **Priorité haute** — Forcer les cookies quand YouTube bloque (« Sign in to confirm you’re not a bot »). *(Fait le 2026-11-15 : le blocage est détecté dans la sortie yt-dlp et l’analyse ou le téléchargement est relancé automatiquement avec les cookies du premier navigateur dont le profil est détecté, même sans sélection dans Outils ; le navigateur retenu devient la session active.)*
- [ ] **Priorité moyenne** — Gérer les URL de chaînes et les collections prises en charge par yt-dlp.

### Sources

- [x] **Priorité moyenne** — Étendre la détection automatique aux sites de replay gérés par yt-dlp (arte, france.tv, RTS, …). *(Fait le 2026-11-15 : routage automatique vers yt-dlp — y compris pour un lien collé sur la page Capturer, qui bascule alors vers la page YouTube. Les sites ne sont pas cités dans le README.)*
- [ ] **Priorité moyenne** — Importer facultativement les cookies depuis un navigateur via yt-dlp, sans les copier dans les journaux.
- [ ] **Priorité moyenne** — Reprendre un téléchargement interrompu lorsque yt-dlp le permet.

### Lives

- [ ] **Priorité haute** — Afficher clairement les états à venir, en direct et terminé.
- [ ] **Priorité haute** — Améliorer la reconnexion après une coupure momentanée. *(Fait le 2026-07-30 pour Streamlink et FFmpeg direct, voir CHANGELOG 0.6.0. Reste à faire spécifiquement pour les lives YouTube/yt-dlp.)*
- [ ] **Priorité moyenne** — Permettre l’arrêt automatique à une heure ou après une durée donnée. *(Fait le 2026-07-30 pour Streamlink, l’IPTV et FFmpeg direct. Reste à faire pour YouTube.)*
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

### Windows

- [x] **Priorité haute** — Script `build-windows.bat` construisant `KageStream.exe` via PyInstaller (environnement MSYS2 MinGW64, seule source viable de PyGObject/GTK3 sous Windows) puis le lançant directement. *(Fait le 2026-09-17, non vérifié faute de machine Windows disponible — à tester réellement avant de le considérer fiable.)*
- [ ] **Priorité haute** — Vérifier réellement le build sur une machine Windows et corriger ce qui plante (typelibs GObject-Introspection, DLL GTK, thème d’icônes). *(Depuis le 2026-11-15, la CI construit l’exécutable sur `windows-latest` à chaque push — les premiers échecs, s’il y en a, fourniront les diagnostics.)*
- [ ] **Priorité moyenne** — Publier une AppImage-like (archive ou installateur) qui ne dépende pas d’un MSYS2 déjà installé sur la machine cible.

### Publication

- [ ] **Priorité haute** — Automatiser les tests et la construction à chaque version.
- [ ] **Priorité haute** — Générer les notes de version depuis le changelog validé.
- [ ] **Priorité haute** — Afficher la version de KageStream dans l’interface et le diagnostic.
- [ ] **Priorité moyenne** — Vérifier les nouvelles versions de KageStream depuis une source configurable.
- [ ] **Priorité moyenne** — Télécharger une nouvelle AppImage sans remplacer automatiquement la version en cours.
- [ ] **Priorité basse** — Ajouter une signature de publication en plus du SHA-256.

### Critères de validation

- Une version peut être reconstruite à partir de son étiquette Git.
- Les AppImages démarrent sur plusieurs distributions glibc prises en charge.
- Les sommes publiées correspondent exactement aux fichiers distribués.
- La mise à jour de KageStream exige toujours une confirmation explicite.

## Refonte de l’interface

Objectif : rendre l’interface agréable à utiliser, pas seulement fonctionnelle. À mener après le découpage du monolithe `app.py` — une refonte visuelle sur 2 700 lignes construites à la chaîne serait jetée à la première refactorisation.

- [x] **Priorité haute** — Repenser la hiérarchie visuelle : espacement homogène, regroupement des actions par intention, moins de cadres imbriqués. *(Fait le 2026-11-15 — échelle d’espacement unique, cartes de section, actions par page.)*
- [x] **Priorité haute** — Rafraîchissement visuel général (mode sombre suivi du système, icônes cohérentes, typographie). *(Fait le 2026-11-15 — couleurs dérivées du thème GTK, icônes symboliques avec repli si le thème n’en fournit pas, titres de page et de section hiérarchisés.)*
- [x] **Priorité moyenne** — Uniformiser les pages Captures / Téléchargements sur un même composant de liste avec rafraîchissement différentiel (plus de reconstruction complète chaque seconde). *(Fait le 2026-11-15 — `ui/job_rows.py`.)*
- [x] **Priorité moyenne** — Revoir l’ergonomie clavier : mnémoniques, labels associés, Entrée qui valide dans les champs URL. *(Fait le 2026-11-15, plus `Ctrl+1..6` pour les sections.)*
- [ ] **Priorité basse** — Étudier une maquette GTK 4 (libadwaita) comme cible d’arrivée plutôt qu’une retouche GTK 3 profonde.

## Version 1.0 — Version stable

Objectif : fournir une base documentée et suffisamment robuste pour une utilisation quotidienne.

- [ ] **Priorité haute** — Corriger tous les problèmes bloquants identifiés pendant les versions 0.6 à 0.9.
- [ ] **Priorité haute** — Geler et documenter le format du fichier de configuration.
- [ ] **Priorité haute** — Tester les migrations de configuration entre versions.
- [ ] **Priorité haute** — Finaliser le README, le changelog, la feuille de route et le guide de contribution.
- [x] **Priorité haute** — Vérifier l’accessibilité au clavier et les libellés GTK. *(Fait le 2026-11-15 pour les formulaires : mnémoniques et association libellé/champ partout, validation par Entrée, raccourcis de section `Ctrl+1..6`. Reste à vérifier au lecteur d’écran et sur les dialogues secondaires.)*
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

KageStream n’a pas vocation à :

- contourner les DRM, abonnements, contrôles d’accès ou restrictions territoriales ;
- télécharger un contenu sans autorisation lorsque la plateforme ou les droits applicables l’interdisent ;
- devenir un éditeur vidéo complet ;
- réencoder systématiquement les captures lorsque le remux suffit ;
- installer ou remplacer GTK et les bibliothèques critiques du système avec des privilèges administrateur.

## Prochain ordre de travail conseillé

Ordre consolidé issu de l’audit du code du 2026-11-15 et des demandes associées. Les lots 1 à 7 sont du corrective maintenance ; les trois suivants sont les évolutions demandées.

1. **Correctifs rapides (audit)** : anti-collision des fichiers TS (`capture/manager.py:101`), `try/finally` dans `analyze_worker` (`music_page.py:189`), re-vérification de `schedule_cancelled` après la sortie de boucle (`capture/manager.py:132`), annulation d’un téléchargement en thread au lieu du thread GTK (`download/manager.py:61`), dialog de découpe modal (`captures_page.py:69`). **Fait le 2026-11-15** (avec, en plus, la mesure de durée FFprobe sortie du thread GTK dans le dialog de découpe).
2. **Forcer les cookies YouTube** quand le blocage « not a bot » est détecté, sans sélection manuelle préalable. **Fait le 2026-11-15** (détection du blocage, navigateurs détectés par profil, relance automatique de l’analyse, des téléchargements YouTube et des téléchargements musicaux, session mémorisée).
3. **Étendre la détection yt-dlp** aux replays arte / france.tv / RTS — silencieusement, sans mention dans le README. **Fait le 2026-11-15** (routage automatique vers la page YouTube, familles de domaines Arte / france.tv / SRG SSR).
4. **Réparer la CI** : `GUIStream.exe` → `KageStream.exe` dans le workflow, ne pas lancer la GUI à la fin du build, ajouter un trigger push et un workflow Linux qui exécute les tests. **Fait le 2026-11-15** (workflow Windows corrigé et passé sur MINGW64 comme le README, lancement de la GUI ignoré en CI via la variable `CI`, déclenchement sur push/PR ; nouveau workflow Linux : compileall, import GTK headless, tests unitaires).
5. **Fiabiliser la finalisation** : timeouts sur les sous-processus de remux/vérification/conversion, handler d’arrêt à la fermeture de l’application pour tuer les sous-processus restants. **Fait le 2026-11-15** (délais garde-fou dimensionnés sur la taille du fichier, groupes de session pour les FFmpeg de finalisation, arrêt groupé parallèle à la fermeture de la fenêtre).
6. **Performance UI** : rafraîchissement différentiel des pages Captures / Téléchargements, purge des tâches terminées, limite de taille du journal technique. **Fait le 2026-11-15** (registre de rangées partagé `ui/job_rows.py`, boutons Retirer / Vider, journal borné à 5 000 lignes, minuteur de capture auto-extinguible, progression par piste affichée).
7. **Assainir le build** : appimagetool épinglé avec SHA-256, suppression de l’`AppRun` racine obsolète, `.gitignore` complété (`.venv-windows/`), `requirements.txt` épinglés, suppression de `package-lock.json`. **Fait le 2026-11-15** (appimagetool système ou empreinte obligatoire, fichiers morts supprimés, `requirements-build.txt` séparé, dépendances bornées).
8. **Découper `app.py`** (2 753 lignes, trois systèmes de jobs) : faire converger `youtube_worker` vers les managers, injecter un contexte d’outils à la place de la fenêtre GTK dans les managers. **Partiellement fait le 2026-11-15** : `app.py` passe à 388 lignes, la logique est répartie en mixins (`ui/page_*.py`, `ui/logic_*.py`) et la commande yt-dlp devient une fonction pure testable (`media/ytdlp_command.py`). Restent la convergence de `youtube_worker` vers les managers et l’injection d’un contexte d’outils à la place de `self.window` dans `CaptureManager`.
9. **Sélecteur de formats YouTube avancé** avec pistes audio multiples sélectionnables (s’appuie sur le point 8).
10. **Refonte de l’interface** (voir la section dédiée) — en dernier, sur la base refactorisée. **Fait le 2026-11-15** (barre de titre avec statut et horloges, barre latérale à icônes et pastilles, barres d’action par page, cartes et échelle d’espacement uniques, thème clair/sombre suivi, mnémoniques, Entrée, `Ctrl+1..6`).

Les anciens points restants restent valables par ailleurs : version interne et dossiers XDG, extraction de la génération des commandes, tests M3U/XSPF et des commandes (installateurs déjà extraits le 2026-08-12), mémorisation des réglages, file d’attente, sélection multiple dans les listes locales, automatisation des AppImages.

"""Every user-facing string, in French and English.

One table rather than per-module constants: the point of translating is that a
missing string is *visible*, and a single catalogue makes an untranslated entry
obvious at a glance instead of hiding in whichever file happens to print it.

The language follows the League client language chosen in the settings, because
the two are almost never different in practice -- someone playing on an English
client reads English. It is deliberately not read from Windows: what matters is
the language of the chat being OCR'd, not the one the desktop is in. Until that
choice is made -- first launch, or a locale nobody recognises -- it is English:
the guide that asks the question has to be written in something, and English is
the language the most players will be able to answer it in.

``tr`` never raises. An unknown key comes back as the key itself, which shows up
in the interface as a plain slug instead of crashing the window that was about to
be drawn.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

FRENCH = "fr"
ENGLISH = "en"
LANGUAGES = (FRENCH, ENGLISH)

# Riot's locale codes, which are what the data downloader wants.
LOCALES = {FRENCH: "fr_FR", ENGLISH: "en_US"}

_language = ENGLISH


def language_for(locale: str) -> str:
    """Map a Riot locale ("fr_FR", "en_US") onto a language code.

    French only when the locale says so; everything else, including a locale
    the application never writes, comes back English. The fallback has to name
    one of the two, and English is the one someone who has not chosen yet is
    likeliest to read.
    """
    return FRENCH if str(locale).lower().startswith("fr") else ENGLISH


def locale_for(language: str) -> str:
    return LOCALES.get(language, LOCALES[ENGLISH])


def set_language(value: str) -> str:
    """Switch language. Accepts a language code or a Riot locale."""
    global _language
    _language = value if value in LANGUAGES else language_for(value)
    return _language


def current() -> str:
    return _language


def tr(key: str, **kwargs) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        log.warning("missing translation for %r", key)
        return key
    text = entry[1] if _language == ENGLISH else entry[0]
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            log.warning("bad format arguments for %r", key)
    return text


# (french, english)
STRINGS: dict[str, tuple[str, str]] = {
    # -- window titles ---------------------------------------------------
    "app.title": ("Flashwatch", "Flashwatch"),
    "app.tray_tooltip": ("Flashwatch",
                         "Flashwatch"),
    "app.already_running": (
        "Flashwatch est deja lance : cherchez son icone dans la zone de "
        "notification, en bas a droite (eventuellement sous la fleche). Deux "
        "copies se disputeraient l'overlay.",
        "Flashwatch is already running: look for its icon in the notification "
        "area at the bottom right (possibly under the arrow). Two copies would "
        "fight over the overlay."),

    # -- game state ------------------------------------------------------
    "game.in_game": ("En jeu ({width}x{height})", "In game ({width}x{height})"),
    "game.client_only": ("Client ouvert, pas en partie",
                         "Client open, not in a game"),
    "game.absent": ("League of Legends non detecte",
                    "League of Legends not detected"),

    # -- start-up / Riot data -------------------------------------------
    "boot.loading": ("Chargement des donnees Riot...", "Loading Riot data..."),
    "boot.error": ("Erreur de chargement : {error}", "Loading failed: {error}"),
    "boot.waiting": ("En attente de League of Legends...",
                     "Waiting for League of Legends..."),
    "assets.version": ("Recherche de la version du patch...",
                       "Looking up the patch version..."),
    "assets.patch": ("Patch {version} - chargement des donnees ({locale})",
                     "Patch {version} - loading data ({locale})"),
    "assets.spells": ("{count} sorts d'invocateur charges",
                      "{count} summoner spells loaded"),
    "assets.champions": ("{count} champions charges", "{count} champions loaded"),
    "assets.icons_cached": ("Icones deja en cache", "Icons already cached"),
    "assets.icons_downloading": ("Telechargement de {count} icones...",
                                 "Downloading {count} icons..."),
    "assets.icons_progress": ("Icones {done}/{total}", "Icons {done}/{total}"),
    "assets.offline": (
        "Impossible de contacter Data Dragon et aucun cache local n'existe. "
        "Verifiez votre connexion internet au premier lancement.",
        "Data Dragon is unreachable and there is no local cache. Check your "
        "internet connection for the first run."),

    # -- overlay ---------------------------------------------------------
    "overlay.enemy_spells": ("SORTS ENNEMIS", "ENEMY SPELLS"),
    "overlay.unlocked": ("deverrouille", "unlocked"),
    "overlay.unlocked_hint": ("Flashwatch - deverrouille, glissez pour deplacer",
                              "Flashwatch - unlocked, drag to move"),
    "overlay.waiting": ("En attente...", "Waiting..."),
    "overlay.nothing_yet": ("Aucun sort detecte pour le moment",
                            "No spell detected yet"),

    # -- tray menu -------------------------------------------------------
    "tray.overlay": ("Afficher l'overlay", "Show the overlay"),
    "tray.lock": ("Verrouiller (clics traversants)",
                  "Lock (click-through)"),
    "tray.test_mode": ("Mode test : placer la zone OCR",
                       "Test mode: place the OCR zone"),
    "tray.settings": ("Parametres...", "Settings..."),
    "tray.guide": ("Guide d'installation...", "Setup guide..."),
    # No longer "at the top": each display has its own default place, and the
    # rows belong down a side.
    "tray.recentre": ("Remettre l'affichage en place",
                      "Put the display back in place"),
    "tray.demo": ("Essayer sans partie", "Try it without a game"),
    "tray.redetect": ("Redetecter le chat", "Detect the chat again"),
    "tray.reset": ("Reinitialiser les timers", "Reset the timers"),
    "tray.quit": ("Quitter (fermer le programme)", "Quit (close the program)"),
    "notify.zone_saved": ("Zone OCR enregistree ({width}x{height}).",
                          "OCR zone saved ({width}x{height})."),
    "notify.bar_in_game_only": (
        "La barre s'affichera automatiquement des que vous serez en partie.",
        "The bar will appear by itself once you are in a game."),
    "notify.demo_ended": (
        "Une partie a demarre : le mode essai s'arrete et l'affichage repasse en "
        "clics traversants.",
        "A game has started: the trial stops and the display goes back to "
        "click-through."),
    "notify.demo_loading": (
        "Les donnees Riot finissent de se telecharger. Reessayez dans quelques "
        "secondes.",
        "Riot's data is still downloading. Try again in a few seconds."),
    "notify.hidden_to_tray": (
        "Flashwatch continue de tourner ici. Double-cliquez sur l'icone pour "
        "rouvrir les reglages, ou clic droit puis Quitter pour fermer le "
        "programme.",
        "Flashwatch is still running here. Double-click the icon to reopen the "
        "settings, or right-click then Quit to close the program."),

    # -- updates ---------------------------------------------------------
    "update.available": ("Flashwatch {version} est disponible.",
                         "Flashwatch {version} is available."),
    "update.banner": ("Nouvelle version disponible : {version} "
                      "(vous avez la {current}).",
                      "New version available: {version} "
                      "(you have {current})."),
    "update.install": ("Mettre a jour maintenant", "Update now"),
    "update.notes": ("Voir les nouveautes", "See what changed"),
    "update.skip": ("Ignorer cette version", "Skip this version"),
    "update.downloading": ("Telechargement... {percent}%",
                           "Downloading... {percent}%"),
    "update.installing": ("Installation...", "Installing..."),
    "update.restarting": (
        "Mise a jour installee. Flashwatch redemarre.",
        "Update installed. Flashwatch is restarting."),
    "update.restart_manually": (
        "Mise a jour installee. Relancez Flashwatch pour l'utiliser.",
        "Update installed. Start Flashwatch again to use it."),
    "update.failed": ("La mise a jour a echoue : {error}",
                      "The update failed: {error}"),
    "update.failed_hint": (
        "Vous pouvez toujours telecharger la nouvelle version depuis la page "
        "des releases.",
        "You can still download the new version from the releases page."),
    "update.read_only": (
        "Flashwatch ne peut pas s'ecrire dans {folder}. Telechargez la nouvelle "
        "version a la main, ou deplacez le programme dans un dossier a vous.",
        "Flashwatch cannot write to {folder}. Download the new version by hand, "
        "or move the program to a folder of your own."),
    "update.keeps_settings": (
        "Vos reglages et les icones deja telechargees sont conserves : ils "
        "vivent dans le dossier assets, pas dans l'executable. L'ancienne "
        "version est supprimee, il ne reste qu'un seul fichier.",
        "Your settings and the icons already downloaded are kept: they live in "
        "the assets folder, not inside the executable. The old version is "
        "removed, so only one file is left."),

    # -- control window: header, navigation, footer -----------------------
    "ui.tagline": ("Timers des sorts ennemis, lus a l'ecran",
                   "Enemy spell cooldowns, read off the screen"),
    "ui.nav_home": ("Accueil", "Home"),
    "ui.nav_display": ("Affichage", "Display"),
    "ui.nav_settings": ("Reglages", "Settings"),
    "ui.nav_help": ("Depannage", "Troubleshooting"),
    "ui.hide_window": ("Masquer la fenetre", "Hide this window"),
    "ui.hide_window_tip": (
        "Le programme continue de tourner dans la zone de notification, en bas "
        "a droite. Double-cliquez sur son icone pour revenir ici.",
        "The program keeps running in the notification area, bottom right. "
        "Double-click its icon to come back here."),
    "ui.quit": ("Quitter (fermer le programme)", "Quit (close the program)"),
    # The same action, said shorter: in the side rail there is no room for the
    # parenthesis, and none needed either -- the rail button sits under "Masquer
    # la fenetre", so the difference between the two is already the sentence.
    "ui.quit_rail": ("Quitter le programme", "Quit the program"),

    # -- the live state pill ----------------------------------------------
    "ui.pill_in_game": ("EN PARTIE", "IN GAME"),
    "ui.pill_client": ("CLIENT OUVERT", "CLIENT OPEN"),
    "ui.pill_waiting": ("EN ATTENTE", "WAITING"),
    "ui.pill_loading": ("CHARGEMENT", "LOADING"),
    "ui.pill_error": ("PROBLEME", "PROBLEM"),
    "ui.pill_demo": ("ESSAI", "TRIAL"),

    # -- home page --------------------------------------------------------
    "ui.state_game": ("Jeu :", "Game:"),
    "ui.state_region": ("Zone de chat :", "Chat area:"),
    "ui.state_ocr": ("OCR :", "OCR:"),
    "ui.state_timers": ("Timers actifs :", "Active timers:"),
    "ui.state_clock": ("Horloge estimee :", "Estimated clock:"),
    "ui.home_headline_idle": ("Rien a faire : lancez une partie",
                              "Nothing to do: start a game"),
    "ui.home_headline_idle_hint": (
        "Flashwatch attend en arriere-plan. La barre apparaitra toute seule des "
        "que l'ecran de jeu s'affiche, et se remplira au premier sort ennemi. "
        "Pour voir tout de suite a quoi elle ressemble et la placer : Affichage, "
        "puis \"Afficher des sorts d'exemple\".",
        "Flashwatch waits in the background. The bar shows up by itself once the "
        "in-game screen does, and fills in on the first enemy spell. To see what "
        "it looks like right now and place it: Display, then \"Show sample "
        "cooldowns\"."),
    "ui.home_headline_live": ("En train de lire votre chat",
                              "Reading your chat right now"),
    "ui.home_headline_live_hint": (
        "Chaque sort annonce dans le chat demarre un compte a rebours. Vous "
        "n'avez aucune touche a presser.",
        "Every spell announced in chat starts a countdown. There is no key for "
        "you to press."),
    "ui.home_headline_demo": ("Mode essai : ce que vous voyez est faux",
                             "Trial mode: what you see is not real"),
    "ui.home_headline_demo_hint": (
        "Des sorts d'exemple sont affiches pour que vous puissiez juger et placer "
        "l'affichage. Rien n'est lu a l'ecran pour l'instant, et tout s'effacera "
        "quand une vraie partie demarrera.",
        "Sample cooldowns are on screen so you can judge and place the display. "
        "Nothing is being read from the screen right now, and it all clears when a "
        "real game starts."),
    "ui.home_headline_boot": ("Preparation en cours",
                              "Getting ready"),
    "ui.home_headline_boot_hint": (
        "Les donnees Riot (noms et icones) se telechargent une seule fois, au "
        "premier lancement.",
        "Riot's data (names and icons) downloads once, on the first run."),
    "ui.guide_card": ("Guide d'installation", "Setup guide"),
    "ui.guide_card_hint": (
        "Trois minutes : mode d'affichage de League, langue du client, cadrage "
        "du chat, position de la barre.",
        "Three minutes: League's display mode, your client language, framing the "
        "chat, and where the bar sits."),
    "ui.guide_open": ("Ouvrir le guide", "Open the guide"),
    "ui.test_card": ("Test", "Test"),
    "ui.test_hint": (
        "Une vraie image de partie est fournie avec le programme. Le test la lit "
        "de bout en bout (recherche du chat, OCR, reconnaissance des sorts) et "
        "demarre les timers correspondants, sans attendre de partie.",
        "A real game frame ships with the program. The test reads it end to end "
        "(finding the chat, OCR, recognising the spells) and starts the matching "
        "timers, with no game needed."),
    "ui.test_run": ("Lancer le test", "Run the test"),
    "ui.test_again": ("Relancer le test", "Run the test again"),
    "ui.test_running": ("Lecture de l'image...", "Reading the image..."),
    "ui.test_not_ready": (
        "Les donnees Riot finissent de charger. Reessayez dans un instant.",
        "Riot's data is still loading. Try again in a moment."),
    "ui.test_pass": ("La chaine de lecture fonctionne.",
                     "The reading chain works."),
    "ui.test_fail_region": (
        "Le chat n'a pas ete localise dans l'image. C'est la detection de zone "
        "qui est en cause, pas votre configuration.",
        "The chat was not located in the image. That points at the area "
        "detection, not at your setup."),
    "ui.test_fail_parse": (
        "Le texte a bien ete lu, mais aucun sort n'y a ete reconnu.",
        "The text was read, but no spell was recognised in it."),
    "ui.test_fail_partial": (
        "Une partie seulement des sorts attendus a ete reconnue.",
        "Only some of the expected spells were recognised."),
    "ui.test_error": ("Le test n'a pas pu tourner : {error}",
                      "The test could not run: {error}"),
    "ui.test_detail": (
        "Zone trouvee {region}, {lines} lignes lues dont {chat} reconnues comme "
        "du chat, {ms:.0f} ms",
        "Area found {region}, {lines} lines read of which {chat} recognised as "
        "chat, {ms:.0f} ms"),
    "ui.test_hit": ("{champion} - {spell} : timer demarre ({time})",
                    "{champion} - {spell}: timer started ({time})"),
    "ui.test_hit_existing": ("{champion} - {spell} : reconnu, timer deja en cours",
                             "{champion} - {spell}: recognised, timer already running"),
    "ui.test_miss": ("{champion} - {spell} : non reconnu",
                     "{champion} - {spell}: not recognised"),
    "ui.test_scope": (
        "Ce test ne lit pas votre ecran : il ne peut donc pas confirmer que la "
        "capture de votre partie fonctionne. Pour ca, utilisez Cadrer le chat "
        "pendant une partie, dans Depannage.",
        "This test does not read your screen, so it cannot confirm that capturing "
        "your own game works. For that, use Frame the chat during a game, under "
        "Troubleshooting."),
    "ui.copy": ("Copier", "Copy"),
    "ui.enemies": ("Ennemis reperes", "Enemies spotted"),
    "ui.ocr_summary": ("{runs} analyses, {ms:.0f} ms, {skipped:.0f}% ignorees",
                       "{runs} reads, {ms:.0f} ms, {skipped:.0f}% skipped"),
    "ui.redetect": ("Redetecter le chat", "Detect the chat again"),
    "ui.manual_region": ("Definir la zone manuellement", "Set the area by hand"),
    "ui.forget_region": ("Oublier la zone enregistree", "Forget the saved area"),
    "ui.reset_timers": ("Reinitialiser les timers", "Reset the timers"),
    "ui.test_mode": ("Cadrer le chat", "Frame the chat"),
    "ui.test_mode_tip": (
        "Affiche un cadre autour de la zone lue. Deplacez-le pendant la partie : "
        "l'OCR suit le cadre et indique ce qu'il lit.",
        "Draws a frame around the area being read. Move it during a game: the "
        "OCR follows the frame and reports what it reads."),
    "ui.test_mode_clock": ("Cadrer le temps de partie",
                           "Frame the game clock"),
    "ui.test_mode_clock_tip": (
        "Placez le cadre sur le chronometre de la partie, en haut de l'ecran. "
        "Une fois valide, l'application lit l'heure du jeu directement au lieu "
        "de la deduire des horodatages du chat.",
        "Put the frame over the match timer at the top of the screen. Once "
        "applied, the app reads the game clock directly instead of inferring it "
        "from chat timestamps."),
    "ui.test_mode_scoreboard": ("Cadrer les ennemis (scoreboard)",
                                "Frame the enemies (scoreboard)"),
    "ui.test_mode_scoreboard_tip": (
        "Maintenez Tab, puis placez le cadre sur la colonne des cinq portraits "
        "ennemis. Chaque portrait est compare aux icones deja telechargees, et "
        "sa position dans la colonne donne le role.",
        "Hold Tab, then put the frame over the column of five enemy portraits. "
        "Each portrait is compared with the icons already downloaded, and its "
        "position in the column gives the role."),
    "ui.test_mode_loading": ("Cadrer l'ecran de chargement",
                             "Frame the loading screen"),
    "ui.test_mode_loading_tip": (
        "Placez le cadre sur la rangee des cinq ennemis, pendant le chargement. "
        "Les noms de champions y sont ecrits, et leur ordre donne les roles : "
        "top, jungle, mid, adc, support.",
        "Put the frame over the row of five enemies while the game loads. Their "
        "champion names are printed there, and their order gives the roles: top, "
        "jungle, mid, adc, support."),
    "ui.show_overlay": ("Afficher l'overlay", "Show the overlay"),
    "ui.locked": ("Verrouille (clics traversants)", "Locked (click-through)"),
    "ui.locked_hint": (
        "Verrouillee, la barre laisse passer les clics vers le jeu et ne peut "
        "pas prendre le focus. Decochez pour la deplacer.",
        "Locked, the bar lets clicks through to the game and can never take "
        "focus. Untick it to move the bar."),
    "ui.borderless_tip": (
        "Astuce : jouez en mode fenetre sans bordure. En plein ecran exclusif, "
        "Windows empeche tout overlay de s'afficher.",
        "Tip: play in borderless windowed mode. In exclusive fullscreen, Windows "
        "prevents any overlay from being drawn."),

    # -- display page: choosing and placing the overlay -------------------
    "ui.display_choose": ("Choisissez votre affichage",
                          "Pick the display you prefer"),
    "ui.display_choose_hint": (
        "Les trois montrent exactement la meme information. Prenez celui que "
        "votre oeil lit le plus vite en combat.",
        "All three show exactly the same information. Take the one your eye reads "
        "fastest in a fight."),
    "ui.layout_bar": ("Barre chrono", "Chrono track"),
    "ui.layout_bar_hint": (
        "L'icone entre a gauche au lancement du sort et arrive a droite quand il "
        "revient : la position dit tout, sans lire les chiffres.",
        "The icon enters on the left when the spell is cast and reaches the right "
        "as it comes back: position alone tells you, without reading numbers."),
    "ui.layout_cards": ("Cartes fixes", "Fixed cards"),
    "ui.layout_cards_hint": (
        "Une carte par sort, a une place qui ne bouge jamais, avec un anneau de "
        "progression autour du portrait.",
        "One card per spell, in a place that never moves, with a progress ring "
        "around the portrait."),
    "ui.layout_list": ("Rangées compactes", "Compact rows"),
    "ui.layout_list_hint": (
        "Une ligne par sort : champion, sort, temps restant et une jauge de "
        "progression. Le plus lisible, le plus haut.",
        "One row per spell: champion, spell, time left and a progress gauge. The "
        "most readable, and the tallest."),
    "ui.position": ("Position a l'ecran", "Where it sits on screen"),
    "ui.position_hint": (
        "L'affichage se pose ou vous voulez : glissez-le n'importe ou, "
        "redimensionnez-le par le coin en bas a droite. Chaque affichage garde sa "
        "propre position.",
        "The display goes wherever you want: drag it anywhere, resize it from the "
        "bottom-right corner. Each display keeps its own position."),
    "ui.move_start": ("Deplacer / redimensionner", "Move / resize"),
    "ui.move_done": ("J'ai fini, verrouiller", "Done, lock it"),
    "ui.move_active": (
        "Deverrouille : glissez la barre ou vous voulez, tirez le coin en bas a "
        "droite pour la taille, puis revenez verrouiller.",
        "Unlocked: drag the bar wherever you like, pull the bottom-right corner "
        "to resize, then come back and lock it."),
    "ui.advanced": ("Options avancees", "Advanced options"),

    # -- settings tab ----------------------------------------------------
    "ui.language": ("Langue du client", "Client language"),
    "ui.language_fr": ("Francais (client FR)", "French (FR client)"),
    "ui.language_en": ("Anglais (client EN)", "English (EN client)"),
    "ui.language_tip": (
        "Langue du client League : elle decide des textes recherches dans le "
        "chat et des noms de champions et de sorts telecharges. L'interface "
        "suit le meme choix.",
        "Your League client's language: it decides which chat wordings are "
        "looked for and which champion and spell names are downloaded. The "
        "interface follows the same choice."),
    "ui.language_reloading": (
        "Langue changee. Donnees Riot rechargees en arriere-plan.",
        "Language changed. Riot data is reloading in the background."),
    "ui.appearance": ("Apparence", "Appearance"),
    "ui.hide_until_in_game": ("Afficher seulement pendant la partie",
                              "Show only during a game"),
    "ui.hide_until_in_game_tip": (
        "La barre reste invisible sur le bureau et dans le client. Elle "
        "apparait des que l'ecran de jeu est affiche (et reste visible quand "
        "l'overlay est deverrouille, pour pouvoir la deplacer).",
        "The bar stays off the desktop and the client. It appears as soon as the "
        "in-game screen does (and is always shown while the overlay is unlocked, "
        "so it can be moved)."),
    "ui.bar_when_idle": ("Garder la barre visible au repos",
                        "Keep the bar visible at rest"),
    "ui.bar_when_idle_hint": (
        "Sans cela, la barre est totalement invisible quand aucun sort n'est en "
        "recharge : plus discret, mais aucun signe que le programme tourne.",
        "Without it the bar is completely invisible while nothing is on "
        "cooldown: more discreet, but no sign the program is running."),
    "ui.bar_vertical": ("Barre chronologique verticale",
                        "Vertical timeline"),
    "ui.bar_vertical_hint": (
        "La barre se dresse sur le cote de l'ecran : les recharges descendent "
        "de haut en bas, le temps restant s'affiche a cote de chaque champion. "
        "Elle garde sa propre position, distincte de la barre horizontale.",
        "The bar stands up along the side of the screen: cooldowns run from top "
        "to bottom and the time left sits beside each champion. It keeps its own "
        "position, separate from the horizontal bar."),
    "ui.recentre": ("Remettre en place", "Put it back"),
    "ui.recentre_tip": (
        "Replace l'affichage courant a sa position par defaut. Utile apres un "
        "changement de resolution ou d'ecran.",
        "Puts the current display back at its default spot. Useful after changing "
        "resolution or monitor."),

    # -- trial mode -------------------------------------------------------
    "ui.demo": ("Essayer sans lancer de partie", "Try it without starting a game"),
    "ui.demo_hint": (
        "Des sorts d'exemple s'affichent en continu, dans tous les etats : "
        "fraichement lance, a mi-course, bientot pret, deja dispo. De quoi "
        "comparer les trois affichages, essayer un theme et poser la barre ou "
        "vous voulez. Ca s'arrete tout seul quand une vraie partie demarre.",
        "Sample cooldowns stay on screen in every state: just cast, halfway, "
        "nearly back, already up. Enough to compare the three displays, try a "
        "theme and put the bar where you want it. It stops by itself when a real "
        "game starts."),
    "ui.demo_start": ("Afficher des sorts d'exemple", "Show sample cooldowns"),
    "ui.demo_stop": ("Arreter l'essai", "Stop the trial"),
    "ui.theme": ("Theme :", "Theme:"),
    "ui.theme_dark": ("Sombre", "Dark"),
    "ui.theme_light": ("Clair", "Light"),
    "ui.theme_neon": ("Neon", "Neon"),
    "ui.opacity": ("Opacite :", "Opacity:"),
    "ui.scale": ("Echelle :", "Scale:"),
    "ui.timer_font": ("Police du chrono :", "Timer font:"),
    "ui.timer_font_auto": ("Automatique", "Automatic"),
    "ui.timer_font_tip": (
        "Ne concerne que le compte a rebours, pas les noms. Automatique prend la "
        "meilleure police presente sur cette machine : des chiffres de largeur "
        "fixe, pour que le nombre ne tressaute pas a chaque seconde.",
        "Affects the countdown only, never the names. Automatic takes the best "
        "face present on this machine: fixed-width digits, so the number does "
        "not twitch on every tick."),
    "ui.timer_size": ("Taille du chrono :", "Timer size:"),
    "ui.timer_size_tip": (
        "Taille du compte a rebours, independamment de l'echelle generale : de "
        "quoi garder de grands portraits avec un nombre discret, ou l'inverse. "
        "Les lignes se redimensionnent avec lui.",
        "Size of the countdown, separately from the overall scale: enough to keep "
        "large portraits with a discreet number, or the other way round. The rows "
        "resize with it."),
    "ui.sort_by_role": ("Trier par role", "Sort by role"),
    "ui.hide_ready": ("Masquer les sorts disponibles", "Hide spells that are up"),
    "ui.ready_linger": ("Garder READY affiche :", "Keep READY on screen:"),
    "ui.ready_linger_tip": (
        "Duree pendant laquelle un sort revenu affiche READY avant que sa ligne "
        "disparaisse. 0 la fait disparaitre des qu'il est pret.",
        "How long a spell that is back up keeps showing READY before its entry "
        "disappears. 0 removes it as soon as it is ready."),
    "ui.tracking": ("Suivi", "Tracking"),
    "ui.track_summoners": ("Sorts d'invocateur (exact)",
                           "Summoner spells (exact)"),
    "ui.track_ultimates": ("Ultimes (approximatif, ~)",
                           "Ultimates (approximate, ~)"),
    "ui.chat_calls": ("Timers annonces dans le chat",
                      "Timers called in chat"),
    "ui.chat_calls_tip": (
        "Un coequipier qui tape \"jgl flash 950\" lance le timer du jungler "
        "jusqu'a 9:50 sur l'horloge de la partie. Le role (top, jgl, mid, adc, "
        "supp) ou le nom du champion, le sort, et l'heure : les trois sont "
        "obligatoires. Sans heure, rien ne demarre -- \"top no flash\" n'est pas "
        "un timer. Ces timers portent le \"?\", parce qu'ils viennent de "
        "quelqu'un et pas du jeu.",
        "A teammate typing \"jgl flash 950\" starts the jungler's timer until "
        "9:50 on the game clock. The role (top, jgl, mid, adc, supp) or the "
        "champion's name, the spell, and the time: all three are required. With "
        "no time nothing starts -- \"top no flash\" is not a timer. These timers "
        "carry the \"?\", because they come from somebody rather than from the "
        "game."),
    "ui.auto_roles": ("Lire les roles ennemis a l'ecran",
                      "Read the enemy roles from the screen"),
    "ui.auto_roles_tip": (
        "L'ecran de chargement et le scoreboard listent une equipe dans l'ordre "
        "des lignes : top, jungle, mid, adc, support. Les deux zones se cadrent "
        "dans Depannage. Decochez pour ne garder que les roles choisis a la main "
        "dans la liste des ennemis.",
        "The loading screen and the scoreboard both list a team in lane order: "
        "top, jungle, mid, adc, support. Both areas are framed on the "
        "Troubleshooting page. Untick to keep only the roles picked by hand in "
        "the enemies list."),
    "ui.enemy_colour": ("Uniquement les ennemis", "Enemies only"),
    "ui.enemy_colour_tip": (
        "Ne concerne que les lignes du type \"Attendez <champion> <sort> - N "
        "sec.\", qui indiquent un temps restant sans dire de quelle equipe il "
        "s'agit : seule la couleur du nom le dit. Laissez decoche si vous tapez "
        "cette phrase vous-meme pour tester l'OCR, car votre propre texte n'est "
        "pas affiche en rouge. Les annonces \"a utilise\" ne sont jamais "
        "filtrees : le jeu ne les affiche que pour les ennemis.",
        "Only affects lines like \"Wait <champion> <spell> - N sec.\", which "
        "state a remaining time without saying whose it is: only the colour of "
        "the name does. Leave it unticked if you type that line yourself to test "
        "the OCR, since your own text is not drawn in red. \"used\" "
        "announcements are never filtered: the game prints those for enemies "
        "only."),
    "ui.cosmic": ("Supposer Perspicacite cosmique (-18%)",
                  "Assume Cosmic Insight (-18%)"),
    "ui.ionian": ("Supposer Bottes ioniennes (-12%)",
                  "Assume Ionian Boots of Lucidity (-12%)"),
    "ui.ultimate_note": (
        "Les ultimes dependent du rang et de l'acceleration de competences, "
        "invisibles a l'ecran. Ils sont estimes d'apres l'horloge de la partie "
        "et marques d'un ~.",
        "Ultimates depend on ability rank and haste, neither of which is visible "
        "on screen. They are estimated from the game clock and marked with a ~."),
    "ui.notifications": ("Notifications", "Notifications"),
    "ui.audio": ("Activer le son", "Enable sound"),
    "ui.audio_ready": ("Signaler les sorts prets", "Announce ready spells"),
    "ui.audio_warn": ("Alerte avant :", "Warn before:"),
    "ui.audio_sfx": ("Son :", "Sound:"),
    "ui.audio_preview": ("Ecouter", "Play"),
    "ui.audio_preview_tip": (
        "Joue le son de retour de sort. Choisir dans la liste le joue aussi, "
        "meme si les notifications sont coupees.",
        "Plays the spell-is-back cue. Picking from the list plays it too, even "
        "when notifications are switched off."),

    # -- the notification voices -----------------------------------------
    # Named for what they sound like rather than for how they are made: nobody
    # picks a cue by its synthesis engine. Listed in the order the settings show
    # them, which walks through the families -- struck, metallic, breathy,
    # sliding, wavering, swelling -- instead of shuffling them.
    "sfx.chime": ("Carillon", "Chime"),
    "sfx.bell": ("Cloche", "Bell"),
    "sfx.bowl": ("Bol chantant", "Singing bowl"),
    "sfx.marimba": ("Marimba", "Marimba"),
    "sfx.harp": ("Harpe", "Harp"),
    "sfx.musicbox": ("Boite a musique", "Music box"),
    "sfx.knock": ("Toc-toc", "Knock"),
    "sfx.tick": ("Tic", "Tick"),
    "sfx.fmbell": ("Cloche metallique", "Metal bell"),
    "sfx.glass": ("Verre", "Glass"),
    "sfx.reed": ("Anche", "Reed"),
    "sfx.clave": ("Claves", "Claves"),
    "sfx.breath": ("Souffle", "Breath"),
    "sfx.brush": ("Balai", "Brush"),
    "sfx.shaker": ("Maracas", "Shaker"),
    "sfx.hush": ("Chuchotement", "Hush"),
    "sfx.swoop": ("Montee", "Swoop"),
    "sfx.droplet": ("Goutte", "Droplet"),
    "sfx.warble": ("Tremolo", "Warble"),
    "sfx.vibrato": ("Vibrato", "Vibrato"),
    "sfx.pad": ("Nappe", "Pad"),
    "sfx.choir": ("Choeur", "Choir"),
    "ui.capture": ("Capture", "Capture"),
    "ui.interval": ("Intervalle :", "Interval:"),

    "ui.startup": ("Demarrage", "Startup"),
    "ui.autostart": ("Lancer au demarrage de Windows", "Start with Windows"),
    "ui.autostart_note": (
        "Le programme doit tourner avant le debut de la partie : il ne peut "
        "pas rattraper les annonces ecrites avant son lancement. Il demarre "
        "dans la zone de notification, sans fenetre. Windows laisse aussi "
        "desactiver cette entree dans le Gestionnaire des taches, onglet "
        "Demarrage.",
        "The program has to be running before the game starts: it cannot "
        "recover announcements printed before it launched. It starts in the "
        "notification area, with no window. Windows also lets you switch this "
        "entry off from Task Manager's Startup tab."),
    "ui.open_window": ("Ouvrir la fenetre au lancement",
                       "Open the window on launch"),
    "ui.open_window_tip": (
        "Decochez pour que Flashwatch demarre directement dans la zone de "
        "notification. La fenetre reste accessible : double-cliquez l'icone de "
        "la barre des taches.",
        "Untick to have Flashwatch start straight in the notification area. The "
        "window stays one double-click on the tray icon away."),
    "ui.open_window_note": (
        "Un demarrage avec Windows n'ouvre jamais la fenetre, quelle que soit "
        "cette case : le programme est alors lance pour etre deja pret quand une "
        "partie commence, pas pour etre regarde.",
        "A start with Windows never opens the window, whatever this box says: "
        "the program is launched then so that it is already running when a game "
        "begins, not so that it can be looked at."),
    "ui.autostart_failed": (
        "Windows a refuse la modification (strategie de securite ?). "
        "L'entree de demarrage n'a pas ete changee.",
        "Windows refused the change (security policy?). The startup entry was "
        "not modified."),

    "ui.updates": ("Mises a jour", "Updates"),
    "ui.update_check": ("Verifier au demarrage", "Check on start-up"),
    "ui.update_check_tip": (
        "Une requete a GitHub au lancement. Rien ne se telecharge sans que vous "
        "cliquiez : la nouvelle version est seulement proposee.",
        "One request to GitHub at launch. Nothing downloads unless you click: "
        "the new version is only offered."),
    "ui.update_installed": ("Version installee :", "Installed version:"),
    "ui.update_check_now": ("Verifier maintenant", "Check now"),
    "ui.update_checking": ("Verification...", "Checking..."),
    "ui.update_up_to_date": ("Vous avez la derniere version.",
                             "You have the latest version."),
    "ui.update_unavailable": (
        "Verification impossible (pas de reseau ?).",
        "Could not check (no network?)."),
    "ui.update_from_source": (
        "Lance depuis les sources : il n'y a pas d'executable a remplacer.",
        "Running from source: there is no executable to replace."),

    # -- enemies and their roles -----------------------------------------
    "ui.team_help": (
        "Les champions apparaissent des que l'ecran de chargement ou le "
        "scoreboard est lu, ou au premier sort detecte. Le role choisi ici "
        "l'emporte toujours sur celui lu a l'ecran.",
        "Champions appear as soon as the loading screen or the scoreboard is "
        "read, or on the first spell detected. A role picked here always wins "
        "over one read off the screen."),
    "ui.team_empty": (
        "Aucun ennemi repere pour l'instant. Ils s'ajoutent tout seuls au premier "
        "sort detecte.",
        "No enemy spotted yet. They add themselves on the first spell detected."),

    # -- troubleshooting page --------------------------------------------
    "ui.help_intro": (
        "Si aucun timer n'apparait, la cause est presque toujours l'une des "
        "trois : League n'est pas en fenetre sans bordure, la langue ne "
        "correspond pas a celle du client, ou la zone du chat est mal cadree.",
        "If no timer appears, it is nearly always one of three things: League is "
        "not in borderless windowed mode, the language does not match the "
        "client's, or the chat area is framed wrong."),
    "ui.chat_area": ("Zone du chat", "Chat area"),
    "ui.chat_area_hint": (
        "Trouvee automatiquement d'apres le contenu du chat. Ces boutons servent "
        "quand elle ne l'est pas.",
        "Found automatically from what the chat contains. These buttons are for "
        "when it is not."),
    "ui.zones": ("Cadrer les zones lues", "Frame the areas being read"),
    "ui.zones_hint": (
        "Chaque bouton pose un cadre a l'ecran, que vous deplacez pendant la "
        "partie ; il affiche en direct ce que l'OCR lit dedans.",
        "Each button puts a frame on screen that you move during a game; it "
        "reports live what the OCR reads inside it."),
    "ui.diagnostics": ("Ce que l'application lit", "What the application reads"),

    # -- debug readouts --------------------------------------------------
    "ui.debug_lines": ("Lignes lues par l'OCR :", "Lines read by the OCR:"),
    "ui.debug_misses": (
        "Lignes contenant un champion mais non interpretees. Si le jeu annonce "
        "les sorts avec une formulation differente, elle apparait ici :",
        "Lines naming a champion that were not understood. If the game words "
        "spell announcements differently, it shows up here:"),
    "ui.debug_colour": (
        "Sorts lus mais ignores car le champion n'etait pas affiche en rouge, "
        "donc pas un ennemi (ping sur son propre sort, sort d'un allie) :",
        "Spells read but ignored because the champion was not drawn in red, so "
        "not an enemy (a ping on one's own spell, an ally's spell):"),
    "ui.debug_events": ("Evenements confirmes :", "Confirmed events:"),

    # -- the setup guide -------------------------------------------------
    # Seven screens, drawn from design/maquette/Onboarding *.dc.html. The wording
    # is the mockups' own, which means two things this catalogue does nowhere
    # else: it says "tu", and it is written with its accents. The rest of the
    # file is ASCII because it was written before anything drew accented text;
    # the guide draws every word of itself with an embedded font that has them.
    "guide.title": ("Guide d'installation", "Setup guide"),
    "guide.step": ("Etape {step} sur {total}", "Step {step} of {total}"),
    "guide.back": ("Retour", "Back"),
    "guide.next": ("Suivant", "Next"),
    "guide.finish": ("Terminer", "Finish"),

    # The eight labels under the stepper's circles.
    "guide.nav_language": ("Langue du client", "Client language"),
    "guide.nav_welcome": ("Bienvenue", "Welcome"),
    "guide.nav_borderless": ("Fenêtré sans bordure", "Borderless window"),
    "guide.nav_layout": ("Choisir l'affichage", "Pick a display"),
    "guide.nav_tune": ("Le régler", "Tune it"),
    "guide.nav_place": ("Le poser", "Place it"),
    "guide.nav_proof": ("La preuve", "The proof"),
    "guide.nav_done": ("Tout est prêt", "All set"),

    # -- 1. the client's language ----------------------------------------
    "guide.language_title": ("Langue du client", "Client language"),
    "guide.language_lead": (
        "Le Guide et l'overlay parlent <b>la même langue</b> que ton client "
        "League of Legends.",
        "The guide and the overlay speak <b>the same language</b> as your "
        "League of Legends client."),
    "guide.language_lead_2": (
        "Sélectionne celle de ton client juste en dessous.",
        "Pick your client's language just below."),
    "guide.language_note": (
        "Tu pourras la changer plus tard dans les paramètres du Guide.",
        "You can change it later in the guide's settings."),
    "guide.language_pick": (
        "Sélectionne la langue de ton client League of Legends",
        "Pick your League of Legends client language"),
    # A language's own name, which does not change with the interface language.
    "guide.language_fr_name": ("Français", "Français"),
    "guide.language_en_name": ("English", "English"),
    "guide.language_fr_sub": ("Version française", "French version"),
    "guide.language_en_sub": ("English version", "English version"),

    # -- 2. welcome ------------------------------------------------------
    "guide.welcome_title": ("Bienvenue", "Welcome"),
    "guide.welcome_lead": (
        "Nous allons tout configurer dans <b>l'Outil d'entraînement.</b>",
        "We are going to set everything up in the <b>Practice Tool.</b>"),
    "guide.welcome_path": (
        "Ouvre League of Legends, puis suis ce chemin dans le client :",
        "Open League of Legends, then follow this path in the client:"),
    "guide.welcome_blurb": (
        "Apprends à maîtriser ton champion favori grâce à cet "
        "entraînement de 1 à 10 joueurs dans la Faille de l'invocateur !",
        "Learn to master your favourite champion in this 1-to-10 player "
        "practice game on Summoner's Rift!"),
    "guide.welcome_path_play": ("JOUER", "PLAY"),
    "guide.welcome_path_training": ("ENTRAÎNEMENT", "TRAINING"),
    "guide.welcome_path_tool": ("OUTIL D'ENTRAÎNEMENT", "PRACTICE TOOL"),
    "guide.welcome_note": (
        "C'est un environnement d'entraînement privé : personne ne t'y attend, "
        "prends ton temps.",
        "It is a private practice environment: nobody is waiting for you, take "
        "your time."),

    # -- 3. borderless ---------------------------------------------------
    "guide.borderless_step_1": ("Va dans l'onglet <b>VIDÉO</b>.",
                                "Go to the <b>VIDEO</b> tab."),
    "guide.borderless_step_2": (
        "Dans <b>Mode fenêtré</b>, sélectionne <b>Sans bord</b>.",
        "Under <b>Window mode</b>, select <b>Borderless</b>."),
    "guide.borderless_avoid": ("À éviter : Plein écran", "Avoid: Fullscreen"),
    "guide.borderless_avoid_body": (
        "Le mode plein écran peut cacher l'overlay et empêcher le Guide de "
        "fonctionner.",
        "Fullscreen can hide the overlay and stop the guide from working."),
    "guide.borderless_note": (
        "Le mode Sans bord permet d'afficher correctement l'overlay tout en "
        "restant dans le jeu.",
        "Borderless lets the overlay draw properly while you stay in the game."),

    # -- 4. pick a display -----------------------------------------------
    "guide.layout_title": ("Choisir l'affichage", "Pick a display"),
    "guide.layout_lead": (
        "Clique sur un affichage à gauche. <b>Le résultat s'affiche en direct à "
        "droite</b> dans le Practice Tool.",
        "Click a display on the left. <b>The result shows live on the right</b> "
        "in the Practice Tool."),
    "guide.layout_note": (
        "Tu pourras changer d'affichage plus tard dans les paramètres.",
        "You can change the display later in the settings."),
    "guide.layout_result": ("Résultat dans le Practice Tool",
                            "The result in the Practice Tool"),
    "guide.layout_recommended": ("Recommandé", "Recommended"),

    # -- 5. tune it ------------------------------------------------------
    "guide.tune_title": ("Le régler", "Tune it"),
    "guide.tune_lead": (
        "Chaque réglage change <b>l'aperçu à droite</b> pendant que tu le "
        "tournes.",
        "Every setting changes <b>the preview on the right</b> as you turn "
        "it."),
    "guide.tune_behaviour": ("Ce qu'il affiche", "What it shows"),
    "guide.tune_note": (
        "Le chrono est le seul texte dont tu choisis la police : les noms "
        "gardent celle du programme.",
        "The countdown is the only text whose face you pick: the names keep "
        "the program's own."),
    "guide.tune_reset": ("Tout remettre par défaut", "Put it all back"),
    "guide.tune_reset_ask": ("Remettre ces réglages par défaut ?",
                             "Reset these settings to their defaults?"),
    "guide.tune_reset_yes": ("Oui, remettre", "Yes, reset"),
    "guide.tune_reset_no": ("Annuler", "Cancel"),

    # -- 6. place it -----------------------------------------------------
    "guide.place_title": ("Le poser", "Place it"),
    "guide.place_lead": (
        "L'affichage se glisse <b>n'importe où à l'écran</b>. Déverrouille-le, "
        "attrape-le, pose-le où tu veux le lire pendant une partie.",
        "The display drags <b>anywhere on screen</b>. Unlock it, grab it, drop "
        "it wherever you want to read it during a game."),
    "guide.place_action": ("Le placer maintenant", "Place it now"),
    "guide.place_note": (
        "Des sorts d'exemple s'affichent, déverrouillés : glisse le cadre, "
        "redimensionne-le par le coin en bas à droite. Tout se reverrouille dès "
        "qu'une vraie partie démarre.",
        "Sample cooldowns appear, unlocked: drag the frame, resize it from the "
        "bottom-right corner. It all locks itself again the moment a real game "
        "starts."),
    "guide.place_anywhere": ("ou n'importe où ailleurs", "or anywhere else"),

    # -- 7. the proof ----------------------------------------------------
    "guide.proof_title": ("La preuve", "The proof"),
    "guide.proof_lead": (
        "Une vraie image de partie est fournie avec le programme. "
        "<b>Un timer apparaît</b> : la chaîne entière fonctionne.",
        "A real game frame ships with the program. <b>A timer appears</b>: "
        "the whole chain works."),
    "guide.proof_action": ("Lancer le test", "Run the test"),
    "guide.proof_running": ("Lecture...", "Reading..."),
    # Says only what is true on a second press too, when the timers it would have
    # started are already running. The countdown beside each spell is what reports
    # a timer that did start.
    "guide.proof_pass": ("{count} sorts lus sur l'image.",
                         "{count} spells read from the frame."),
    "guide.proof_note": (
        "Rien n'est injecté dans League, sa mémoire n'est jamais lue, aucun clic "
        "ni appui de touche n'est envoyé au jeu. Uniquement les pixels déjà "
        "affichés sur ton écran.",
        "Nothing is injected into League, its memory is never read, and no click "
        "or key press is ever sent to the game. Only the pixels already on your "
        "screen."),
    "guide.proof_read": ("lue", "read"),
    "guide.proof_frame": (
        "Rien n'apparaît ? La zone du chat est trouvée toute seule ; si elle "
        "tombe à côté, ce bouton affiche un cadre à poser sur le tien, et "
        "montre en direct ce qui est lu dessous. Il reste dans Dépannage.",
        "Nothing appeared? The chat area is found on its own; if it lands in "
        "the wrong place, this button draws a box to put over yours, and shows "
        "live what it reads underneath. It stays in Troubleshooting."),

    # -- 8. all set ------------------------------------------------------
    "guide.done_title": ("Tout est prêt !", "All set!"),
    "guide.done_lead": (
        "Ton client League of Legends est maintenant configuré et optimisé.",
        "Your League of Legends client is now set up and ready."),
    "guide.done_check_display": ("Affichage optimisé", "Display set up"),
    "guide.done_check_borderless": ("Fenêtré sans bordure", "Borderless window"),
    "guide.done_check_settings": ("Paramètres appliqués", "Settings applied"),
    "guide.done_footer": (
        "Tu peux modifier ces paramètres à tout moment dans les <b>options.</b>",
        "You can change these settings at any time in the <b>options.</b>"),

    # Words drawn inside the illustrations. Two of the figures redraw League's
    # own client, so those are the client's labels rather than ours -- which is
    # the point: they are what has to be found on a screen this program never
    # sees.
    "guide.shot_chat": ("le chat de la partie", "the game chat"),
    "guide.shot_bar": ("les timers", "the timers"),
    "guide.shot_options": ("OPTIONS", "OPTIONS"),
    "guide.shot_tab_hotkeys": ("RACCOURCIS", "HOTKEYS"),
    "guide.shot_tab_camera": ("CAMÉRA", "CAMERA"),
    "guide.shot_tab_video": ("VIDÉO", "VIDEO"),
    "guide.shot_tab_audio": ("AUDIO", "AUDIO"),
    "guide.shot_tab_interface": ("INTERFACE", "INTERFACE"),
    "guide.shot_tab_game": ("JEU", "GAME"),
    "guide.shot_general": ("Général", "General"),
    "guide.shot_resolution": ("Résolution", "Resolution"),
    "guide.shot_mode": ("Mode fenêtré", "Window mode"),
    "guide.shot_borderless": ("Sans bord", "Borderless"),
    "guide.shot_fullscreen": ("Plein écran", "Fullscreen"),
    "guide.shot_graphics": ("Graphismes", "Graphics"),
    "guide.shot_quality": ("Très élevé", "Very high"),
    "guide.shot_save": ("Sauvegarder", "Save"),
    "guide.shot_cancel": ("Annuler", "Cancel"),
    "guide.shot_play": ("JOUER", "PLAY"),
    "guide.shot_training": ("ENTRAÎNEMENT", "TRAINING"),
    "guide.shot_tutorial": ("DIDACTICIEL", "TUTORIAL"),
    "guide.shot_practice": ("OUTIL D'ENTRAÎNEMENT", "PRACTICE TOOL"),
    "guide.shot_confirm": ("CONFIRMER", "CONFIRM"),

    # -- region picker ---------------------------------------------------
    "picker.hint": ("Tracez un rectangle autour du chat  -  Echap pour annuler",
                    "Draw a rectangle around the chat  -  Esc to cancel"),

    # -- test-mode frame -------------------------------------------------
    "zone.title": ("Zone OCR (mode test)", "OCR zone (test mode)"),
    "zone.name_chat": ("CHAT", "CHAT"),
    "zone.name_clock": ("TEMPS DE PARTIE", "GAME CLOCK"),
    "zone.name_scoreboard": ("SCOREBOARD (ENNEMIS)", "SCOREBOARD (ENEMIES)"),
    "zone.name_loading": ("ECRAN DE CHARGEMENT", "LOADING SCREEN"),
    "zone.clock_read": ("horloge lue : {value}", "clock read: {value}"),
    "zone.clock_unreadable": ("aucune horloge lisible dans ce cadre",
                              "no readable clock inside this frame"),
    "zone.clock_hint": ("Cadrez le chronometre en haut de l'ecran (mm:ss).",
                        "Frame the match timer at the top of the screen (mm:ss)."),
    "zone.scoreboard_hint": (
        "Maintenez Tab, puis cadrez la colonne des cinq portraits ennemis "
        "(haut en bas : top, jungle, mid, adc, support).",
        "Hold Tab, then frame the column of five enemy portraits (top to "
        "bottom: top, jungle, mid, adc, support)."),
    "zone.loading_hint": (
        "Cadrez la rangee des cinq ennemis sur l'ecran de chargement "
        "(gauche a droite : top, jungle, mid, adc, support).",
        "Frame the row of five enemies on the loading screen (left to right: "
        "top, jungle, mid, adc, support)."),
    "zone.roles_read": ("roles reconnus : {roles}", "roles recognised: {roles}"),
    "zone.roles_none": ("aucun champion reconnu dans ce cadre",
                        "no champion recognised inside this frame"),
    "zone.searching": ("recherche", "searching"),
    "zone.fixed": ("zone fixee", "area pinned"),
    "zone.header": ("MODE TEST  -  {width}x{height} @ {x},{y}  ({state})",
                    "TEST MODE  -  {width}x{height} @ {x},{y}  ({state})"),
    "zone.rows": ("{rows} ligne(s) lue(s), {chat} reconnue(s) comme chat",
                  "{rows} line(s) read, {chat} recognised as chat"),
    "zone.last_chat": ("derniere ligne chat : {line}", "last chat line: {line}"),
    "zone.no_chat": ("aucune ligne de chat lue pour l'instant",
                     "no chat line read yet"),
    "zone.keys": (
        "Bords = deplacer/redimensionner  -  fleches = 1 px  -  "
        "Maj+fleches = 10 px  -  Ctrl+fleches = taille",
        "Edges = move/resize  -  arrows = 1 px  -  Shift+arrows = 10 px  -  "
        "Ctrl+arrows = size"),
    "zone.apply": ("Valider", "Apply"),
    "zone.cancel": ("Annuler", "Cancel"),
}

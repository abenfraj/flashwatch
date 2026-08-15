"""Every user-facing string, in French and English.

One table rather than per-module constants: the point of translating is that a
missing string is *visible*, and a single catalogue makes an untranslated entry
obvious at a glance instead of hiding in whichever file happens to print it.

The language follows the League client language chosen in the settings, because
the two are almost never different in practice -- someone playing on an English
client reads English. It is deliberately not read from Windows: what matters is
the language of the chat being OCR'd, not the one the desktop is in.

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

_language = FRENCH


def language_for(locale: str) -> str:
    """Map a Riot locale ("fr_FR", "en_US") onto a language code."""
    return ENGLISH if str(locale).lower().startswith("en") else FRENCH


def locale_for(language: str) -> str:
    return LOCALES.get(language, LOCALES[FRENCH])


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
    "ui.test_line_title": ("Verifier que ca marche, sans attendre un ennemi",
                           "Check it works without waiting for an enemy"),
    "ui.test_line_hint": (
        "Collez cette ligne dans le chat de la partie : un timer doit apparaitre "
        "immediatement. Si oui, la lecture de l'ecran fonctionne et il ne reste "
        "qu'a attendre un vrai sort.",
        "Paste this line into the game chat: a timer must appear at once. If it "
        "does, screen reading works and all that is left is waiting for a real "
        "spell."),
    "ui.test_line": ("Attendez Darius Saut eclair - 245 sec.",
                     "Wait Darius Flash - 245 sec."),
    "ui.copy": ("Copier", "Copy"),
    "ui.copied": ("Copie !", "Copied!"),
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
    "ui.test_mode_scoreboard": ("Cadrer le scoreboard",
                                "Frame the scoreboard"),
    "ui.test_mode_scoreboard_tip": (
        "Placez le cadre sur le tableau des scores (touche Tab maintenue). Ce "
        "qu'il lit est affiche pour verification ; la zone est enregistree pour "
        "la lecture des objets ennemis, pas encore exploitee.",
        "Put the frame over the scoreboard (hold Tab). What it reads is shown so "
        "you can check it; the area is saved for the enemy-item reader, which is "
        "not wired up yet."),
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
        "Les champions apparaissent des qu'un sort est detecte. Attribuez un "
        "role pour regrouper l'affichage.",
        "Champions appear as soon as a spell is detected. Give one a role to "
        "group the display."),
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

    # The seven labels under the stepper's circles.
    "guide.nav_language": ("Langue du client", "Client language"),
    "guide.nav_welcome": ("Bienvenue", "Welcome"),
    "guide.nav_borderless": ("Fenêtré sans bordure", "Borderless window"),
    "guide.nav_layout": ("Choisir l'affichage", "Pick a display"),
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

    # -- 5. place it -----------------------------------------------------
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

    # -- 6. the proof ----------------------------------------------------
    "guide.proof_title": ("La preuve", "The proof"),
    "guide.proof_lead": (
        "Colle cette ligne dans le chat de l'Outil d'entraînement. "
        "<b>Un timer apparaît</b> : la chaîne entière fonctionne.",
        "Paste this line into the Practice Tool chat. <b>A timer appears</b>: "
        "the whole chain works."),
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

    # -- 7. all set ------------------------------------------------------
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
    "zone.name_scoreboard": ("SCOREBOARD", "SCOREBOARD"),
    "zone.clock_read": ("horloge lue : {value}", "clock read: {value}"),
    "zone.clock_unreadable": ("aucune horloge lisible dans ce cadre",
                              "no readable clock inside this frame"),
    "zone.clock_hint": ("Cadrez le chronometre en haut de l'ecran (mm:ss).",
                        "Frame the match timer at the top of the screen (mm:ss)."),
    "zone.text_read": ("{count} ligne(s) lue(s) : {sample}",
                       "{count} line(s) read: {sample}"),
    "zone.nothing_read": ("rien de lisible dans ce cadre",
                          "nothing readable inside this frame"),
    "zone.scoreboard_hint": (
        "Maintenez Tab pour afficher le scoreboard, puis cadrez-le.",
        "Hold Tab to bring up the scoreboard, then frame it."),
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

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
    "tray.recentre": ("Recentrer la barre en haut", "Recentre the bar at the top"),
    "tray.preview": ("Afficher un apercu (test)", "Show a preview (test)"),
    "tray.redetect": ("Redetecter le chat", "Detect the chat again"),
    "tray.reset": ("Reinitialiser les timers", "Reset the timers"),
    "tray.quit": ("Quitter (fermer le programme)", "Quit (close the program)"),
    "notify.zone_saved": ("Zone OCR enregistree ({width}x{height}).",
                          "OCR zone saved ({width}x{height})."),
    "notify.bar_in_game_only": (
        "La barre s'affichera automatiquement des que vous serez en partie.",
        "The bar will appear by itself once you are in a game."),
    "notify.preview": (
        "Apercu affiche pendant 20 secondes en haut de l'ecran.",
        "Preview shown for 20 seconds at the top of the screen."),
    "notify.hidden_to_tray": (
        "Flashwatch continue de tourner ici. Double-cliquez sur l'icone pour "
        "rouvrir les reglages, ou clic droit puis Quitter pour fermer le "
        "programme.",
        "Flashwatch is still running here. Double-click the icon to reopen the "
        "settings, or right-click then Quit to close the program."),

    # -- control window: tabs and footer ---------------------------------
    "ui.tab_status": ("Statut", "Status"),
    "ui.tab_settings": ("Reglages", "Settings"),
    "ui.tab_team": ("Equipe", "Team"),
    "ui.tab_debug": ("Debug", "Debug"),
    "ui.hide_window": ("Masquer (rester dans la zone de notification)",
                       "Hide (keep running in the notification area)"),
    "ui.quit": ("Quitter (fermer le programme)", "Quit (close the program)"),

    # -- status tab ------------------------------------------------------
    "ui.state": ("Etat", "State"),
    "ui.state_game": ("Jeu :", "Game:"),
    "ui.state_region": ("Zone de chat :", "Chat area:"),
    "ui.state_ocr": ("OCR :", "OCR:"),
    "ui.state_timers": ("Timers actifs :", "Active timers:"),
    "ui.state_clock": ("Horloge estimee :", "Estimated clock:"),
    "ui.ocr_summary": ("{runs} analyses, {ms:.0f} ms, {skipped:.0f}% ignorees",
                       "{runs} reads, {ms:.0f} ms, {skipped:.0f}% skipped"),
    "ui.actions": ("Actions", "Actions"),
    "ui.redetect": ("Redetecter le chat", "Detect the chat again"),
    "ui.manual_region": ("Definir la zone manuellement", "Set the area by hand"),
    "ui.forget_region": ("Oublier la zone enregistree", "Forget the saved area"),
    "ui.reset_timers": ("Reinitialiser les timers", "Reset the timers"),
    "ui.test_mode": ("Mode test : zone du chat", "Test mode: chat area"),
    "ui.test_mode_tip": (
        "Affiche un cadre autour de la zone lue. Deplacez-le pendant la partie : "
        "l'OCR suit le cadre et indique ce qu'il lit.",
        "Draws a frame around the area being read. Move it during a game: the "
        "OCR follows the frame and reports what it reads."),
    "ui.test_mode_clock": ("Mode test : zone du temps de partie",
                           "Test mode: game clock area"),
    "ui.test_mode_clock_tip": (
        "Placez le cadre sur le chronometre de la partie, en haut de l'ecran. "
        "Une fois valide, l'application lit l'heure du jeu directement au lieu "
        "de la deduire des horodatages du chat.",
        "Put the frame over the match timer at the top of the screen. Once "
        "applied, the app reads the game clock directly instead of inferring it "
        "from chat timestamps."),
    "ui.test_mode_scoreboard": ("Mode test : zone du scoreboard",
                                "Test mode: scoreboard area"),
    "ui.test_mode_scoreboard_tip": (
        "Placez le cadre sur le tableau des scores (touche Tab maintenue). Ce "
        "qu'il lit est affiche pour verification ; la zone est enregistree pour "
        "la lecture des objets ennemis, pas encore exploitee.",
        "Put the frame over the scoreboard (hold Tab). What it reads is shown so "
        "you can check it; the area is saved for the enemy-item reader, which is "
        "not wired up yet."),
    "ui.overlay": ("Overlay", "Overlay"),
    "ui.show_overlay": ("Afficher l'overlay", "Show the overlay"),
    "ui.locked": (
        "Verrouille (clics traversants) - decochez pour deplacer/redimensionner",
        "Locked (click-through) - untick to move or resize it"),
    "ui.borderless_tip": (
        "Astuce : jouez en mode fenetre sans bordure. En plein ecran exclusif, "
        "Windows empeche tout overlay de s'afficher.",
        "Tip: play in borderless windowed mode. In exclusive fullscreen, Windows "
        "prevents any overlay from being drawn."),

    # -- settings tab ----------------------------------------------------
    "ui.language": ("Langue / Language :", "Language / Langue:"),
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
    "ui.layout": ("Disposition :", "Layout:"),
    "ui.layout_bar": ("Barre en haut (compacte)", "Bar at the top (compact)"),
    "ui.layout_list": ("Liste verticale", "Vertical list"),
    "ui.hide_until_in_game": ("Masquer la barre tant qu'on n'est pas en partie",
                              "Hide the bar until you are in a game"),
    "ui.hide_until_in_game_tip": (
        "La barre reste invisible sur le bureau et dans le client. Elle "
        "apparait des que l'ecran de jeu est affiche (et reste visible quand "
        "l'overlay est deverrouille, pour pouvoir la deplacer).",
        "The bar stays off the desktop and the client. It appears as soon as the "
        "in-game screen does (and is always shown while the overlay is unlocked, "
        "so it can be moved)."),
    "ui.bar_when_idle": (
        "Afficher la barre vide quand aucun sort n'est en recharge",
        "Show the empty bar when nothing is on cooldown"),
    "ui.recentre": ("Recentrer en haut", "Recentre at the top"),
    "ui.preview": ("Afficher un apercu (test)", "Show a preview (test)"),
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
    "ui.track_ultimates": ("Ultimes (approximatif, prefixe ~)",
                           "Ultimates (approximate, prefixed with ~)"),
    "ui.enemy_colour": ("Uniquement les ennemis (nom du champion en rouge)",
                        "Enemies only (champion name drawn in red)"),
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
    "ui.audio_ready": ("Signaler quand le sort est pret",
                       "Announce when a spell is back up"),
    "ui.audio_warn": ("Alerte avant :", "Warn before:"),
    "ui.capture": ("Capture", "Capture"),
    "ui.interval": ("Intervalle :", "Interval:"),

    "ui.startup": ("Demarrage", "Startup"),
    "ui.autostart": ("Lancer Flashwatch au demarrage de Windows",
                     "Start Flashwatch when Windows starts"),
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

    # -- team tab --------------------------------------------------------
    "ui.team_help": (
        "Les champions apparaissent des qu'un sort est detecte. Attribuez un "
        "role pour regrouper l'affichage.",
        "Champions appear as soon as a spell is detected. Give one a role to "
        "group the display."),

    # -- debug tab -------------------------------------------------------
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

"""Lane roles: the names, the order, and the words players use for them.

Three places needed the same five strings and were each spelling them out: the
timer manager (to sort the overlay), the control window (to fill a combo box) and
now the two things added here -- the chat-call parser, which has to understand
"jgl", and the role readers, which turn a left-to-right or top-to-bottom order
into roles. One table instead of three.

The aliases are what a player types, not what the game prints. That is the whole
point: nobody types "JUNGLE" in chat, they type "jgl", "jng", "jg" or
"jungle", and a French client is just as likely to see "milieu" or "sup".
Single letters are deliberately absent -- "s" and "m" identify nothing, and a
call is only acted on when every part of it parses, so a one-letter guess
would poison an otherwise strict shape.
"""

from __future__ import annotations

from riot_assets import fold

# In lane order, which is also the order the loading screen and the scoreboard
# list a team in. That coincidence is what the readers rely on.
ROLES: tuple[str, ...] = ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT")

# Sort key for the overlay. "" (unknown) sorts last rather than first: a champion
# whose role we never worked out belongs at the end of the list, not at the top of
# it where the top laner should be.
ROLE_ORDER: dict[str, int] = {role: index for index, role in enumerate(ROLES)}
ROLE_ORDER[""] = len(ROLES)

# Folded, so accents and case never matter. Values are the canonical role.
#
# "tp" is deliberately absent: to everyone it means Teleport, and mapping it to a
# role would make "top tp 9:50" resolve the spell as the target.
ROLE_ALIASES: dict[str, str] = {}
for _role, _words in (
    ("TOP", ("top", "toplane", "toplaner", "haut")),
    ("JUNGLE", ("jungle", "jungler", "jgl", "jng", "jung", "jungl", "jg")),
    ("MID", ("mid", "midlane", "midlaner", "middle", "milieu")),
    ("ADC", ("adc", "bot", "botlane", "bottom", "botlaner", "carry", "adcarry",
             "ad")),
    ("SUPPORT", ("support", "supp", "sup", "soutien", "supporter")),
):
    for _word in _words:
        ROLE_ALIASES[fold(_word)] = _role
del _role, _words, _word


def role_from_word(word: str) -> str:
    """The role a single typed word names, or "" if it names none."""
    return ROLE_ALIASES.get(fold(word), "")


def assign_slots(slots: dict[int, str]) -> dict[str, str]:
    """Turn ``{position: champion}`` into ``{champion: role}``.

    Both the loading screen and the scoreboard list a team top, jungle, mid, bot,
    support -- the loading screen left to right, the scoreboard top to bottom --
    so the position *is* the role and nothing has to be recognised beyond the
    champion.

    Positions rather than a plain list, and that is the whole reason this exists.
    A reader that fails on one of the five has to leave a hole rather than close
    the gap: reading four champions and calling the first of them the top laner is
    right only if it was the *support* that went missing. A hole costs one unknown
    role; a shifted list costs four wrong ones.

    A champion appearing in two positions means the reading itself is wrong -- one
    team does not field the same champion twice -- so the whole result is thrown
    away rather than half-trusted.
    """
    assigned: dict[str, str] = {}
    for index, champion_id in slots.items():
        if not champion_id or not 0 <= index < len(ROLES):
            continue
        if champion_id in assigned:
            return {}
        assigned[champion_id] = ROLES[index]
    if len(set(assigned.values())) != len(assigned):
        return {}
    return assigned

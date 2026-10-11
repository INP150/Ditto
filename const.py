EMOJI_MAP = {
    ":+1:": "👍", ":thumbsup:": "👍", "👍": "👍",
    ":-1:": "👎", ":thumbsdown:": "👎", "👎": "👎",
}

TRANSLATE_TIME_MEASURE = {
    "S": "seconds",
    "M": "minutes",
    "H": "hours",
    "D": "days"
}

TIME_MEASURE_MULTIPLIERS = {
    "S": 1,
    "M": 60,
    "H": 60*60,
    "D": 60*60*24
}

MIN_REPEAT_EVERY_SECONDS = 60 * 60 # 1 hour in seconds, to prevent abuse of the reminder system
DONT_REPEAT_VALUE = -1

# REMINDERS

DATABASE_URL = "sqlite+aiosqlite:///data/ditto.db"
REMINDER_LIST_PAGE_SIZE = 10 # reminders shown per page of /reminders list
DEFAULT_EMBED_COLOR = 0x5865F2 # Discord blurple
EMBED_MAX_TOTAL_LENGTH = 6000 # Discord's limit on all the text in one embed
EMBED_MAX_FIELDS = 25
EMBED_BUILDER_TIMEOUT_SECONDS = 14 * 60 # an interaction can edit its reply for 15 minutes
MAX_VOTE_BUTTONS = 5 # one row of buttons under a reminder

# Embed colour names, mirrors the names Discord itself offers for embed colours.
EMBED_COLOR_NAMES = {
    "default": 0,
    "aqua": 0x1ABC9C, "dark_aqua": 0x11806A,
    "green": 0x2ECC71, "dark_green": 0x1F8B4C,
    "blue": 0x3498DB, "dark_blue": 0x206694,
    "purple": 0x9B59B6, "dark_purple": 0x71368A,
    "gold": 0xF1C40F, "dark_gold": 0xC27C0E,
    "orange": 0xE67E22, "dark_orange": 0xA84300,
    "red": 0xE74C3C, "dark_red": 0x992D22,
    "greyple": 0x95A5A6, "dark_greyple": 0x2C2F33,
    "light_greyple": 0x979C9F, "darker_greyple": 0x546E7A,
    "blurple": 0x5865F2, "greypon": 0x99AAB5,
}

# ERROR MESSAGES

INVALID_TIME_MEASURE = f"Invalid time measure. Use one of: {', '.join(TRANSLATE_TIME_MEASURE.keys())}"
REPEAT_TIME_TOO_SMALL = f"Time between reminders is too small. Minimum is {MIN_REPEAT_EVERY_SECONDS} seconds."
INVALID_WHEN = 'I could not understand that time. Use a duration like "30m", "2h" or "1d", an ISO date like "2026-03-01T18:30", or "tomorrow".'
INVALID_EMBED_COLOR = "I could not understand that colour. Use a name like blurple, red or dark_green, or a hex value like #5865F2."
INVALID_REPEAT = 'I could not understand that interval. Use a duration like "12h" or "1d".'
POSTPONE_IN_PAST = "That time has already passed. Postpone to a time in the future."
REMINDER_NOT_FOUND = "No reminder with that ID here. Use /reminders list to see the reminders on this server."
MISSING_REMINDER_CHANNEL = "I cannot find the channel this reminder posts to, so I cannot send it."
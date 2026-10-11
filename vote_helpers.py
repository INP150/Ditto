"""Vote buttons sent under reminders.

Reactions cannot start at zero, since the bot's own reaction always counts, so
reminders get buttons that show how many people picked each emoji instead.
"""

import re

import discord

from Services.Implementation.sql_vote_storage import SqlVoteStorage
from const import EMOJI_MAP, MAX_VOTE_BUTTONS

VOTE_CUSTOM_ID_PREFIX = "ditto:vote:"

# A custom server emoji as Discord writes it, e.g. <:name:123> or <a:name:123>.
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w{2,32}:\d{15,20}>")

votes = SqlVoteStorage()


def parse_vote_emojis(value: str | None) -> tuple[str | None, str | None]:
    """Parse a space or comma separated list of emojis into the stored form.

    Shortcodes from EMOJI_MAP, like :thumbsup:, are turned into the emoji.
    Returns None for a blank value, plus an error message when the value
    cannot be used.
    """
    tokens = [EMOJI_MAP.get(token, token) for token in re.split(r"[\s,]+", (value or "").strip()) if token]
    if not tokens:
        return None, None

    unique = list(dict.fromkeys(tokens))
    if len(unique) > MAX_VOTE_BUTTONS:
        return None, f"A reminder can have at most {MAX_VOTE_BUTTONS} vote buttons."
    for token in unique:
        # Unicode emojis contain no letters or digits, so this catches words and shortcodes.
        if not CUSTOM_EMOJI_RE.fullmatch(token) and re.search(r"[A-Za-z0-9:]", token):
            return None, f'"{token}" is not an emoji. Use emojis like 👍 👎, or custom server emojis.'
    return " ".join(unique), None


def split_vote_emojis(stored: str | None) -> list[str]:
    """The emojis of a reminder's vote buttons, in order."""
    return (stored or "").split()


class VoteButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ditto:vote:(?P<emoji>.+)"):
    """A button that counts votes for one emoji.

    Being a dynamic item, it keeps working on messages sent before a restart:
    everything it needs is in its custom ID and the database.
    """

    def __init__(self, emoji: str, count: int = 0, disabled: bool = False):
        super().__init__(
            discord.ui.Button(
                emoji=emoji,
                label=str(count),
                style=discord.ButtonStyle.secondary,
                custom_id=f"{VOTE_CUSTOM_ID_PREFIX}{emoji}",
                disabled=disabled,
            )
        )
        self.emoji = emoji

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]
    ) -> "VoteButton":
        """Rebuild the button from a click on a message the bot sent earlier."""
        return cls(match["emoji"])

    async def callback(self, interaction: discord.Interaction) -> None:
        """Record the vote and update the counts on the message."""
        counts = await votes.toggle_vote(interaction.message.id, interaction.user.id, self.emoji)
        emojis = emojis_on_message(interaction.message)
        await interaction.response.edit_message(view=build_vote_view(emojis, counts))


def emojis_on_message(message: discord.Message) -> list[str]:
    """The emojis of the vote buttons on a message, in order."""
    emojis = []
    for row in message.components:
        for component in getattr(row, "children", []):
            custom_id = getattr(component, "custom_id", None) or ""
            if custom_id.startswith(VOTE_CUSTOM_ID_PREFIX):
                emojis.append(custom_id.removeprefix(VOTE_CUSTOM_ID_PREFIX))
    return emojis


def build_vote_view(
    emojis: list[str], counts: dict[str, int] | None = None, disabled: bool = False
) -> discord.ui.View | None:
    """A row of vote buttons, or None when there are no emojis."""
    if not emojis:
        return None
    view = discord.ui.View(timeout=None)
    for emoji in emojis:
        view.add_item(VoteButton(emoji, (counts or {}).get(emoji, 0), disabled))
    return view

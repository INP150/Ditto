"""Reaction buttons sent under reminders.

Discord reactions cannot start at zero, since the bot's own reaction always
counts, so reminders get buttons that work like reactions instead: each starts
at 0, a person can pick several emojis, and clicking one again takes it back.
Once someone reacts, a small embed under the message lists who reacted with
which emoji and the total.
"""

import re

import discord

from Services.Implementation.sql_vote_storage import SqlVoteStorage
from const import EMOJI_MAP, MAX_VOTE_BUTTONS

VOTE_CUSTOM_ID_PREFIX = "ditto:vote:"

# A custom server emoji as Discord writes it, e.g. <:name:123> or <a:name:123>.
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w{2,32}:\d{15,20}>")

# Marks the embed that lists who reacted, so a click replaces it instead of
# adding another. Discord keeps an embed's URL but shows it only with a title,
# and this embed has none.
VOTERS_EMBED_URL = "https://ditto.invalid/reactions"
VOTERS_EMBED_COLOR = 0x2B2D31  # Discord's dark message background, to keep it quiet
MAX_NAMES_PER_EMOJI = 20
# Discord's limits on a message's embeds.
MAX_EMBEDS = 10
MAX_EMBEDS_TOTAL_LENGTH = 6000

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
    """A button that toggles one person's reaction with one emoji.

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
        """Record the reaction and update the counts and the list of who reacted."""
        message = interaction.message
        voters = await votes.toggle_vote(message.id, interaction.user.id, self.emoji)
        emojis = emojis_on_message(message)
        counts = {emoji: len(users) for emoji, users in voters.items()}
        await interaction.response.edit_message(
            embeds=embeds_with_voters(message, emojis, voters),
            view=build_vote_view(emojis, counts),
        )


def emojis_on_message(message: discord.Message) -> list[str]:
    """The emojis of the vote buttons on a message, in order."""
    emojis = []
    for row in message.components:
        for component in getattr(row, "children", []):
            custom_id = getattr(component, "custom_id", None) or ""
            if custom_id.startswith(VOTE_CUSTOM_ID_PREFIX):
                emojis.append(custom_id.removeprefix(VOTE_CUSTOM_ID_PREFIX))
    return emojis


def build_voters_embed(emojis: list[str], voters: dict[str, list[int]]) -> discord.Embed | None:
    """An embed listing who reacted with each emoji, or None when nobody has.

    Mentions in embeds do not ping, so people are shown by mention, which
    Discord displays as their name in the server.
    """
    lines = []
    for emoji in emojis:
        users = voters.get(emoji, [])
        if not users:
            continue
        names = ", ".join(f"<@{user}>" for user in users[:MAX_NAMES_PER_EMOJI])
        if len(users) > MAX_NAMES_PER_EMOJI:
            names += f" +{len(users) - MAX_NAMES_PER_EMOJI} more"
        lines.append(f"{emoji} **{len(users)}** · {names}")
    if not lines:
        return None

    total = sum(len(voters.get(emoji, [])) for emoji in emojis)
    people = len({user for emoji in emojis for user in voters.get(emoji, [])})
    footer = f"{total} reaction{'s' if total != 1 else ''}"
    if people != total:
        footer += f" from {people} {'person' if people == 1 else 'people'}"

    embed = discord.Embed(description="\n".join(lines), color=VOTERS_EMBED_COLOR, url=VOTERS_EMBED_URL)
    embed.set_footer(text=footer)
    return embed


def embeds_with_voters(
    message: discord.Message, emojis: list[str], voters: dict[str, list[int]]
) -> list[discord.Embed]:
    """The message's own embeds, followed by an up to date list of who reacted.

    Link previews are left out, since Discord makes those itself from the
    message text. The list is skipped when it would break Discord's limits.
    """
    embeds = [embed for embed in message.embeds if embed.type == "rich" and embed.url != VOTERS_EMBED_URL]
    summary = build_voters_embed(emojis, voters)
    if summary is not None and len(embeds) < MAX_EMBEDS:
        if sum(len(embed) for embed in embeds) + len(summary) <= MAX_EMBEDS_TOTAL_LENGTH:
            embeds.append(summary)
    return embeds


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

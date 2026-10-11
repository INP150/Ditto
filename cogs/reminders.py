"""Slash commands, a message context menu and the delivery loop for reminders.

Reminders belong to the server and channel they post in. Anyone can create one
in a channel they can post to; a reminder can be changed by the person who
created it, or by anyone allowed to manage messages in its channel.
"""

import json
import re
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

from Entities.reminder import Reminder
from Services.Implementation.reminder_dispatcher import ReminderDispatcher
from Services.Implementation.reminder_service import ReminderService
from Services.Implementation.sql_reminder_storage import SqlReminderStorage
from const import (
    DEFAULT_EMBED_COLOR,
    DONT_REPEAT_VALUE,
    EMBED_BUILDER_TIMEOUT_SECONDS,
    EMBED_MAX_FIELDS,
    INVALID_EMBED_COLOR,
    INVALID_REPEAT,
    INVALID_TIME_MEASURE,
    INVALID_WHEN,
    MIN_REPEAT_EVERY_SECONDS,
    POSTPONE_IN_PAST,
    REMINDER_LIST_PAGE_SIZE,
    REMINDER_NOT_FOUND,
    REPEAT_TIME_TOO_SMALL,
    TIME_MEASURE_MULTIPLIERS,
)
from embed_helpers import (
    build_reminder_content,
    copy_message_embed,
    embed_problem,
    is_embed_url,
    parse_embed_color,
    reminder_summary_text,
)
from message_helpers import gather_message_parts
from vote_helpers import VoteButton, build_vote_view, parse_vote_emojis, split_vote_emojis
from time_helpers import (
    format_duration,
    format_when,
    parse_duration_to_seconds,
    parse_when,
    utc_now,
)

TimeMeasure = Literal["S", "M", "H", "D"]
ListScope = Literal["channel", "server", "mine"]
ReminderChannel = discord.abc.Messageable

# Accepts a full message link or a bare message ID, so either works.
MESSAGE_LINK_RE = re.compile(r"(?:https://discord\.com/channels/(?:\d+|@me)/(\d+)/(\d+)|(\d{15,20}))$")

# How long the "Set reminder" button posted for a prefix command keeps working.
REPLY_BUTTON_TIMEOUT_SECONDS = 5 * 60


def describe_repeat(repeat_every_seconds: int) -> str:
    """Describe how often a reminder repeats."""
    if repeat_every_seconds <= 0:
        return "once"
    return f"every {format_duration(repeat_every_seconds)}"


def summarise(reminder: Reminder, limit: int = 60) -> str:
    """Short one line description of a reminder for listings."""
    text = reminder_summary_text(reminder).replace("\n", " ").strip()
    if len(text) > limit:
        text = text[:limit - 3] + "..."
    return text or "(empty message)"


def copy_message_text(message: discord.Message) -> str:
    """Collect the text of a message, including the text of any embeds on it."""
    return "\n".join(part for part in gather_message_parts(message) if part.strip()).strip()


def confirmation(reminder: Reminder) -> str:
    """Reply shown after a reminder is created."""
    return (
        f"Reminder #{reminder.id} set in <#{reminder.channel_id}> for "
        f"{format_when(reminder.next_reminder_at)} ({describe_repeat(reminder.repeat_every_seconds)})."
    )


def parse_repeat(value: str | None) -> tuple[int, str | None]:
    """Parse a repeat interval like "12h" or "1d" into seconds.

    Returns DONT_REPEAT_VALUE for a blank value, plus an error message when the
    value cannot be used.
    """
    value = (value or "").strip()
    if not value:
        return DONT_REPEAT_VALUE, None

    seconds = parse_duration_to_seconds(value)
    if seconds is None:
        return DONT_REPEAT_VALUE, INVALID_REPEAT
    if seconds < MIN_REPEAT_EVERY_SECONDS:
        return DONT_REPEAT_VALUE, REPEAT_TIME_TOO_SMALL
    return seconds, None


def guild_id_of(channel: ReminderChannel) -> int | None:
    """The server a channel is in, or None for DMs."""
    guild = getattr(channel, "guild", None)
    return guild.id if guild is not None else None


def check_can_post(channel: ReminderChannel, user: discord.abc.User) -> str | None:
    """Return an error when the user or the bot cannot post reminders to a channel."""
    guild = getattr(channel, "guild", None)
    if guild is None or not isinstance(user, discord.Member):
        return None

    if not channel.permissions_for(user).send_messages:
        return f"You cannot send messages in {channel.mention}, so you cannot set reminders there."

    bot_permissions = channel.permissions_for(guild.me)
    if not (bot_permissions.view_channel and bot_permissions.send_messages):
        return f"I cannot send messages in {channel.mention}, so the reminder would never arrive."
    return None


class SetReminderModal(discord.ui.Modal, title="Set reminder"):
    """Asks when and how often to repeat a message that was copied."""

    message = discord.ui.TextInput(
        label="Message",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
    )
    when = discord.ui.TextInput(
        label="First reminder",
        placeholder="e.g. 30m, 2h, 1d, tomorrow or 2026-03-01T18:30",
        max_length=40,
        required=True,
    )
    repeat = discord.ui.TextInput(
        label="Repeat every",
        placeholder="e.g. 60m, 12h, 1d; leave blank for a one-off reminder",
        max_length=40,
        required=False,
    )
    # Not named "title", which Modal uses for the dialog's own title.
    embed_title = discord.ui.TextInput(
        label="Embed title",
        placeholder="Leave blank to send as a plain message",
        max_length=256,
        required=False,
    )
    votes = discord.ui.TextInput(
        label="Vote buttons",
        placeholder="e.g. 👍 👎; leave blank for none",
        max_length=200,
        required=False,
    )

    def __init__(self, service: ReminderService, channel: ReminderChannel, creator_id: int, text: str = ""):
        super().__init__()
        self.service = service
        self.channel = channel
        self.creator_id = creator_id
        if text:
            self.message.default = text[:1000]
        self.when.default = "1h"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Create the reminder from the answers given."""
        first_at = parse_when(self.when.value)
        if first_at is None:
            await interaction.response.send_message(INVALID_WHEN, ephemeral=True)
            return

        repeat_seconds, error = parse_repeat(self.repeat.value)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        vote_emojis, error = parse_vote_emojis(self.votes.value)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        embed_title = (self.embed_title.value or "").strip()
        reminder = await self.service.create_reminder(
            channel_id=self.channel.id,
            creator_id=self.creator_id,
            guild_id=guild_id_of(self.channel),
            message=self.message.value,
            next_reminder_at=first_at,
            repeat_every_seconds=repeat_seconds,
            as_embed=bool(embed_title),
            embed_title=embed_title or None,
            embed_color=DEFAULT_EMBED_COLOR if embed_title else None,
            vote_emojis=vote_emojis,
        )
        await interaction.response.send_message(confirmation(reminder), ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        """Report a failure that escaped on_submit."""
        print(f"Set reminder modal failed: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("Something went wrong.", ephemeral=True)


class OpenReminderModalView(discord.ui.View):
    """A button that opens the reminder dialog.

    Prefix commands have no interaction to open a dialog from, so `!set-reminder`
    without a time replies with this button instead.
    """

    def __init__(self, service: ReminderService, channel: ReminderChannel, author_id: int, text: str):
        super().__init__(timeout=REPLY_BUTTON_TIMEOUT_SECONDS)
        self.service = service
        self.channel = channel
        self.author_id = author_id
        self.text = text
        self.reply: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only let the person who used the command press the button."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This button is not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Set reminder", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Open the dialog with the copied text filled in."""
        await interaction.response.send_modal(
            SetReminderModal(self.service, self.channel, self.author_id, self.text)
        )

    async def on_timeout(self) -> None:
        """Remove the button once it stops working."""
        if self.reply is not None:
            try:
                await self.reply.delete()
            except discord.HTTPException:
                pass


def starting_embed(message: discord.Message) -> tuple[str, discord.Embed]:
    """The text and embed the builder starts with when copying a message.

    The message's own embed is copied when it has one; otherwise its text
    becomes the embed description.
    """
    content, embed = copy_message_embed(message)
    if embed is not None:
        return content, embed
    return "", discord.Embed(description=copy_message_text(message)[:4000] or None)


def blank_to_none(value: str | None) -> str | None:
    """Strip a text input, treating an empty answer as no value."""
    value = (value or "").strip()
    return value or None


class EmbedTextModal(discord.ui.Modal, title="Edit embed text"):
    """Edits the title, description, colour and footer of the embed being built."""

    embed_title = discord.ui.TextInput(label="Title", max_length=256, required=False)
    description = discord.ui.TextInput(
        label="Description", style=discord.TextStyle.paragraph, max_length=4000, required=False
    )
    color = discord.ui.TextInput(
        label="Colour", placeholder="e.g. blurple, red or #5865F2", max_length=20, required=False
    )
    footer = discord.ui.TextInput(label="Footer", max_length=2048, required=False)
    content = discord.ui.TextInput(
        label="Message above the embed (mentions ping)",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=False,
    )

    def __init__(self, builder: "EmbedBuilderView"):
        super().__init__()
        self.builder = builder
        embed = builder.embed
        self.embed_title.default = embed.title
        self.description.default = embed.description
        self.color.default = f"#{embed.colour.value:06X}" if embed.colour is not None else None
        self.footer.default = embed.footer.text
        self.content.default = builder.content or None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Apply the new text to the embed."""
        color = blank_to_none(self.color.value)
        parsed_color = parse_embed_color(color) if color else None
        if color and parsed_color is None:
            await interaction.response.send_message(INVALID_EMBED_COLOR, ephemeral=True)
            return

        embed = self.builder.embed.copy()
        embed.title = blank_to_none(self.embed_title.value)
        embed.description = blank_to_none(self.description.value)
        embed.colour = parsed_color
        footer = blank_to_none(self.footer.value)
        if footer:
            embed.set_footer(text=footer, icon_url=embed.footer.icon_url)
        else:
            embed.remove_footer()
        await self.builder.apply(interaction, embed, (self.content.value or "").strip())


class EmbedDetailsModal(discord.ui.Modal, title="Edit embed author and images"):
    """Edits the author, title link and images of the embed being built."""

    author = discord.ui.TextInput(label="Author", max_length=256, required=False)
    url = discord.ui.TextInput(label="Title link", placeholder="https://...", required=False)
    image = discord.ui.TextInput(label="Image URL", placeholder="https://...", required=False)
    thumbnail = discord.ui.TextInput(label="Thumbnail URL", placeholder="https://...", required=False)

    def __init__(self, builder: "EmbedBuilderView"):
        super().__init__()
        self.builder = builder
        embed = builder.embed
        self.author.default = embed.author.name
        self.url.default = embed.url
        self.image.default = embed.image.url
        self.thumbnail.default = embed.thumbnail.url

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Apply the new author, link and images to the embed."""
        url = blank_to_none(self.url.value)
        image = blank_to_none(self.image.value)
        thumbnail = blank_to_none(self.thumbnail.value)
        if any(value and not is_embed_url(value) for value in (url, image, thumbnail)):
            await interaction.response.send_message(
                "Links and image URLs must start with https://.", ephemeral=True
            )
            return

        embed = self.builder.embed.copy()
        author = blank_to_none(self.author.value)
        if author:
            embed.set_author(name=author, url=embed.author.url, icon_url=embed.author.icon_url)
        else:
            embed.remove_author()
        embed.url = url
        embed.set_image(url=image)
        embed.set_thumbnail(url=thumbnail)
        await self.builder.apply(interaction, embed, self.builder.content)


class EmbedFieldModal(discord.ui.Modal, title="Add embed field"):
    """Adds a field to the end of the embed being built."""

    name = discord.ui.TextInput(label="Name", max_length=256)
    value = discord.ui.TextInput(label="Value", style=discord.TextStyle.paragraph, max_length=1024)
    inline = discord.ui.TextInput(
        label="Show next to other fields? (yes/no)", default="no", max_length=3, required=False
    )

    def __init__(self, builder: "EmbedBuilderView"):
        super().__init__()
        self.builder = builder

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Add the field to the embed."""
        embed = self.builder.embed.copy()
        embed.add_field(
            name=self.name.value,
            value=self.value.value,
            inline=(self.inline.value or "").strip().lower() in ("y", "yes"),
        )
        await self.builder.apply(interaction, embed, self.builder.content)


class EmbedScheduleModal(discord.ui.Modal, title="Schedule embed reminder"):
    """Asks when and how often to send the embed, then creates the reminder."""

    when = discord.ui.TextInput(
        label="First reminder",
        placeholder="e.g. 30m, 2h, 1d, tomorrow or 2026-03-01T18:30",
        default="1h",
        max_length=40,
    )
    repeat = discord.ui.TextInput(
        label="Repeat every",
        placeholder="e.g. 60m, 12h, 1d; leave blank for a one-off reminder",
        max_length=40,
        required=False,
    )
    votes = discord.ui.TextInput(
        label="Vote buttons",
        placeholder="e.g. 👍 👎; leave blank for none",
        max_length=200,
        required=False,
    )

    def __init__(self, builder: "EmbedBuilderView"):
        super().__init__()
        self.builder = builder

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Create the reminder and close the builder."""
        first_at = parse_when(self.when.value)
        if first_at is None:
            await interaction.response.send_message(INVALID_WHEN, ephemeral=True)
            return

        repeat_seconds, error = parse_repeat(self.repeat.value)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        vote_emojis, error = parse_vote_emojis(self.votes.value)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        reminder = await self.builder.create_reminder(first_at, repeat_seconds, vote_emojis)
        await self.builder.close(interaction, confirmation(reminder))


class EmbedBuilderView(discord.ui.View):
    """An ephemeral embed preview with buttons to edit it and schedule it.

    The preview is the embed exactly as the reminder will send it, so what the
    user sees here is what the channel gets.
    """

    def __init__(
        self,
        service: ReminderService,
        channel: ReminderChannel,
        author_id: int,
        embed: discord.Embed | None = None,
        content: str = "",
    ):
        super().__init__(timeout=EMBED_BUILDER_TIMEOUT_SECONDS)
        self.service = service
        self.channel = channel
        self.author_id = author_id
        self.embed = embed or discord.Embed(
            title="New reminder",
            description="Use the buttons below to edit this embed.",
            colour=discord.Colour(DEFAULT_EMBED_COLOR),
        )
        self.content = content
        self.interaction: discord.Interaction | None = None

    def header(self) -> str:
        """The text above the preview, explaining the builder and showing the message content."""
        lines = [f"**Embed builder**, posts in <#{self.channel.id}>. Press **Schedule** when it looks right."]
        if self.content:
            lines.append("Sent above the embed:")
            lines.extend(f"> {line}" for line in self.content.splitlines())
        return "\n".join(lines)[:2000]

    def message_kwargs(self) -> dict:
        """The preview message, with buttons enabled to match the embed."""
        self.add_field.disabled = len(self.embed.fields) >= EMBED_MAX_FIELDS
        self.remove_field.disabled = not self.embed.fields
        return {
            "content": self.header(),
            "embed": self.embed,
            "view": self,
            # The preview shows the message content without pinging anyone.
            "allowed_mentions": discord.AllowedMentions.none(),
        }

    async def open(self, interaction: discord.Interaction) -> None:
        """Post the builder as a reply only the user can see."""
        problem = embed_problem(self.embed)
        if problem is not None:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        self.interaction = interaction
        await interaction.response.send_message(**self.message_kwargs(), ephemeral=True)

    async def apply(self, interaction: discord.Interaction, embed: discord.Embed, content: str) -> None:
        """Replace the embed when Discord would accept it, and refresh the preview."""
        problem = embed_problem(embed)
        if problem is not None:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        self.embed = embed
        self.content = content
        await interaction.response.edit_message(**self.message_kwargs())

    async def create_reminder(self, first_at, repeat_seconds: int, vote_emojis: str | None) -> Reminder:
        """Store the embed as a reminder in the builder's channel."""
        return await self.service.create_reminder(
            channel_id=self.channel.id,
            creator_id=self.author_id,
            guild_id=guild_id_of(self.channel),
            message=self.content,
            next_reminder_at=first_at,
            repeat_every_seconds=repeat_seconds,
            as_embed=True,
            embed_title=self.embed.title,
            embed_color=self.embed.colour.value if self.embed.colour is not None else None,
            embed_footer=self.embed.footer.text,
            embed_json=json.dumps(self.embed.to_dict()),
            vote_emojis=vote_emojis,
        )

    async def close(self, interaction: discord.Interaction, text: str) -> None:
        """Replace the buttons with a closing message, keeping the final embed."""
        self.stop()
        await interaction.response.edit_message(content=text, embed=self.embed, view=None)

    @discord.ui.button(label="Text", style=discord.ButtonStyle.primary)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Edit the title, description, colour, footer and message content."""
        await interaction.response.send_modal(EmbedTextModal(self))

    @discord.ui.button(label="Author & images", style=discord.ButtonStyle.secondary)
    async def edit_details(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Edit the author, title link, image and thumbnail."""
        await interaction.response.send_modal(EmbedDetailsModal(self))

    @discord.ui.button(label="Add field", style=discord.ButtonStyle.secondary)
    async def add_field(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Add a field to the end of the embed."""
        await interaction.response.send_modal(EmbedFieldModal(self))

    @discord.ui.button(label="Remove last field", style=discord.ButtonStyle.secondary)
    async def remove_field(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Remove the last field of the embed."""
        embed = self.embed.copy()
        embed.remove_field(len(embed.fields) - 1)
        await self.apply(interaction, embed, self.content)

    @discord.ui.button(label="Schedule", style=discord.ButtonStyle.success, row=1)
    async def schedule(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Ask when to send the embed."""
        await interaction.response.send_modal(EmbedScheduleModal(self))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Close the builder without creating a reminder."""
        await self.close(interaction, "Embed builder closed, no reminder was created.")

    async def on_timeout(self) -> None:
        """Remove the buttons once they stop working."""
        if self.interaction is not None:
            try:
                await self.interaction.edit_original_response(view=None)
            except discord.HTTPException:
                pass


class Reminders(commands.Cog):
    """Creates, lists and manages reminders, and sends the ones that are due."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = ReminderService(SqlReminderStorage())
        self.dispatcher = ReminderDispatcher(bot, self.service)

    def cog_load(self) -> None:
        """Start the delivery loop once the cog is loaded."""
        # Vote buttons on reminders sent before a restart keep working through this.
        self.bot.add_dynamic_items(VoteButton)
        self.send_reminders.start()

    def cog_unload(self) -> None:
        """Stop the delivery loop when the cog is unloaded."""
        self.bot.remove_dynamic_items(VoteButton)
        self.send_reminders.cancel()

    @tasks.loop(minutes=1)
    async def send_reminders(self) -> None:
        """Send everything that has come due since the last pass."""
        await self.dispatcher.dispatch_due()

    @send_reminders.before_loop
    async def wait_before_sending(self) -> None:
        """Hold off the first pass until the bot is connected, then tie old reminders to their server."""
        await self.bot.wait_until_ready()
        updated = await self.service.fill_missing_guild_ids(
            lambda channel_id: guild_id_of(self.bot.get_channel(channel_id))
        )
        if updated:
            print(f"Linked {updated} existing reminder(s) to their server.")

    # Copy a message into a reminder ------------------------------------

    @commands.hybrid_command(name="set-reminder", description="Turn a message into a reminder")
    @app_commands.describe(
        when='When the first reminder fires, e.g. "30m", "2h", "tomorrow"; leave out to open a dialog',
        repeat='Repeat every e.g. "12h" or "1d", leave out for a one-off reminder',
        message="Message link or ID to copy, when you are not replying to one",
    )
    async def set_reminder(
        self,
        ctx: commands.Context,
        when: str | None = None,
        repeat: str | None = None,
        message: str | None = None,
    ) -> None:
        """Copy a message into a reminder in this channel.

        Reply to a message with `!set-reminder 1d 1d` to create it right away, or
        with `!set-reminder` alone to get a button that opens the dialog. Discord
        does not pass the replied-to message into a slash command, so the slash
        form takes a message link or ID instead, and the "Set reminder" message
        context menu covers the rest.
        """
        source = await self.resolve_source(ctx, message)
        if isinstance(source, str):
            await ctx.send(source, ephemeral=True)
            return

        error = check_can_post(ctx.channel, ctx.author)
        if error is not None:
            await ctx.send(error, ephemeral=True)
            return

        copied = copy_message_text(source) if source is not None else ""

        if when is None:
            if ctx.interaction is not None:
                await ctx.interaction.response.send_modal(
                    SetReminderModal(self.service, ctx.channel, ctx.author.id, copied)
                )
                return
            view = OpenReminderModalView(self.service, ctx.channel, ctx.author.id, copied)
            view.reply = await ctx.reply("Open the dialog to set the reminder:", view=view)
            return

        if not copied:
            await ctx.send(
                "Reply to a message, or pass a message link, to copy its text into the reminder.",
                ephemeral=True,
            )
            return

        first_at = parse_when(when)
        if first_at is None:
            await ctx.send(INVALID_WHEN, ephemeral=True)
            return

        repeat_seconds, error = parse_repeat(repeat)
        if error is not None:
            await ctx.send(error, ephemeral=True)
            return

        reminder = await self.service.create_reminder(
            channel_id=ctx.channel.id,
            creator_id=ctx.author.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            message=copied[:2000],
            next_reminder_at=first_at,
            repeat_every_seconds=repeat_seconds,
        )
        await ctx.send(confirmation(reminder), ephemeral=True)

    async def resolve_source(
        self, ctx: commands.Context, reference: str | None
    ) -> discord.Message | str | None:
        """Find the message to copy, returning an error string when it fails."""
        if reference is not None:
            return await self.fetch_linked_message(ctx.channel, reference)

        if ctx.message.reference is not None:
            try:
                return await ctx.message.reference.resolve()
            except discord.HTTPException:
                return "I could not fetch the message you are replying to."
        return None

    async def fetch_linked_message(
        self, current: ReminderChannel, reference: str
    ) -> discord.Message | str:
        """Fetch a message from a link or ID, returning an error string when it fails."""
        channel_id, message_id = parse_message_reference(reference)
        if not message_id:
            return "That is not a message link or ID."
        try:
            channel = (
                current
                if channel_id is None or channel_id == current.id
                else self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            )
            return await channel.fetch_message(message_id)
        except (discord.HTTPException, AttributeError):
            return "I could not fetch that message."

    # Command group -----------------------------------------------------

    reminders_group = app_commands.Group(name="reminders", description="Manage reminders")

    async def reminder_id_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        """Suggest the reminders here that the user may change."""
        current = current.strip().lower()
        choices = []
        for reminder in await self.reminders_here(interaction):
            if self.management_error(interaction, reminder) is not None:
                continue
            label = f"#{reminder.id} · {summarise(reminder, 80)}"
            if current and current not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label[:100], value=reminder.id))
            if len(choices) == 25:
                break
        return choices

    @reminders_group.command(name="new", description="Create a reminder")
    @app_commands.describe(
        when='When the first reminder fires, e.g. "30m", "2h", "1d", "tomorrow" or "2026-03-01T18:30"',
        message="The text to send",
        repeat_every="Repeat every N time measures, blank for a one-off reminder",
        time_measure="Unit for repeat_every",
        channel="Channel to post in, defaults to this one",
        title="Embed title, sends the reminder as an embed",
        color="Embed colour, e.g. blurple, red or #5865F2",
        footer="Embed footer text",
        votes="Vote buttons under the reminder, e.g. 👍 👎",
    )
    async def new(
        self,
        interaction: discord.Interaction,
        when: str,
        message: str,
        repeat_every: int | None = None,
        time_measure: TimeMeasure = "H",
        channel: discord.TextChannel | discord.Thread | None = None,
        title: str | None = None,
        color: str | None = None,
        footer: str | None = None,
        votes: str | None = None,
    ) -> None:
        """Create a reminder in this channel or another channel of this server."""
        target = channel or interaction.channel
        error = check_can_post(target, interaction.user)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        first_at = parse_when(when)
        if first_at is None:
            await interaction.response.send_message(INVALID_WHEN, ephemeral=True)
            return

        repeat_seconds, error = self.resolve_repeat(repeat_every, time_measure)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        parsed_color = parse_embed_color(color) if color else None
        if color and parsed_color is None:
            await interaction.response.send_message(INVALID_EMBED_COLOR, ephemeral=True)
            return

        vote_emojis, error = parse_vote_emojis(votes)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        as_embed = bool(title) or parsed_color is not None or bool(footer)
        reminder = await self.service.create_reminder(
            channel_id=target.id,
            creator_id=interaction.user.id,
            guild_id=interaction.guild_id,
            message=message,
            next_reminder_at=first_at,
            repeat_every_seconds=repeat_seconds,
            as_embed=as_embed,
            embed_title=title,
            embed_color=parsed_color if as_embed else None,
            embed_footer=footer,
            vote_emojis=vote_emojis,
        )
        await interaction.response.send_message(confirmation(reminder), ephemeral=True)

    @reminders_group.command(name="list", description="List reminders in this channel or server")
    @app_commands.describe(scope="channel: this channel, server: every channel you can see, mine: yours on this server")
    async def list_reminders(self, interaction: discord.Interaction, scope: ListScope = "channel") -> None:
        """List the reminders in this channel, this server, or the user's own."""
        if interaction.guild is None or scope == "channel":
            reminders = await self.service.find_reminders(channel_id=interaction.channel_id)
            heading = "Reminders in this channel"
        elif scope == "server":
            reminders = await self.service.find_reminders(guild_id=interaction.guild_id)
            heading = f"Reminders on {interaction.guild.name}"
        else:
            reminders = await self.service.find_reminders(
                guild_id=interaction.guild_id, creator_id=interaction.user.id
            )
            heading = "Your reminders on this server"

        reminders = [r for r in reminders if self.can_see(interaction, r)]
        if not reminders:
            await interaction.response.send_message(
                "No reminders here yet. Create one with /reminders new.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=heading,
            colour=discord.Colour(DEFAULT_EMBED_COLOR),
            timestamp=utc_now(),
        )
        for reminder in reminders[:REMINDER_LIST_PAGE_SIZE]:
            status = "active" if reminder.is_active else "paused"
            details = [describe_repeat(reminder.repeat_every_seconds)]
            if scope != "channel":
                details.append(f"in <#{reminder.channel_id}>")
            if reminder.creator_id:
                details.append(f"by <@{reminder.creator_id}>")
            embed.add_field(
                name=f"#{reminder.id} · {status} · next {format_when(reminder.next_reminder_at)}",
                value=f"{summarise(reminder)}\n{' · '.join(details)}",
                inline=False,
            )
        if len(reminders) > REMINDER_LIST_PAGE_SIZE:
            embed.set_footer(text=f"{len(reminders) - REMINDER_LIST_PAGE_SIZE} more not shown")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reminders_group.command(name="pause", description="Stop a reminder until you resume it")
    @app_commands.describe(reminder_id="The reminder, from /reminders list")
    @app_commands.autocomplete(reminder_id=reminder_id_autocomplete)
    async def pause(self, interaction: discord.Interaction, reminder_id: int) -> None:
        """Pause a reminder."""
        reminder, error = await self.get_manageable_reminder(interaction, reminder_id)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        await self.service.pause_reminder(reminder.id)
        await interaction.response.send_message(
            f"Reminder #{reminder.id} paused. Use /reminders resume or /reminders postpone to start it again.",
            ephemeral=True,
        )

    @reminders_group.command(name="resume", description="Resume a paused reminder")
    @app_commands.describe(reminder_id="The reminder, from /reminders list")
    @app_commands.autocomplete(reminder_id=reminder_id_autocomplete)
    async def resume(self, interaction: discord.Interaction, reminder_id: int) -> None:
        """Resume a paused reminder on its usual schedule."""
        reminder, error = await self.get_manageable_reminder(interaction, reminder_id)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        resumed = await self.service.resume_reminder(reminder.id)
        await interaction.response.send_message(
            f"Reminder #{resumed.id} resumes {format_when(resumed.next_reminder_at)}.",
            ephemeral=True,
        )

    @reminders_group.command(name="postpone", description="Move a reminder to a later time")
    @app_commands.describe(
        reminder_id="The reminder, from /reminders list",
        until='When it should fire next, e.g. "14d", "6h" or "2026-12-01"; it repeats as usual from then',
    )
    @app_commands.autocomplete(reminder_id=reminder_id_autocomplete)
    async def postpone(self, interaction: discord.Interaction, reminder_id: int, until: str) -> None:
        """Postpone a reminder, which then carries on as before from the new time."""
        reminder, error = await self.get_manageable_reminder(interaction, reminder_id)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        target = parse_when(until)
        if target is None:
            await interaction.response.send_message(INVALID_WHEN, ephemeral=True)
            return
        if target <= utc_now():
            await interaction.response.send_message(POSTPONE_IN_PAST, ephemeral=True)
            return

        postponed = await self.service.postpone_reminder(reminder.id, target)
        await interaction.response.send_message(
            f"Reminder #{postponed.id} postponed to {format_when(target)}, "
            f"then {describe_repeat(postponed.repeat_every_seconds)}.",
            ephemeral=True,
        )

    @reminders_group.command(name="delete", description="Delete a reminder")
    @app_commands.describe(reminder_id="The reminder, from /reminders list")
    @app_commands.autocomplete(reminder_id=reminder_id_autocomplete)
    async def delete(self, interaction: discord.Interaction, reminder_id: int) -> None:
        """Delete a reminder."""
        reminder, error = await self.get_manageable_reminder(interaction, reminder_id)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        await self.service.delete_reminder(reminder.id)
        await interaction.response.send_message(f"Reminder #{reminder.id} deleted.", ephemeral=True)

    @reminders_group.command(name="preview", description="Show a reminder as it will look")
    @app_commands.describe(reminder_id="The reminder, from /reminders list")
    @app_commands.autocomplete(reminder_id=reminder_id_autocomplete)
    async def preview(self, interaction: discord.Interaction, reminder_id: int) -> None:
        """Show a reminder without changing when it next fires."""
        reminder, error = await self.get_manageable_reminder(interaction, reminder_id)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        await interaction.response.send_message(
            **build_reminder_content(reminder),
            view=build_vote_view(split_vote_emojis(reminder.vote_emojis), disabled=True),
            ephemeral=True,
        )

    @reminders_group.command(name="votes", description="Set or remove the vote buttons of a reminder")
    @app_commands.describe(
        reminder_id="The reminder, from /reminders list",
        emojis="Vote buttons, e.g. 👍 👎; leave out to remove them",
    )
    @app_commands.autocomplete(reminder_id=reminder_id_autocomplete)
    async def votes(self, interaction: discord.Interaction, reminder_id: int, emojis: str | None = None) -> None:
        """Change the vote buttons sent with a reminder from now on."""
        reminder, error = await self.get_manageable_reminder(interaction, reminder_id)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        vote_emojis, error = parse_vote_emojis(emojis)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        reminder.vote_emojis = vote_emojis
        await self.service.update_reminder(reminder)
        if vote_emojis:
            text = f"Reminder #{reminder.id} will be sent with the vote buttons {vote_emojis}."
        else:
            text = f"Reminder #{reminder.id} will be sent without vote buttons."
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="embed", description="Build an embed and schedule it as a reminder")
    @app_commands.describe(
        channel="Channel to post in, defaults to this one",
        message="Message link or ID whose embed to start from, e.g. a forwarded embed",
    )
    async def embed(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | discord.Thread | None = None,
        message: str | None = None,
    ) -> None:
        """Open the embed builder, optionally starting from an existing message."""
        target = channel or interaction.channel
        error = check_can_post(target, interaction.user)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        content, start_from = "", None
        if message is not None:
            source = await self.fetch_linked_message(interaction.channel, message)
            if isinstance(source, str):
                await interaction.response.send_message(source, ephemeral=True)
                return
            content, start_from = starting_embed(source)

        await EmbedBuilderView(self.service, target, interaction.user.id, start_from, content).open(interaction)

    # Helpers -----------------------------------------------------------

    def resolve_repeat(
        self, repeat_every: int | None, time_measure: str
    ) -> tuple[int, str | None]:
        """Convert a repeat interval and its unit into a number of seconds.

        Returns DONT_REPEAT_VALUE when no interval was given, plus an error
        message when the arguments do not make sense together.
        """
        if repeat_every is None:
            return DONT_REPEAT_VALUE, None

        if time_measure not in TIME_MEASURE_MULTIPLIERS:
            return DONT_REPEAT_VALUE, INVALID_TIME_MEASURE

        seconds = repeat_every * TIME_MEASURE_MULTIPLIERS[time_measure]
        if seconds < MIN_REPEAT_EVERY_SECONDS:
            return DONT_REPEAT_VALUE, REPEAT_TIME_TOO_SMALL
        return seconds, None

    async def reminders_here(self, interaction: discord.Interaction) -> list[Reminder]:
        """The reminders of the current server, or of the current DM."""
        if interaction.guild_id is not None:
            return await self.service.find_reminders(guild_id=interaction.guild_id)
        return await self.service.find_reminders(channel_id=interaction.channel_id)

    def reminder_channel(self, interaction: discord.Interaction, reminder: Reminder):
        """The channel or thread a reminder posts in, when it is still cached."""
        if interaction.guild is None:
            return None
        return interaction.guild.get_channel_or_thread(int(reminder.channel_id))

    def belongs_here(self, interaction: discord.Interaction, reminder: Reminder) -> bool:
        """Whether a reminder is on the server, or in the DM, the command came from."""
        if interaction.guild_id is not None:
            return reminder.guild_id == interaction.guild_id
        return reminder.channel_id == str(interaction.channel_id)

    def can_see(self, interaction: discord.Interaction, reminder: Reminder) -> bool:
        """Whether the user may see a reminder, so listings do not leak private channels."""
        if not self.belongs_here(interaction, reminder):
            return False
        if reminder.creator_id == interaction.user.id or interaction.guild is None:
            return True

        channel = self.reminder_channel(interaction, reminder)
        if channel is None:
            return interaction.user.guild_permissions.manage_guild
        return channel.permissions_for(interaction.user).view_channel

    def management_error(self, interaction: discord.Interaction, reminder: Reminder) -> str | None:
        """Return why the user may not change a reminder, or None when they may."""
        if not self.belongs_here(interaction, reminder):
            # Reminders on other servers are reported as missing, not as forbidden.
            return REMINDER_NOT_FOUND
        if reminder.creator_id == interaction.user.id or interaction.guild is None:
            return None

        channel = self.reminder_channel(interaction, reminder)
        if channel is None:
            allowed = interaction.user.guild_permissions.manage_guild
        else:
            allowed = channel.permissions_for(interaction.user).manage_messages
        if allowed:
            return None
        return (
            f"Only the person who created reminder #{reminder.id}, or someone who can "
            f"manage messages in <#{reminder.channel_id}>, can change it."
        )

    async def get_manageable_reminder(
        self, interaction: discord.Interaction, reminder_id: int
    ) -> tuple[Reminder | None, str | None]:
        """Load a reminder that the calling user is allowed to manage."""
        reminder = await self.service.get_reminder(reminder_id)
        if reminder is None:
            return None, REMINDER_NOT_FOUND
        error = self.management_error(interaction, reminder)
        if error is not None:
            return None, error
        return reminder, None


def parse_message_reference(reference: str) -> tuple[int | None, int]:
    """Pull the channel and message IDs out of a message link or bare ID.

    Returns the channel ID, which is None for a bare message ID, and the message
    ID, which is 0 when the reference cannot be parsed.
    """
    match = MESSAGE_LINK_RE.search(reference.strip())
    if match is None:
        return None, 0

    channel, message, bare = match.groups()
    if bare is not None:
        return None, int(bare)
    return int(channel), int(message)


def build_set_reminder_menu(service: ReminderService) -> app_commands.ContextMenu:
    """Build the message context menu that copies a message into a new reminder.

    Context menus cannot be defined inside a class, so this is a factory closing
    over the reminder service instead.
    """

    @app_commands.context_menu(name="Set reminder")
    async def set_reminder(interaction: discord.Interaction, message: discord.Message) -> None:
        """Open the reminder dialog with the chosen message's text filled in."""
        copied = copy_message_text(message)
        if not copied:
            await interaction.response.send_message(
                "That message has no text to copy.", ephemeral=True
            )
            return

        error = check_can_post(interaction.channel, interaction.user)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        await interaction.response.send_modal(
            SetReminderModal(service, interaction.channel, interaction.user.id, copied)
        )

    return set_reminder


def build_embed_reminder_menu(service: ReminderService) -> app_commands.ContextMenu:
    """Build the message context menu that opens the embed builder from a message."""

    @app_commands.context_menu(name="Build embed reminder")
    async def build_embed_reminder(interaction: discord.Interaction, message: discord.Message) -> None:
        """Open the embed builder with the chosen message's embed, or its text, filled in."""
        error = check_can_post(interaction.channel, interaction.user)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        content, embed = starting_embed(message)
        await EmbedBuilderView(service, interaction.channel, interaction.user.id, embed, content).open(interaction)

    return build_embed_reminder


async def setup(bot: commands.Bot) -> None:
    """Add the reminder cog and its context menu to the bot."""
    cog = Reminders(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(build_set_reminder_menu(cog.service))
    bot.tree.add_command(build_embed_reminder_menu(cog.service))

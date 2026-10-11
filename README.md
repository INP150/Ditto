# Ditto
Universal discord bot

## Current features
- Reactions to chat messages
  - messages containing defined text will get defined reactions on them
- Reminders stored in a SQLite database
  - created manually, or by copying the text of an existing message
  - one-off or repeating, with a configurable interval
  - can be paused, resumed or postponed to a later date
  - sent as a plain message or as an embed with a title, colour and footer
  - full embeds (author, images, fields) can be built with an embed builder
  - optional vote buttons (e.g. 👍 👎) under each reminder, counting from 0

## Commands
- /ping
  - shows current ping
- /version (TODO)
  - shows latest commit hash for currently running bot
- /reminders new
  - creates a reminder in the current channel, or in `channel` on the same server
  - `when` accepts a duration ("30m", "2h", "1d"), "today"/"tomorrow", a Unix
    timestamp or an ISO date ("2026-03-01T18:30")
  - `repeat_every` with `time_measure` (S/M/H/D) makes it repeat, leaving it out
    sends it once
  - `title`, `color` and `footer` send the reminder as an embed
  - `votes` adds vote buttons, e.g. `👍 👎` (up to 5, custom server emojis work)
- /set-reminder, !set-reminder
  - copies the text of a message (including its embeds) into a new reminder in
    the current channel
  - reply to a message with `!set-reminder 1d 1d` (first reminder, then repeat
    every) to create it straight away, or with `!set-reminder` alone to get a
    button that opens the reminder dialog
  - Discord does not expose the replied-to message to slash commands, so either
    pass a link/ID to `/set-reminder`, or right-click the message and use
    **Apps → Set reminder**
- /embed
  - opens an embed builder only you can see, with a live preview of the embed
  - buttons edit the text (title, description, colour, footer and a message
    sent above the embed, where mentions ping), the author, title link and
    images, and add or remove fields; **Schedule** asks when to send it
  - `channel` picks where it posts, `message` takes a link/ID of a message
    (e.g. a forwarded embed) to start from its embed
  - or right-click a message and use **Apps → Build embed reminder**
- /reminders list
  - lists reminders in this channel (default), on the whole server, or only
    yours on this server, with their ID, status and next time
  - only reminders in channels you can see are shown
- /reminders pause, /reminders resume
  - temporarily stops a reminder, then starts it again on its usual schedule,
    skipping the times missed while paused
- /reminders postpone
  - moves a reminder's next time to a later date, after which it repeats as
    before (a paused reminder is resumed)
- /reminders preview
  - shows how a reminder will look, without affecting its schedule
- /reminders votes
  - sets or removes the vote buttons of an existing reminder; the dialogs of
    /set-reminder and /embed have a **Vote buttons** box too
  - every message a reminder sends starts at 0; each person has one vote per
    message, clicking the same button again takes it back, another moves it
- /reminders delete
  - deletes a reminder

### Who can manage a reminder
Reminders belong to the server and channel they post in, and the reminder ID
options suggest the reminders on the current server. A reminder can be paused,
resumed, postponed, previewed or deleted by the person who created it, or by
anyone with the **Manage Messages** permission in its channel.

## Database
Reminders are kept in SQLite at `data/ditto.db`, created on first start. Point
`DATABASE_URL` in `.env` at another database to move them elsewhere, for example
`postgresql+asyncpg://user:password@host/ditto`.

## Planned features

# How to Install
- Clone Ditto repository
```bash
git clone <repository>
```
- Create .env file containing bots 'DISCORD_TOKEN'
- Download packages needed (needs Python 3.10 or newer)
```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```
- run the bot
```bash
.venv/bin/python main.py
```
```
```

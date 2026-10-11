def gather_message_parts(msg):
    """Gather all relevant text parts from the message content and embeds for reaction checking."""
    parts = [msg.content or ""]
    embeds = list(msg.embeds)
    # A forwarded message has no content or embeds of its own; they live in its snapshots.
    for snapshot in getattr(msg, "message_snapshots", None) or []:
        parts.append(snapshot.content or "")
        embeds.extend(snapshot.embeds)
    for embed in embeds:
        parts.extend(get_title_parts(embed))
        parts.extend(get_description_parts(embed))
        parts.extend(get_footer_parts(embed))
        parts.extend(get_author_parts(embed))
        parts.extend(get_fields_parts(embed))
    return parts


def get_title_parts(embed):
    """Helper to extract title from an embed."""
    parts = []
    if getattr(embed, "title", None):
        parts.append(embed.title)
    return parts


def get_description_parts(embed):
    """Helper to extract description from an embed."""
    parts = []
    if getattr(embed, "description", None):
        parts.append(embed.description)
    return parts


def get_footer_parts(embed):
    """Helper to extract footer text from an embed."""
    parts = []
    footer = getattr(embed, "footer", None)
    if footer and getattr(footer, "text", None):
        parts.append(footer.text)
    return parts


def get_author_parts(embed):
    """Helper to extract author name from an embed."""
    parts = []
    author = getattr(embed, "author", None)
    if author and getattr(author, "name", None):
        parts.append(author.name)
    return parts


def get_fields_parts(embed):
    """Helper to extract field names and values from an embed."""
    parts = []
    for f in getattr(embed, "fields", []) or []:
        if getattr(f, "name", None):
            parts.append(f.name)
        if getattr(f, "value", None):
            parts.append(f.value)
    return parts
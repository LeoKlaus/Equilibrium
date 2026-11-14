from enum import StrEnum


class WebhookBodyFormat(StrEnum):
    """How a webhook's body is written, which decides how placeholder values
    are inserted: into JSON they're escaped, into text they're kept as they are."""

    JSON = "json"
    TEXT = "text"

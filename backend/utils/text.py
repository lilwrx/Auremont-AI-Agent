"""Vietnamese text normalisation helpers for keyword matching."""

import re
import unicodedata


def strip_diacritics(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics: "Còn căn trống" -> "con can trong".

    Sales staff typing on a phone in front of a customer routinely drop every accent.
    Every keyword match in the AI flow (detecting inventory questions, screening for
    price/commitment risk) must go through this, otherwise an unaccented sentence
    silently slips past all the rules — most dangerously past RiskCheck, leaving a
    price answer without its mandatory HITL card.

    NFD does not decompose `đ` into a base letter plus a combining mark, so it has to
    be replaced by hand first.
    """
    lowered = text.lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


_EXTERNAL_FIELD_MAX_CHARS = 120
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_external_field(value: str) -> str:
    """Flatten a short free-text value from an external API before it reaches a prompt.

    Uploaded documents get `ingestion_service.sanitize_and_scan`, which blocks the whole
    file on a hit. That is the wrong trade here: one odd inventory row must not fail a
    Sale's entire stock lookup. So this neutralises rather than rejects — injected wording
    survives as inert words on a single line, unable to pose as prompt structure.
    """
    flattened = _CONTROL_CHARS.sub(" ", value)
    return " ".join(flattened.split())[:_EXTERNAL_FIELD_MAX_CHARS]


_MD_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3})(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_MD_BULLET = re.compile(r"^[ \t]*[*+-][ \t]+", re.MULTILINE)
_MD_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]*", re.MULTILINE)
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MD_CODE_FENCE = re.compile(r"^[ \t]*```.*$", re.MULTILINE)
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
_JOINED_BULLET = re.compile(r"(?<=[.!?])\s*-\s+(?=\S)")


def strip_markdown(text: str) -> str:
    """Strip Markdown syntax from an LLM answer while preserving the text content.

    The chat window renders answers as plain text (`<p>{content}</p>` in
    frontend/src/routes/sale/ChatWindow.tsx), so any Markdown character the model
    returns shows up literally: "*   **Tiện ích:**" instead of a clean bullet line.

    The prompt already instructs the model to write plain text; this function is the
    last line of defense for the times the model slips into Markdown out of habit.
    Leading "- " is deliberately kept, since that reads as a plain-text bullet rather
    than syntax that needs stripping.
    """
    if not text:
        return text

    cleaned = _MD_CODE_FENCE.sub("", text)
    cleaned = _MD_LINK.sub(r"\1", cleaned)
    cleaned = _MD_HEADING.sub("", cleaned)
    for _ in range(3):
        stripped = _MD_EMPHASIS.sub(r"\2", cleaned)
        if stripped == cleaned:
            break
        cleaned = stripped
    cleaned = _MD_BULLET.sub("- ", cleaned)
    cleaned = _JOINED_BULLET.sub("\n- ", cleaned)
    cleaned = _EXCESS_BLANK_LINES.sub("\n\n", cleaned)

    return cleaned.strip()

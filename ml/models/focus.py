"""Drop explicit instructions from the optional free-text focus field."""
import re
import unicodedata

FOCUS_POLICY_VERSION = "lab5-focus-v1"
ROLE_MARKERS = re.compile(
    r"<\|/?(?:system|assistant|user|im_start|im_end)[^\n]{0,24}\|>"
    r"|\[/?(?:inst|system)\]"
    r"|(?:^|[\s\]}])(?:system|assistant|developer|система)\s*:"
    r"|системное\s+сообщение\s*:",
    re.IGNORECASE,
)
COMMANDS = re.compile(
    r"\b(?:игнорируй(?:те)?|забудь(?:те)?|ignore|disregard|forget)\s+"
    r"(?:(?:все|any|all|the|предыдущие|предшествующие|previous|prior|системные)\s+){0,5}"
    r"(?:инструкци\w*|правил\w*|указани\w*|instructions?|rules?|prompts?)\b",
    re.IGNORECASE,
)


def safe_focus(value: str | None) -> str:
    if not value:
        return ""
    # Format characters can hide a role marker or split a command word.
    normalized = unicodedata.normalize("NFKC", value[:1500])
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Cf")
    if ROLE_MARKERS.search(normalized) or COMMANDS.search(normalized):
        return ""
    return value[:1500]

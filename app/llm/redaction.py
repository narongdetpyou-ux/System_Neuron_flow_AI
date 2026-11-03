"""Mask personal data before any text reaches an AI provider (roadmap 7.1, gap G5).

Flow for one AI call:
1. the agent calls :func:`mask` on the untrusted text;
2. it gets a :class:`MaskedText`: the text with placeholders, and how many of each kind were masked;
3. the gateway (``structured_answer``) accepts only a ``MaskedText``, so no AI call can skip this step.

What is masked (Thai and English), in this order:

* **e-mail addresses** → ``[EMAIL]``;
* **long numbers**: a run of digits (Thai digits too) with single spaces, dashes or dots between the groups,
  and an optional ``+`` or area code in brackets. Runs of 9 or more digits are masked by what they look
  like, the first match winning:
  - 13 digits with a valid Thai ID check digit → ``[THAI_ID]``;
  - 13–19 digits passing the Luhn check (card-like) → ``[CARD]``;
  - a phone number → ``[PHONE]``: Thai numbers (0 + 8–9 digits, the second digit 2–9), +66/0066 + 8–9
    digits, or another number written with ``+`` (8–15 digits);
  - anything else (bank account, order or policy numbers) → ``[NUMBER]``;
* **names after a title or a label** → ``[NAME]`` (the title stays, so the sentence still reads):
  - English: ``Mr``, ``Mrs``, ``Ms``, ``Miss``, ``Mx``, ``Dr`` (dot optional) + one or two capitalised words;
    ``my name is`` + one or two capitalised words; ``Name:`` or ``Full name:`` at the start of a line;
  - Thai: ``นาย``, ``นาง``, ``นางสาว``, ``น.ส.``, ``ด.ช.``, ``ด.ญ.`` + the given name, when a space,
    punctuation or the end of the text follows it (Thai has no spaces between words, so a name run into
    the next word cannot be told apart from it); ``นามสกุล`` + the surname; ``คุณ`` + a capitalised
    English name. Common compounds such as นายจ้าง (employer) or นางพยาบาล (nurse) are left alone.

Not detected (written down so nobody relies on it): names without a title or label (for example
``คุณสมชาย``, where คุณ may also mean "you"), Thai surnames after a given name, addresses, numbers of
fewer than 9 digits, and identifiers mixing letters and digits. Masking lowers the risk; it does not
make real personal data safe to use. Real data still needs the owner's decision (D4) after 7.2 and 7.3.

The placeholders never contain the masked value, its length or a hash of it. ``REDACTION_VERSION`` is
part of the AI agent's version: changing these rules is a new version, like a prompt change.
"""

from dataclasses import dataclass, field
import re

REDACTION_VERSION = "redact-v1"
KINDS = ("email", "thai_id", "card", "phone", "number", "name")
PLACEHOLDER = {"email": "[EMAIL]", "thai_id": "[THAI_ID]", "card": "[CARD]", "phone": "[PHONE]",
               "number": "[NUMBER]", "name": "[NAME]"}
MIN_DIGITS = 9

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# Digit groups with one separator between them; not glued to Latin letters or other digits. Thai letters
# may touch a number ("โทร0812345678"), so they are not part of the boundary.
_NUMBER_RUN = re.compile(r"(?<![0-9A-Za-z+])(\+?(?:\(\d{1,4}\)[ .-]?)?\d+(?:[ .-]\d+)*)(?![0-9A-Za-z])")
_LATIN_NAME = r"[A-Z][a-z]+(?:['’-][A-Za-z]+)?"
_ENGLISH_TITLE = re.compile(rf"\b(?:Mrs|Mr|Ms|Miss|Mx|Dr)\.?[ \t]+({_LATIN_NAME}(?:[ \t]+{_LATIN_NAME})?)")
_ENGLISH_LABEL = re.compile(rf"(?:\b[Mm]y name is|(?:^|(?<=[\n;(]))[ \t]*(?:[Ff]ull )?[Nn]ame[ \t]*:)[ \t]*"
                            rf"({_LATIN_NAME}(?:[ \t]+{_LATIN_NAME})?)", re.MULTILINE)
_THAI_WORD = r"[ก-๎]+"
_THAI_TITLE = re.compile(rf"(นางสาว|นาง|นาย|น\.ส\.|ด\.ช\.|ด\.ญ\.)[ \t]?({_THAI_WORD})(?=[\s,.;:!?()]|$)")
_THAI_SURNAME = re.compile(rf"นามสกุล[ \t]*:?[ \t]*({_THAI_WORD})")
_THAI_KHUN_LATIN = re.compile(rf"คุณ[ \t]?({_LATIN_NAME}(?:[ \t]+{_LATIN_NAME})?)")
# Words that begin with นาย or นาง but are not a title and a name (employer, broker, prime minister, …).
_NOT_NAMES = {"นาย": ("จ้าง", "หน้า", "กรัฐมนตรี", "กเทศมนตรี", "กสมาคม", "กองค์การ", "ทะเบียน", "อำเภอ", "ทุน",
                      "ท่า", "ด่าน", "ประกัน", "ห้าง", "ตรวจ", "สถานี", "พราน", "งาน"),
              "นาง": ("ฟ้า", "แบบ", "พยาบาล", "งาม", "รำ", "เอก", "ร้าย")}
_MAX_THAI_NAME = 20
# A date, alone or with the hour that a space joins to it ("2026-11-03 12:30"), is not personal data.
_DATE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}(?: \d{1,2})?")


@dataclass(frozen=True)
class MaskedText:
    """Text that went through :func:`mask`. ``counts`` lists only the kinds that were found."""
    text: str
    counts: dict = field(default_factory=dict)
    version: str = REDACTION_VERSION


def _ascii_digits(run):
    return "".join(str(int(ch)) for ch in run if ch.isdigit())


def _thai_id(digits):
    if len(digits) != 13:
        return False
    total = sum(int(digits[i]) * (13 - i) for i in range(12))
    return (11 - total % 11) % 10 == int(digits[12])


def _luhn(digits):
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, ch in enumerate(reversed(digits)):
        value = int(ch) * (2 if index % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def _phone(run, digits):
    if run.startswith("+"):
        if digits.startswith("66"):
            return len(digits) in (10, 11) and digits[2] in "23456789"
        return 8 <= len(digits) <= 15
    if digits.startswith("0066"):
        return len(digits) in (12, 13) and digits[4] in "23456789"
    return digits.startswith("0") and len(digits) in (9, 10) and digits[1] in "23456789"


def _number_kind(run):
    digits = _ascii_digits(run)
    if len(digits) < MIN_DIGITS or _DATE.fullmatch(run):
        return None
    if _thai_id(digits):
        return "thai_id"
    if _luhn(digits):
        return "card"
    if _phone(run, digits):
        return "phone"
    return "number"


def mask(text):
    """Return a :class:`MaskedText`. Masking masked text again changes nothing."""
    if not isinstance(text, str):
        raise TypeError("mask() takes text")
    counts = {}

    def count(kind):
        counts[kind] = counts.get(kind, 0) + 1
        return PLACEHOLDER[kind]

    text = _EMAIL.sub(lambda m: count("email"), text)

    def number(match):
        kind = _number_kind(match.group(1))
        return match.group(0) if kind is None else count(kind)

    text = _NUMBER_RUN.sub(number, text)

    def name(match, group=1):  # keep what came before the name (the title or label)
        start, end = match.span(group)
        return match.string[match.start():start] + count("name") + match.string[end:match.end()]

    def thai_name(match):
        title, word = match.group(1), match.group(2)
        if word.startswith(_NOT_NAMES.get(title, ())) or len(word) > _MAX_THAI_NAME:
            return match.group(0)
        return name(match, 2)

    for pattern in (_ENGLISH_TITLE, _ENGLISH_LABEL, _THAI_KHUN_LATIN, _THAI_SURNAME):
        text = pattern.sub(name, text)
    text = _THAI_TITLE.sub(thai_name, text)
    return MaskedText(text, {kind: counts[kind] for kind in KINDS if kind in counts})

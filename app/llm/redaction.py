"""Mask personal data before any text reaches an AI provider (roadmap 7.1, gap G5).

Flow for one AI call:
1. the agent calls :func:`mask` on the untrusted text;
2. it gets a :class:`MaskedText`: the text with placeholders, and how many of each kind were masked. Only
   :func:`mask` can make one: calling ``MaskedText(...)`` directly raises ``TypeError``;
3. the gateway (``structured_answer``) accepts only a ``MaskedText`` made by :func:`mask` under the current
   rules, and checks the text itself again with :func:`leftover`: if these rules would still mask anything,
   nothing is sent. So the masking is enforced where the text leaves, not only by the agents' habit.

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

Masking masked text again changes nothing, and the gateway relies on that. ``redact-v2`` fixed two inputs
where it did not hold in ``redact-v1``: ``นางสาว`` + a name masked again as ``นาง`` + the "name" ``สาว``, and a
name glued to an English title (``คุณZsMr Yaa``) or a number glued to a name (``Smith0812345678``) that only
the second pass saw. The rules now run again until nothing changes, and ``สาว`` after ``นาง`` is never a name.
"""

import re

REDACTION_VERSION = "redact-v2"
KINDS = ("email", "thai_id", "card", "phone", "number", "name")
PLACEHOLDER = {"email": "[EMAIL]", "thai_id": "[THAI_ID]", "card": "[CARD]", "phone": "[PHONE]",
               "number": "[NUMBER]", "name": "[NAME]"}
MIN_DIGITS = 9
_ROUNDS = 8  # the rules run again until nothing changes (masking one item can expose another)

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
              "นาง": ("สาว", "ฟ้า", "แบบ", "พยาบาล", "งาม", "รำ", "เอก", "ร้าย")}
_MAX_THAI_NAME = 20
# A date, alone or with the hour that a space joins to it ("2026-11-03 12:30"), is not personal data.
_DATE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}(?: \d{1,2})?")


_SEAL = object()  # held by this module only: mask() passes it, so other code cannot make a MaskedText by accident


class MaskedText:
    """Text that went through :func:`mask`. ``counts`` lists only the kinds that were found.

    Read-only, and made only by :func:`mask`: ``MaskedText("raw text")`` raises ``TypeError``. Python cannot stop
    code that goes out of its way (it could reach for ``_SEAL``), so the gateway checks the text again as well
    (:func:`leftover`).
    """
    __slots__ = ("_text", "_counts", "_version")

    def __init__(self, text, counts, version, *, _seal=None):
        if _seal is not _SEAL:
            raise TypeError("MaskedText is made only by app.llm.redaction.mask(): personal data is masked before "
                            "every AI call")
        object.__setattr__(self, "_text", text)
        object.__setattr__(self, "_counts", dict(counts))
        object.__setattr__(self, "_version", version)

    def __setattr__(self, name, value):
        raise AttributeError("MaskedText is read-only")

    def __delattr__(self, name):
        raise AttributeError("MaskedText is read-only")

    def __reduce__(self):  # no copies through pickle or copy.copy: they would skip the seal check
        raise TypeError("MaskedText cannot be copied; call mask() again")

    @property
    def text(self):
        return self._text

    @property
    def counts(self):
        return dict(self._counts)  # a copy, so a caller cannot change what was recorded

    @property
    def version(self):
        return self._version

    def __eq__(self, other):
        if type(other) is not MaskedText:
            return NotImplemented
        return (self._text, self._counts, self._version) == (other._text, other._counts, other._version)

    __hash__ = None

    def __repr__(self):
        return f"MaskedText(text={self._text!r}, counts={self._counts!r}, version={self._version!r})"


def is_sealed(value):
    """True only for a :class:`MaskedText` that :func:`mask` made under the current rules."""
    return (type(value) is MaskedText and type(value.text) is str and value.version == REDACTION_VERSION
            and isinstance(getattr(value, "_counts", None), dict))


def leftover(text):
    """The kinds these rules would still mask in ``text`` (counts per kind), ``{}`` when there is nothing.

    The gateway calls it on the text it is about to send: for text that came from :func:`mask` it is always
    ``{}``, because masking masked text again changes nothing."""
    return mask(text).counts


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


def _mask_once(text, count):
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
    return _THAI_TITLE.sub(thai_name, text)


def mask(text):
    """Return a :class:`MaskedText`. Masking masked text again changes nothing.

    The rules run again while they still change the text (at most ``_ROUNDS`` times): masking a name can free a
    number that was glued to it (``Smith0812345678``), and a placeholder can open a word boundary for a title.
    """
    if not isinstance(text, str):
        raise TypeError("mask() takes text")
    counts = {}

    def count(kind):
        counts[kind] = counts.get(kind, 0) + 1
        return PLACEHOLDER[kind]

    for _round in range(_ROUNDS):
        masked = _mask_once(text, count)
        if masked == text:
            break
        text = masked
    return MaskedText(text, {kind: counts[kind] for kind in KINDS if kind in counts}, REDACTION_VERSION, _seal=_SEAL)

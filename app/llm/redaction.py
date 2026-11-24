"""Mask personal data before any text reaches an AI provider (roadmap 7.1, gap G5).

Flow for one AI call:
1. the agent calls :func:`mask` on the untrusted text;
2. it gets a :class:`MaskedText`: the text with placeholders, and how many of each kind were masked. Only
   :func:`mask` can make one: calling ``MaskedText(...)`` directly raises ``TypeError``;
3. the gateway (``structured_answer``) accepts only a ``MaskedText`` made by :func:`mask` under the current
   rules, and checks the text itself again with :func:`leftover`: if these rules would still mask anything,
   nothing is sent. So the masking is enforced where the text leaves, not only by the agents' habit.

What is masked (Thai and English), in this order:

* **e-mail addresses** → ``[EMAIL]``:
  - ASCII addresses (``somchai.j@example.co.th``);
  - addresses with Thai or other non-ASCII letters, an internationalised domain such as ``.ไทย`` included
    (``สมชาย@ตัวอย่าง.ไทย``), starting after a space, punctuation or the start of the text;
  - addresses written out: ``at``/``(at)``/``[at]``/``แอท`` for ``@`` and ``dot``/``(dot)``/``[dot]``/``ดอท`` for
    a dot, ending in a common top-level domain (``somchai at example dot com``). The list of endings keeps
    phrases such as "look at the dot matrix" readable. A plain "at" needs a written-out dot and a first
    part that is not a common word, so ``I cannot login at example.com`` keeps its words;
* **long numbers**: a run of digits (Thai digits too) with spaces (up to three), dashes, dots or slashes
  between the groups (with or without spaces around them), or with invisible zero-width characters between
  them, and an optional ``+`` or area code in brackets. A date (``2026-11-03``, ``24/11/2026``,
  ``24.11.2026``), alone or with the hour that a space joins to it, is left alone when its parts make a date
  (``08-12-3456 78`` does not). Runs of 9 or more digits are masked by what they look like, the first match
  winning:
  - 13 digits with a valid Thai ID check digit → ``[THAI_ID]``;
  - 13–19 digits passing the Luhn check (card-like) → ``[CARD]``;
  - a phone number → ``[PHONE]``: Thai numbers (0 + 8–9 digits, the second digit 2–9), +66/0066 + 8–9
    digits, or another number written with ``+`` (8–15 digits);
  - anything else (bank account, order or policy numbers) → ``[NUMBER]``;
* **names after a title or a label** → ``[NAME]`` (the title stays, so the sentence still reads). A name word
  is capitalised (``Smith``, ``McDonald``, ``O'Neil``, ``Anne-Marie``) or written in capitals (``SMITH``); a
  second word of the same kind joins it:
  - English: ``Mr`` or ``Mrs`` (any case, dot optional) + one or two name words, which may also be written in
    small letters (``mr john smith``); ``Ms``, ``Miss``, ``Mx``, ``Dr`` + one or two name words, not in small
    letters (``miss``, ``dr`` and ``ms`` are ordinary words too); ``my name is`` (any case) + one or two name
    words, small letters included; ``Name:`` or ``Full name:`` at the start of a line;
  - a word written in capitals or small letters is not taken for a name when it is a common English word
    (``Mr. IT``, ``my name is not shown``, ``Mr John called``): see ``_NOT_A_NAME``;
  - Thai: ``นาย``, ``นาง``, ``นางสาว``, ``น.ส.``, ``ด.ช.``, ``ด.ญ.`` + the given name, when a space,
    punctuation or the end of the text follows it (Thai has no spaces between words, so a name run into
    the next word cannot be told apart from it); ``นามสกุล`` + the surname; ``คุณ`` + an English name word
    (not in small letters). Common compounds such as นายจ้าง (employer) or นางพยาบาล (nurse) are left alone.

Not detected (written down so nobody relies on it): names without a title or label (for example
``คุณสมชาย``, where คุณ may also mean "you", or ``John Smith called``), Thai surnames after a given name,
addresses, an e-mail written with a plain "at" and real dots (``somchai at gmail.com``, which reads like
``login at example.com``), numbers of fewer than 9 digits, numbers spelled out in words, and identifiers
mixing letters and digits. Masking lowers the risk; it does not make real personal data safe to use. Real data still needs the
owner's decision (D4) after 7.2 and 7.3.

The placeholders never contain the masked value, its length or a hash of it. ``REDACTION_VERSION`` is
part of the AI agent's version: changing these rules is a new version, like a prompt change.

Masking masked text again changes nothing, and the gateway relies on that. ``redact-v2`` fixed two inputs
where it did not hold in ``redact-v1``: ``นางสาว`` + a name masked again as ``นาง`` + the "name" ``สาว``, and a
name glued to an English title (``คุณZsMr Yaa``) or a number glued to a name (``Smith0812345678``) that only
the second pass saw. The rules now run again until nothing changes (with no fixed limit, see :func:`mask`), and
``สาว`` after ``นาง`` is never a name.

``redact-v3`` (2026-11-24, roadmap 5.5) closed the ten masking gaps that the robustness benchmark found
(SYN-MSK-040 to 049): phone numbers split by double spaces, zero-width spaces or slashes; names in capitals or
small letters after a title; ``McDonald`` (``redact-v2`` left ``Donald`` behind) and ``O'Neil``; a Thai-domain
e-mail; an e-mail written as "at … dot"; and ``my name is`` + a name in small letters. It also leaves a date
with dots and an hour (``24.11.2026 10:30``) readable, which ``redact-v2`` masked as a number, and never takes a
title for a surname (``redact-v2`` masked ``Mr Smith Mrs Jones`` as ``Mr [NAME] Jones``).
"""

import re

REDACTION_VERSION = "redact-v3"
KINDS = ("email", "thai_id", "card", "phone", "number", "name")
PLACEHOLDER = {"email": "[EMAIL]", "thai_id": "[THAI_ID]", "card": "[CARD]", "phone": "[PHONE]",
               "number": "[NUMBER]", "name": "[NAME]"}
MIN_DIGITS = 9

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# An address with Thai or other non-ASCII letters (an internationalised domain such as .ไทย). Python's \w covers
# letters and digits of every script but not Thai vowel and tone marks or combining accents, so they are added.
_INTL = "\\w\u0e00-\u0e7f\u0300-\u036f"
_EMAIL_INTL = re.compile(rf"(?<![{_INTL}.%+-])[{_INTL}.%+-]+@[{_INTL}-]+(?:\.[{_INTL}-]+)*"
                         rf"\.(?:[^\W\d_]|[\u0e00-\u0e7f])[{_INTL}]+")
# An address written out: "somchai at example dot com", "(at)", "[dot]", แอท, ดอท. It must end in one of these
# top-level domains, so that phrases such as "look at the dot matrix printer" stay readable.
_TOP_LEVEL = ("com", "net", "org", "edu", "gov", "mil", "int", "info", "biz", "name", "pro", "io", "co", "me", "app",
              "dev", "ai", "th", "uk", "us", "jp", "cn", "de", "fr", "au", "sg", "my", "vn", "la", "kh", "mm", "id",
              "ph", "in", "kr", "tw", "hk", "ru", "ca", "nz", "ac", "or", "go")
_SPELLED_AT = r"(?:[ \t]+(?i:at)[ \t]+|[ \t]*[(\[{][ \t]*(?i:at)[ \t]*[)\]}][ \t]*|[ \t]*แอท[ \t]*)"
_SPELLED_DOT = r"(?:[ \t]+(?i:dot)[ \t]+|[ \t]*[(\[{][ \t]*(?i:dot)[ \t]*[)\]}][ \t]*|[ \t]*ดอท[ \t]*|\.)"
_EMAIL_SPELLED = re.compile(
    rf"(?<![A-Za-z0-9._%+-])(?P<local>[A-Za-z0-9._%+-]+)(?P<at>{_SPELLED_AT}|@)(?P<domain>[A-Za-z0-9-]+"
    rf"(?:{_SPELLED_DOT}[A-Za-z0-9-]+)*{_SPELLED_DOT}(?i:{'|'.join(sorted(_TOP_LEVEL, key=len, reverse=True))}))"
    rf"(?![A-Za-z0-9-])")
_SPELLED_DOT_WORD = re.compile(r"(?i:(?<![A-Za-z])dot(?![A-Za-z]))|ดอท")
# Digit groups and what may stand between them: spaces (up to three), a dash, dot or slash with or without spaces
# around it, or invisible zero-width characters (text copied from some websites). Not glued to Latin letters or
# other digits. Thai letters may touch a number ("โทร0812345678"), so they are not part of the boundary.
_GAP = "(?:[ \\t]*[./-][ \\t]*|[ \\t]{1,3}|[\u200b\u200c\u200d\u2060\ufeff]+)"
_NUMBER_RUN = re.compile(rf"(?<![0-9A-Za-z+])(\+?(?:\(\d{{1,4}}\)[ .-]?)?\d+(?:{_GAP}\d+)*)(?![0-9A-Za-z])")
# Common English words that are not taken for a name when they are written in capitals or in small letters, so
# that "Mr. IT", "Mr John called" and "my name is not shown" stay readable. Words that are also common first
# names (Will, May, Mark, Grace) are not on the list. A capitalised word after a title is a name, as in redact-v2.
_NOT_A_NAME = tuple(sorted(set("""
    a an the and or but nor so yet if then than as at by for from in into of off on onto out over to up via with
    without about after before since until again also just only still even too very here there now today tonight
    tomorrow yesterday soon later i me my mine we us our you your he him his she her it its they them their this
    that these those who whom whose which what when where why how all any each every some no not yes ok okay
    please thanks thank hi hello dear sir madam is am are was were be been being has have had do does did done
    shall should can cannot cant could would might must ought won wont didnt doesnt dont isnt wasnt arent hasnt
    havent hadnt couldnt wouldnt shouldnt call calls called calling say says said ask asks asked want wants wanted
    need needs needed try tries tried send sends sent pay pays paid report reports reported get gets got come comes
    came go goes went make makes made reset login log logged sign signed upload uploaded download downloaded
    refund refunded charge charged cancel cancelled canceled lock locked forgot lost change changed update updated
    show shows shown showing display displayed print printed list listed register registered write written type
    typed enter entered save saved use used take taken link linked block blocked spell spelled spelt misspelled
    misspelt missing wrong incorrect correct right different same blank empty cut truncated garbled broken gone
    deleted removed invalid unknown account appointment office support admin user customer client team password
    email phone number name it hr pc id otp pin vpn api pdf sms usb atm
""".split()) | {word.replace("'", mark) for word in ("can't", "won't", "don't", "didn't", "doesn't", "isn't",
                                                   "wasn't", "aren't", "hasn't", "haven't", "hadn't", "couldn't",
                                                   "wouldn't", "shouldn't", "i'm", "i've", "it's", "that's")
                 for mark in ("'", "’")}, key=lambda word: (-len(word), word)))
_END = r"(?![A-Za-z'’-])"
_NOT_COMMON = rf"(?!(?:{'|'.join(_NOT_A_NAME)}){_END})(?!(?:{'|'.join(w.upper() for w in _NOT_A_NAME)}){_END})"
# Titles, for the inside of a word: "AaMr Bb" is the name Aa, then the title Mr (redact-v2 read it so too).
_TITLES = r"(?:Mrs|Mr|Ms|Miss|Mx|Dr)(?![a-z])"
# A title is never a name word, so "Mr Smith Mrs Jones" masks both names (redact-v2 took "Mrs" for Smith's surname).
_NOT_TITLE = r"(?!(?:Mrs|Mr|Ms|Miss|Mx|Dr|MRS|MR|mrs|mr)(?![A-Za-z]))"
# A name word, whole: capitalised (Smith, McDonald, O'Neil, Anne-Marie, Smith's), in capitals (SMITH, O'NEIL,
# McDONALD). A capitalised word may run straight into a title ("AaMr Bb" is the name Aa, then Mr Bb).
_CAP_WORD = (rf"{_NOT_COMMON}{_NOT_TITLE}(?:[A-Z](?:['’][A-Z])?[a-z]+(?:(?!{_TITLES})[A-Z][a-z]+)*(?:['’-][A-Za-z]+)*"
             rf"(?:(?![A-Za-z])|(?={_TITLES}))|[A-Z](?:['’]?[A-Z])+(?:-[A-Z]+)*(?![A-Za-z])"
             rf"|Ma?c[A-Z](?:['’]?[A-Z])+(?![A-Za-z]))")
_SMALL_WORD = rf"{_NOT_COMMON}{_NOT_TITLE}[a-z](?:['’]?[a-z])+(?:-[a-z]+)*(?![A-Za-z])"
_CAP_NAME = rf"{_CAP_WORD}(?:[ \t]+{_CAP_WORD})?"
_ANY_NAME = rf"(?:{_CAP_NAME}|{_SMALL_WORD}(?:[ \t]+{_SMALL_WORD})?)"
_MR_TITLE = re.compile(rf"\b(?:Mrs|Mr|MRS|MR|mrs|mr)\.?[ \t]+({_ANY_NAME})")
_OTHER_TITLE = re.compile(rf"\b(?:Ms|Miss|Mx|Dr)\.?[ \t]+({_CAP_NAME})")
_MY_NAME_IS = re.compile(rf"\b(?i:my name is)[ \t]+({_ANY_NAME})")
_NAME_LABEL = re.compile(rf"(?:^|(?<=[\n;(]))[ \t]*(?:[Ff]ull )?[Nn]ame[ \t]*:[ \t]*({_CAP_NAME})", re.MULTILINE)
_THAI_WORD = r"[ก-๎]+"
_THAI_TITLE = re.compile(rf"(นางสาว|นาง|นาย|น\.ส\.|ด\.ช\.|ด\.ญ\.)[ \t]?({_THAI_WORD})(?=[\s,.;:!?()]|$)")
_THAI_SURNAME = re.compile(rf"นามสกุล[ \t]*:?[ \t]*({_THAI_WORD})")
_THAI_KHUN_LATIN = re.compile(rf"คุณ[ \t]?({_CAP_NAME})")
# Words that begin with นาย or นาง but are not a title and a name (employer, broker, prime minister, …).
_NOT_NAMES = {"นาย": ("จ้าง", "หน้า", "กรัฐมนตรี", "กเทศมนตรี", "กสมาคม", "กองค์การ", "ทะเบียน", "อำเภอ", "ทุน",
                      "ท่า", "ด่าน", "ประกัน", "ห้าง", "ตรวจ", "สถานี", "พราน", "งาน"),
              "นาง": ("สาว", "ฟ้า", "แบบ", "พยาบาล", "งาม", "รำ", "เอก", "ร้าย")}
_MAX_THAI_NAME = 20
# A date, alone or with the hour that a space joins to it ("2026-11-03 12:30", "24/11/2026 10:30",
# "24.11.2026 10:30"), is not personal data. The same mark separates its three parts, and the parts must make a
# date (see _is_date): "08-12-3456 78" is a phone number, not a date.
_DATE = re.compile(r"(?:(?P<y1>\d{4})[ \t]*(?P<s1>[-/.])[ \t]*(?P<a1>\d{1,2})[ \t]*(?P=s1)[ \t]*(?P<b1>\d{1,2})"
                   r"|(?P<a2>\d{1,2})[ \t]*(?P<s2>[-/.])[ \t]*(?P<b2>\d{1,2})[ \t]*(?P=s2)[ \t]*(?P<y2>\d{4}))"
                   r"(?:[ \t]+(?P<hour>\d{1,2}))?")


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


def _is_date(run):
    """True when ``run`` is a date (and maybe an hour) whose parts make sense: a year from 1900 to 2100 or the same
    years in the Thai calendar (2443 to 2643), a day and a month in either order, an hour from 0 to 23."""
    match = _DATE.fullmatch(run)
    if not match:
        return False
    year = int(match["y1"] or match["y2"])
    first, second = int(match["a1"] or match["a2"]), int(match["b1"] or match["b2"])
    if not (1900 <= year <= 2100 or 2443 <= year <= 2643):
        return False
    if match["hour"] is not None and int(match["hour"]) > 23:
        return False
    return (1 <= first <= 12 and 1 <= second <= 31) or (1 <= first <= 31 and 1 <= second <= 12)


def _written_out_address(match):
    """Whether a written-out address is one. A plain word "at" followed by real dots reads like a place on the
    web ("I cannot login at example.com"), and a common word before "at … dot" too ("login at example dot com"):
    both are left alone, so the case keeps the word the triage needs. ``@``, ``(at)``, ``[at]`` and แอท are
    always an address."""
    if match["at"].strip().lower() != "at":
        return True
    return (_SPELLED_DOT_WORD.search(match["domain"]) is not None
            and match["local"].lower() not in _NOT_A_NAME)


def _number_kind(run):
    digits = _ascii_digits(run)
    if len(digits) < MIN_DIGITS or _is_date(run):
        return None
    if _thai_id(digits):
        return "thai_id"
    if _luhn(digits):
        return "card"
    if _phone(run, digits):
        return "phone"
    return "number"


def _mask_once(text, count):
    for pattern in (_EMAIL, _EMAIL_INTL):
        text = pattern.sub(lambda m: count("email"), text)
    text = _EMAIL_SPELLED.sub(lambda m: count("email") if _written_out_address(m) else m.group(0), text)

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

    for pattern in (_MR_TITLE, _OTHER_TITLE, _MY_NAME_IS, _NAME_LABEL, _THAI_KHUN_LATIN, _THAI_SURNAME):
        text = pattern.sub(name, text)
    return _THAI_TITLE.sub(thai_name, text)


def mask(text):
    """Return a :class:`MaskedText`. Masking masked text again changes nothing.

    The rules run again until they change nothing: masking a name can free a number that was glued to it
    (``Smith0812345678``), and a placeholder can open a word boundary for the next title (``คุณAaMr BbMr Cc…``
    exposes one more name per round). This always ends: every match takes at least one character of the original
    text. A placeholder is ``[``, capitals and ``_``, then ``]``: it holds no digit, no ``@`` and no Thai letter; a
    name must start right after a space, a title or a label, and the first part of an address must be followed by
    ``@`` or a written-out "at"; neither can happen inside the brackets, so no rule matches inside one. A round that
    changes the text therefore leaves fewer original characters than the round before. ``len(text) + 1`` rounds are therefore enough for any text; the loop stops as soon as a round changes
    nothing, which for ordinary text is the second round.
    """
    if not isinstance(text, str):
        raise TypeError("mask() takes text")
    counts = {}

    def count(kind):
        counts[kind] = counts.get(kind, 0) + 1
        return PLACEHOLDER[kind]

    for _round in range(len(text) + 1):
        masked = _mask_once(text, count)
        if masked == text:
            break
        text = masked
    return MaskedText(text, {kind: counts[kind] for kind in KINDS if kind in counts}, REDACTION_VERSION, _seal=_SEAL)

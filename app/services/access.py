"""Who may call the API, and what each role may do (roadmap 2.1, ADR-034).

Two kinds of credential, both sent as ``Authorization: Bearer <credential>``:

* the shared key ``NEURON_FLOW_ACCESS_KEY``: the owner's bootstrap credential (ADR-016). Its holder is the owner,
  recorded as ``shared-access-key``;
* a personal token the owner issued: ``nf_<token_id>_<secret>``, for the role ``reviewer`` (reads cases, the inbox
  and reviews; records decisions) or ``submitter`` (sends, cancels and reads cases; for n8n and other tools). No
  token is an owner's in this version.

The queue database keeps a token's id, the SHA-256 of its secret, a display name and the role, never the secret
(``QueueStore.create_token``). A token is shown once, in the reply that creates it. Every request reads the token's
row again (no cache), so a revocation applies to the next request. On storage that is not persistent the tokens go
with the queue at every wipe, so a lost token is refused like an unknown one: it fails closed.

What each role may do is one fixed table, :data:`PERMISSIONS`, checked before any route runs. Who decides a review
comes from here, never from a request body (ADR-027).
"""

from dataclasses import dataclass
import hashlib
import hmac
import re
import secrets
import sqlite3
from typing import Optional

from app.persistence import TokenLimit
from app.persistence.queue_store import iso

OWNER, REVIEWER, SUBMITTER = "owner", "reviewer", "submitter"
ROLES = (OWNER, REVIEWER, SUBMITTER)
ISSUABLE_ROLES = (REVIEWER, SUBMITTER)  # the owner role belongs to the shared key alone (ADR-034)
SHARED_KEY_ID = "shared-access-key"
TOKEN = re.compile(r"^nf_([0-9a-f]{16})_([A-Za-z0-9_-]{43})$")
TOKEN_ID = re.compile(r"^[0-9a-f]{16}$")
TOKEN_LIKE = re.compile(r"nf_[0-9a-f]{16}_")  # text that holds the start of a token is never logged or stored
MAX_ACTIVE_TOKENS = 50
NAME_MAX_CHARS = 60
TOUCH_INTERVAL_S = 60.0  # ``last_used_at`` is written at most once a minute per token
_FIELDS = {"display_name", "role"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# Compared when a token's id is unknown, so an unknown id takes the same work as a wrong secret.
_UNKNOWN = hashlib.sha256(b"neuron-flow: no token has this id").hexdigest()

_EVERYONE = frozenset(ROLES)
_OWNER = frozenset({OWNER})
_SENDS = frozenset({OWNER, SUBMITTER})
_DECIDES = frozenset({OWNER, REVIEWER})
# (method, route template) -> the roles that may call it. HEAD counts as GET. A route missing here is nobody's.
PERMISSIONS = {
    ("GET", "/v1/status"): _EVERYONE,
    ("GET", "/v1/me"): _EVERYONE,
    ("GET", "/v1/frame"): _EVERYONE,  # what the system can do, in plain words (roadmap 4.1)
    ("GET", "/v1/jobs"): _EVERYONE,
    ("POST", "/v1/jobs"): _SENDS,
    ("GET", "/v1/jobs/{job_id}"): _EVERYONE,
    ("GET", "/v1/jobs/{job_id}/events"): _EVERYONE,
    ("POST", "/v1/jobs/{job_id}/cancel"): _SENDS,
    ("POST", "/v1/jobs/{job_id}/confirm"): _SENDS,  # a person confirms the router's proposal (roadmap 4.2)
    ("POST", "/v1/jobs/{job_id}/reply"): _SENDS,    # a person answers the router's question
    ("GET", "/v1/reviews"): _DECIDES,
    ("GET", "/v1/reviews/scorecard"): _DECIDES,
    ("GET", "/v1/reviews/{review_id}"): _DECIDES,
    ("POST", "/v1/reviews/{review_id}/decisions"): _DECIDES,
    ("GET", "/v1/tokens"): _OWNER,
    ("POST", "/v1/tokens"): _OWNER,
    ("POST", "/v1/tokens/{token_id}/revoke"): _OWNER,
}


@dataclass(frozen=True)
class Identity:
    """The caller, from the credential: ``token_id`` is ``shared-access-key`` for the owner's shared key."""
    token_id: str
    role: str
    display_name: Optional[str] = None

    @property
    def reviewer(self):
        """What a decision records about who made it (ADR-027)."""
        return {"token_id": self.token_id, "role": self.role}


OWNER_IDENTITY = Identity(SHARED_KEY_ID, OWNER)


class TokenError(Exception):
    """A refused token request. ``status`` is the HTTP status, ``code`` a stable machine-readable reason."""

    def __init__(self, status, code, message, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def method_of(method):
    return "GET" if method == "HEAD" else method


def known(method, template):
    """Whether the table names this route: only then can a role be refused (403) rather than the route (404/405)."""
    return (method_of(method), template) in PERMISSIONS


def allowed(method, template, role):
    return role in PERMISSIONS.get((method_of(method), template), ())


def secret_sha256(secret):
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


def parse_token(value):
    """``(token_id, secret)`` of a well-formed token, or ``None``."""
    match = TOKEN.fullmatch(value or "")
    return (match.group(1), match.group(2)) if match else None


def authenticate(store, presented, shared_digest, *, now):
    """The :class:`Identity` behind a bearer credential, or ``None`` for a wrong, unknown, revoked or lost one.

    ``shared_digest`` is the SHA-256 (bytes) of the shared key. Both comparisons use ``hmac.compare_digest``.
    """
    if not presented:
        return None
    presented_digest = hashlib.sha256(presented.encode("utf-8", "surrogatepass")).digest()
    if shared_digest is not None and hmac.compare_digest(presented_digest, shared_digest):
        return OWNER_IDENTITY
    parsed = parse_token(presented)
    if parsed is None:
        return None
    token_id, secret = parsed
    row = store.token_for_check(token_id)
    matches = hmac.compare_digest(secret_sha256(secret), row["secret_sha256"] if row is not None else _UNKNOWN)
    if row is None or not matches or row["revoked_at"] is not None:
        return None
    if row["last_used_at"] is None or now - row["last_used_at"] >= TOUCH_INTERVAL_S:
        store.touch_token(token_id, now)
    return Identity(token_id, row["role"], row["display_name"])


def check_new_token(body):
    """``(display_name, role)`` of a request for a new token, or :class:`TokenError` (400) before anything is
    written."""
    if not isinstance(body, dict) or set(body) != _FIELDS:
        raise TokenError(400, "invalid_fields", "The body must contain exactly display_name and role")
    name = body["display_name"]
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > NAME_MAX_CHARS \
            or _CONTROL.search(name) or TOKEN_LIKE.search(name):
        raise TokenError(400, "invalid_display_name",
                         f"display_name must be 1-{NAME_MAX_CHARS} characters of text, such as a role and a number")
    if body["role"] not in ISSUABLE_ROLES:
        raise TokenError(400, "invalid_role", "role must be reviewer or submitter", allowed=list(ISSUABLE_ROLES))
    return name.strip(), body["role"]


def issue(store, body, *, created_by, now=None):
    """A new token: ``(token, row)``. ``token`` is the only copy of the secret; it is returned once and never kept."""
    name, role = check_new_token(body)
    for _attempt in range(3):  # 64 random bits: a repeated id is next to impossible, but never an error
        token_id, secret = secrets.token_hex(8), secrets.token_urlsafe(32)
        try:
            row = store.create_token(token_id=token_id, secret_sha256=secret_sha256(secret), display_name=name,
                                     role=role, created_by=created_by, max_active=MAX_ACTIVE_TOKENS, now=now)
        except TokenLimit as exc:
            raise TokenError(409, "too_many_tokens", f"At most {MAX_ACTIVE_TOKENS} tokens can be active; revoke one "
                             "that is no longer used", active=exc.active, max_active=MAX_ACTIVE_TOKENS) from None
        except sqlite3.IntegrityError:
            continue
        return f"nf_{token_id}_{secret}", row
    raise RuntimeError("could not draw an unused token id")


# -- views ------------------------------------------------------------------------------------

def token_view(row):
    """A token as the owner sees it: never its secret or the secret's hash."""
    return {"token_id": row["token_id"], "display_name": row["display_name"], "role": row["role"],
            "active": row["revoked_at"] is None, "created_at": iso(row["created_at"]), "created_by": row["created_by"],
            "last_used_at": iso(row["last_used_at"]), "revoked_at": iso(row["revoked_at"]),
            "revoked_by": row["revoked_by"]}


def me_view(identity):
    """Who the caller is and what the role may do, so a page shows only what will work."""
    role = identity.role
    return {"token_id": identity.token_id, "role": role, "display_name": identity.display_name,
            "shared_key": identity.token_id == SHARED_KEY_ID,
            "can": {"submit": allowed("POST", "/v1/jobs", role),
                    "cancel": allowed("POST", "/v1/jobs/{job_id}/cancel", role),
                    "review": allowed("POST", "/v1/reviews/{review_id}/decisions", role),
                    "manage_tokens": allowed("POST", "/v1/tokens", role)}}


def policy():
    """For ``/v1/status``: the roles and the limits, never a token."""
    return {"per_person_tokens": True, "roles": list(ROLES), "issuable_roles": list(ISSUABLE_ROLES),
            "max_active_tokens": MAX_ACTIVE_TOKENS, "display_name_max_chars": NAME_MAX_CHARS}

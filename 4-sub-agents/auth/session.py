"""
Session helpers — thin wrappers around Starlette's signed-cookie sessions.

Starlette's ``SessionMiddleware`` (backed by ``itsdangerous``) handles:
- HMAC-SHA256 signing of the cookie value.
- Tamper detection (signature mismatch → session cleared).

This module provides higher-level helpers that read/write structured data
into ``request.session`` so that the OAuth flow and the route handlers share
a single, well-typed interface.

Session key conventions
-----------------------
``oauth_state``          Random CSRF state value generated at /login.
``oauth_nonce``          OIDC nonce generated at /login.
``oauth_code_verifier``  PKCE code_verifier generated at /login.
``user``                 Authenticated user profile dict, present after
                          successful callback.

All three oauth_ keys are *one-time*: they are deleted immediately after the
callback handler consumes them to prevent replay.
"""

from typing import Any

from starlette.requests import Request

# Session keys
_KEY_STATE = "oauth_state"
_KEY_NONCE = "oauth_nonce"
_KEY_VERIFIER = "oauth_code_verifier"
_KEY_USER = "user"


# ---------------------------------------------------------------------------
# Pre-login (store ephemeral PKCE / CSRF values)
# ---------------------------------------------------------------------------


def store_oauth_params(
    request: Request,
    *,
    state: str,
    nonce: str,
    code_verifier: str,
) -> None:
    """
    Persist the PKCE verifier, CSRF state, and nonce into the session.

    Called at the start of the login flow, before redirecting to the provider.
    """
    request.session[_KEY_STATE] = state
    request.session[_KEY_NONCE] = nonce
    request.session[_KEY_VERIFIER] = code_verifier


def pop_oauth_params(request: Request) -> tuple[str, str, str]:
    """
    Return and **delete** the one-time OAuth params from the session.

    Returns
    -------
    tuple[str, str, str]
        ``(state, nonce, code_verifier)``

    Raises
    ------
    KeyError
        If any expected key is missing (session was never populated or already consumed).
    """
    try:
        state = request.session.pop(_KEY_STATE)
        nonce = request.session.pop(_KEY_NONCE)
        verifier = request.session.pop(_KEY_VERIFIER)
    except KeyError as exc:
        raise KeyError(
            f"OAuth session key missing: {exc}. "
            "The session may have expired, been tampered with, or this callback "
            "was called without a prior /login request."
        ) from exc
    return state, nonce, verifier


# ---------------------------------------------------------------------------
# Post-login (authenticated user profile)
# ---------------------------------------------------------------------------


def set_authenticated_user(request: Request, user_profile: dict[str, Any]) -> None:
    """
    Store the authenticated user profile in the session.

    *user_profile* is the dict returned by the userinfo endpoint (or a
    subset of it).  Callers may add additional claims (e.g. from the
    id_token) before storing.
    """
    request.session[_KEY_USER] = user_profile


def get_authenticated_user(request: Request) -> dict[str, Any] | None:
    """
    Return the authenticated user profile dict, or ``None`` if not logged in.
    """
    return request.session.get(_KEY_USER)


def clear_session(request: Request) -> None:
    """
    Destroy the entire session (used by /logout).
    """
    request.session.clear()

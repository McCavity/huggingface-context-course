"""
OAuth2/OIDC client configuration loaded from environment variables.

Required environment variables
-------------------------------
OAUTH_ISSUER          Base URL of the identity provider (e.g. https://accounts.example.com).
                      The /.well-known/openid-configuration path is *not* fetched at startup;
                      the three endpoint URLs are derived from ISSUER or overridden explicitly.
OAUTH_CLIENT_ID       The client_id registered with the provider.
OAUTH_CLIENT_SECRET   The client_secret (keep this out of source control).
OAUTH_REDIRECT_URI    The exact redirect URI registered with the provider
                      (e.g. http://localhost:8000/auth/callback).
SESSION_SECRET        A long random string used to sign session cookies (>=32 chars required).

Optional overrides (default to OAUTH_ISSUER + path)
----------------------------------------------------
OAUTH_AUTHORIZE_URL   Override the authorization endpoint.
OAUTH_TOKEN_URL       Override the token endpoint.
OAUTH_USERINFO_URL    Override the userinfo endpoint.
OAUTH_JWKS_URI        Override the JWKS endpoint (default: {issuer}/.well-known/jwks.json).

Dev-only flag
-------------
OAUTH_ALLOW_INSECURE  Set to "1" to permit http:// URLs for local development.
                      Never set in production.
"""

import os
from dataclasses import dataclass, field


_SESSION_SECRET_MIN_LENGTH = 32

# Hostnames that are always considered local even under http://.
_LOCAL_HOSTS = {"localhost", "127.0.0.1"}


@dataclass(frozen=True)
class OAuthConfig:
    """Immutable configuration object constructed from environment variables."""

    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    session_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    jwks_uri: str

    # True when OAUTH_ALLOW_INSECURE=1 was set at load time.
    # Consumers (e.g. main.py) must use this field rather than re-reading the
    # environment variable so that the value is always consistent with the
    # URLs already validated in load_config().
    allow_insecure: bool = False

    # Scopes requested from the provider.
    scopes: str = "openid profile email"


def _require(name: str) -> str:
    """Return the value of an env var or raise a clear error."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            "See module docstring for the full list of required variables."
        )
    return value


def _is_url_allowed(url: str, allow_insecure: bool) -> bool:
    """
    Return True if *url* satisfies the HTTPS enforcement policy.

    Rules:
    - ``https://`` is always allowed.
    - ``http://localhost`` and ``http://127.0.0.1`` are allowed only when
      *allow_insecure* is True (i.e. ``OAUTH_ALLOW_INSECURE=1`` is set).
    - All other ``http://`` URLs are rejected.
    """
    from urllib.parse import urlparse  # local import to keep module import light

    parsed = urlparse(url)
    if parsed.scheme == "https":
        return True
    if parsed.scheme == "http" and allow_insecure and parsed.hostname in _LOCAL_HOSTS:
        return True
    return False


def _validate_url(name: str, url: str, allow_insecure: bool) -> None:
    """
    Raise ``RuntimeError`` if *url* violates the HTTPS enforcement policy.

    Parameters
    ----------
    name:
        Human-readable name of the URL (used in error message).
    url:
        The URL string to validate.
    allow_insecure:
        When True, ``http://localhost`` / ``http://127.0.0.1`` are allowed.
        When False, only ``https://`` is accepted.
    """
    if not _is_url_allowed(url, allow_insecure):
        raise RuntimeError(
            f"Configuration error: '{name}' must use https:// in production. "
            f"Got: '{url}'. "
            "Set OAUTH_ALLOW_INSECURE=1 to permit http://localhost or "
            "http://127.0.0.1 for local development only."
        )


def load_config() -> OAuthConfig:
    """
    Build an :class:`OAuthConfig` from environment variables.

    Endpoint URLs fall back to ``{OAUTH_ISSUER}/{path}`` when not explicitly
    overridden, which satisfies the majority of OIDC-compliant providers.

    Security checks
    ---------------
    - ``SESSION_SECRET`` must be at least 32 characters.
    - All endpoint URLs and ``redirect_uri`` must use ``https://`` unless
      ``OAUTH_ALLOW_INSECURE=1`` is set (dev mode only).
    - ``allow_insecure`` is stored on the returned config object so callers
      never need to re-read the environment variable themselves.
    """
    issuer = _require("OAUTH_ISSUER").rstrip("/")

    session_secret = _require("SESSION_SECRET")
    if len(session_secret) < _SESSION_SECRET_MIN_LENGTH:
        raise RuntimeError(
            f"SESSION_SECRET must be at least {_SESSION_SECRET_MIN_LENGTH} characters long. "
            f"Got {len(session_secret)} characters. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    allow_insecure = os.environ.get("OAUTH_ALLOW_INSECURE", "0") == "1"

    redirect_uri = _require("OAUTH_REDIRECT_URI")
    authorize_url = os.environ.get("OAUTH_AUTHORIZE_URL", f"{issuer}/authorize")
    token_url = os.environ.get("OAUTH_TOKEN_URL", f"{issuer}/token")
    userinfo_url = os.environ.get("OAUTH_USERINFO_URL", f"{issuer}/userinfo")
    jwks_uri = os.environ.get("OAUTH_JWKS_URI", f"{issuer}/.well-known/jwks.json")

    # --- HTTPS enforcement + SSRF guard ---
    _validate_url("OAUTH_AUTHORIZE_URL / authorize_url", authorize_url, allow_insecure)
    _validate_url("OAUTH_TOKEN_URL / token_url", token_url, allow_insecure)
    _validate_url("OAUTH_USERINFO_URL / userinfo_url", userinfo_url, allow_insecure)
    _validate_url("OAUTH_REDIRECT_URI / redirect_uri", redirect_uri, allow_insecure)
    _validate_url("OAUTH_JWKS_URI / jwks_uri", jwks_uri, allow_insecure)

    return OAuthConfig(
        issuer=issuer,
        client_id=_require("OAUTH_CLIENT_ID"),
        client_secret=_require("OAUTH_CLIENT_SECRET"),
        redirect_uri=redirect_uri,
        session_secret=session_secret,
        authorize_url=authorize_url,
        token_url=token_url,
        userinfo_url=userinfo_url,
        jwks_uri=jwks_uri,
        allow_insecure=allow_insecure,
    )

"""
OAuth2 Authorization Code flow with PKCE helpers.

This module contains helpers for:

- Generating PKCE ``code_verifier`` / ``code_challenge`` pairs (S256 method).
- Generating cryptographically random ``state`` and ``nonce`` values.
- Building the authorization redirect URL.
- Validating ``id_token`` claims including **RSA signature verification** via
  JWKS (fetched from the provider and cached in-memory).
- Exchanging the authorization ``code`` for tokens via the token endpoint.
- Fetching the authenticated user profile from the userinfo endpoint.

JWKS caching
------------
A module-level ``_jwks_cache`` dict maps ``kid`` to a ``jwt.PyJWK`` object.
On an unknown ``kid``, the cache is refreshed once by re-fetching the JWKS
endpoint.  The cache is intentionally simple (no TTL) because JWKS rotation
is rare and a fresh fetch on unknown ``kid`` handles the rotation case.

The cache is bounded to ``_JWKS_CACHE_MAX_KEYS`` entries; when exceeded, the
oldest half of entries are evicted (simple FIFO).  This prevents unbounded
memory growth from cache-flooding attacks using novel ``kid`` values.

Concurrent JWKS fetches
-----------------------
A module-level ``asyncio.Lock`` (``_jwks_fetch_lock``) ensures that only one
coroutine fetches the JWKS endpoint at a time on a cache miss.  All other
concurrent waiters re-check the cache after acquiring the lock (double-checked
locking pattern) so that a single fetch satisfies all of them.

Algorithm allowlist
-------------------
Only asymmetric algorithms in ``_ALLOWED_ALGORITHMS`` are accepted.  The
``alg`` header from the JWT is validated against this set *before* any decode
attempt; tokens claiming ``alg: none`` or symmetric algorithms (e.g. HS256)
are rejected unconditionally.  The ``algorithms=`` argument passed to
``jwt.decode`` is always the full allowlist — never the header value — so
PyJWT cannot be tricked into accepting a downgraded algorithm.

The shared ``httpx.AsyncClient`` used for all outbound HTTP requests (token
exchange, userinfo, and JWKS) is passed in as a parameter so that callers
(FastAPI route handlers) can share a single pooled client.
"""

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient, PyJWKClientError

from auth.config import OAuthConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

_PKCE_VERIFIER_BYTES = 32  # 32 bytes → 43-char base64url, safely inside 43-128 range


def generate_code_verifier() -> str:
    """
    Return a cryptographically random PKCE ``code_verifier``.

    The verifier is base64url-encoded with no padding, yielding a 43-character
    string (``ceil(32 * 4/3)`` = 43 chars, within the RFC 7636 range of 43–128).
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(_PKCE_VERIFIER_BYTES)).rstrip(
        b"="
    ).decode("ascii")


def derive_code_challenge(verifier: str) -> str:
    """
    Derive the S256 ``code_challenge`` from *verifier*.

    S256: ``BASE64URL(SHA256(ASCII(code_verifier)))``
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# State / nonce helpers
# ---------------------------------------------------------------------------

_STATE_BYTES = 32
_NONCE_BYTES = 32


def generate_state() -> str:
    """Return a cryptographically random, URL-safe ``state`` parameter (CSRF token)."""
    return secrets.token_urlsafe(_STATE_BYTES)


def generate_nonce() -> str:
    """Return a cryptographically random ``nonce`` to bind the id_token to this session."""
    return secrets.token_urlsafe(_NONCE_BYTES)


# ---------------------------------------------------------------------------
# Authorization URL builder
# ---------------------------------------------------------------------------


def build_authorize_url(
    config: OAuthConfig,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    """
    Construct the full authorization URL to which the user will be redirected.

    The ``scope`` always includes ``openid`` so that an id_token is returned
    alongside the access token.
    """
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": config.scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{config.authorize_url}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# id_token claim validation with JWKS signature verification
# ---------------------------------------------------------------------------


class IDTokenValidationError(Exception):
    """Raised when id_token claims fail validation."""


# ---------------------------------------------------------------------------
# Algorithm allowlist (Fix 1)
# ---------------------------------------------------------------------------

# Only asymmetric algorithms are accepted.  The ``alg`` header from the JWT is
# validated against this set BEFORE any decode attempt.  Symmetric algorithms
# (HS256/384/512) and the ``none`` pseudo-algorithm are intentionally excluded.
_ALLOWED_ALGORITHMS: frozenset[str] = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
)

# Sorted list passed to jwt.decode — never derived from the token header.
_ALGORITHMS_FOR_DECODE: list[str] = sorted(_ALLOWED_ALGORITHMS)

# ---------------------------------------------------------------------------
# JWKS cache (Fix 2)
# ---------------------------------------------------------------------------

# In-memory JWKS cache: maps kid (str) → PyJWK object.
# Populated lazily; refreshed when an unknown kid is encountered.
_jwks_cache: dict[str, Any] = {}

# Maximum number of keys to keep in the cache.  When exceeded the oldest
# half are evicted (simple FIFO eviction to bound memory and prevent
# amplification via novel kid values).
_JWKS_CACHE_MAX_KEYS: int = 20

# Pattern that a valid kid must match.  Rejects empty strings, path-traversal
# sequences, and excessively long values that could be used to amplify cache
# lookups.
_KID_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# ---------------------------------------------------------------------------
# Single-flight lock for JWKS fetches (Fix 3)
# ---------------------------------------------------------------------------

# Acquired before any outbound JWKS fetch so that N concurrent callers on a
# cold cache (or after key rotation) each wait rather than triggering N
# parallel fetches (thundering herd / provider 429).
_jwks_fetch_lock: asyncio.Lock = asyncio.Lock()


def _evict_cache_if_full() -> None:
    """
    If ``_jwks_cache`` has reached ``_JWKS_CACHE_MAX_KEYS``, evict the oldest
    half of entries to keep memory bounded.
    """
    if len(_jwks_cache) >= _JWKS_CACHE_MAX_KEYS:
        evict_count = _JWKS_CACHE_MAX_KEYS // 2
        keys_to_evict = list(_jwks_cache.keys())[:evict_count]
        for k in keys_to_evict:
            del _jwks_cache[k]
        logger.debug("JWKS cache evicted %d oldest entries.", evict_count)


async def _fetch_jwks(jwks_uri: str, http_client: httpx.AsyncClient) -> dict:
    """
    Fetch and return the raw JWKS JSON dict from *jwks_uri*.

    Uses the shared *http_client* so connection pooling and timeouts are
    inherited from the application-level client configuration.

    Raises
    ------
    IDTokenValidationError
        If the JWKS fetch fails for any reason (network error, non-2xx response,
        or unparseable body).
    """
    try:
        response = await http_client.get(
            jwks_uri,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise IDTokenValidationError(
            f"Failed to fetch JWKS from '{jwks_uri}': {exc}"
        ) from exc


async def _get_signing_key(
    kid: str,
    jwks_uri: str,
    http_client: httpx.AsyncClient,
    *,
    allow_refresh: bool = True,
) -> Any:
    """
    Return the ``PyJWK`` signing key for *kid*, fetching/refreshing the cache
    as needed.

    Parameters
    ----------
    kid:
        The ``kid`` header value from the id_token.  Must already have been
        validated against ``_KID_PATTERN`` by the caller.
    jwks_uri:
        The provider's JWKS endpoint URL.
    http_client:
        The shared async HTTP client.
    allow_refresh:
        When True and *kid* is not in the cache, acquire ``_jwks_fetch_lock``
        and fetch the JWKS once; re-check the cache inside the lock before
        fetching (double-checked locking).  Set to False on recursive calls to
        prevent infinite loops.

    Raises
    ------
    IDTokenValidationError
        If the key cannot be found after at most one refresh.
    """
    # Fast path: cache hit (no lock needed for the read, Python's GIL and
    # asyncio's cooperative scheduling make this safe).
    if kid in _jwks_cache:
        return _jwks_cache[kid]

    if not allow_refresh:
        raise IDTokenValidationError(
            f"Unknown 'kid' '{kid}' in id_token header — key not found in JWKS."
        )

    # Slow path: cache miss — acquire the lock, then re-check inside (double-
    # checked locking) so that concurrent waiters don't all re-fetch.
    async with _jwks_fetch_lock:
        # Re-check: a previous waiter may have already populated the cache.
        if kid in _jwks_cache:
            return _jwks_cache[kid]

        logger.debug("kid '%s' not in JWKS cache; fetching %s", kid, jwks_uri)
        jwks_data = await _fetch_jwks(jwks_uri, http_client)

        # Rebuild cache from fresh JWKS payload.
        try:
            _evict_cache_if_full()
            for key_data in jwks_data.get("keys", []):
                try:
                    jwk_obj = jwt.PyJWK(key_data)
                    key_kid = key_data.get("kid", "")
                    _jwks_cache[key_kid] = jwk_obj
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Skipping unparseable JWK entry: %s", exc)
        except IDTokenValidationError:
            raise
        except Exception as exc:
            raise IDTokenValidationError(f"Failed to parse JWKS response: {exc}") from exc

    return await _get_signing_key(kid, jwks_uri, http_client, allow_refresh=False)


async def validate_id_token_claims(
    token: str,
    *,
    expected_issuer: str,
    expected_audience: str,
    expected_nonce: str,
    jwks_uri: str,
    http_client: httpx.AsyncClient,
    clock_skew_seconds: int = 30,
) -> dict:
    """
    Verify the RSA signature of *token* against the provider JWKS, then
    validate the standard OIDC claims and return the claim dict.

    Verification steps
    ------------------
    1. Decode the JWT header to extract ``kid`` and ``alg``.
    2. Validate ``kid`` format and ``alg`` against the allowlist; reject early
       if either is invalid (prevents algorithm confusion and cache flooding).
    3. Fetch the matching public key from the JWKS cache (refresh on miss,
       with single-flight lock to prevent thundering herd).
    4. Verify signature, ``iss``, ``aud``, and ``exp`` via ``PyJWT``, passing
       ``algorithms=_ALGORITHMS_FOR_DECODE`` (never the header value).
    5. Verify ``nonce`` (not handled by PyJWT).
    6. When ``azp`` is present (regardless of aud type), verify
       ``azp == client_id``.

    Parameters
    ----------
    token:
        The raw id_token JWT string received from the token endpoint.
    expected_issuer:
        The ``OAUTH_ISSUER`` value from configuration.
    expected_audience:
        The ``OAUTH_CLIENT_ID`` value from configuration.
    expected_nonce:
        The nonce stored in the session at the start of the login flow.
    jwks_uri:
        The provider's JWKS endpoint URL (used to fetch signing keys).
    http_client:
        The shared async HTTP client (for JWKS fetches).
    clock_skew_seconds:
        Tolerance for exp validation to account for minor clock drift.

    Returns
    -------
    dict
        The decoded and verified claims dictionary.

    Raises
    ------
    IDTokenValidationError
        On any signature or claim validation failure.
    """
    # --- Step 1: decode header to get kid and alg ---
    parts = token.split(".")
    if len(parts) != 3:
        raise IDTokenValidationError("Malformed id_token: expected 3 dot-separated parts.")

    try:
        header_b64 = parts[0]
        padding = 4 - len(header_b64) % 4
        if padding != 4:
            header_b64 += "=" * padding
        header = json.loads(base64.urlsafe_b64decode(header_b64))
    except Exception as exc:
        raise IDTokenValidationError(f"Failed to decode id_token header: {exc}") from exc

    kid = header.get("kid", "")
    alg = header.get("alg", "")

    # --- Step 2a: validate kid format (Fix 2) ---
    # Reject before cache lookup to prevent cache-flooding via arbitrary kids.
    if not _KID_PATTERN.match(kid):
        raise IDTokenValidationError(
            f"id_token 'kid' has invalid format: '{kid}'. "
            "Expected 1-128 alphanumeric characters, dots, underscores, or hyphens."
        )

    # --- Step 2b: algorithm allowlist check (Fix 1) ---
    # MUST be done before jwt.decode; the algorithms= argument to jwt.decode is
    # always _ALGORITHMS_FOR_DECODE (the full allowlist), never the header value.
    if alg not in _ALLOWED_ALGORITHMS:
        raise IDTokenValidationError(
            f"id_token 'alg' '{alg}' is not in the allowed algorithm set "
            f"{sorted(_ALLOWED_ALGORITHMS)}. Possible algorithm confusion attack."
        )

    # --- Step 3: resolve signing key from JWKS ---
    signing_key = await _get_signing_key(kid, jwks_uri, http_client)

    # --- Step 4: verify signature + iss + aud + exp via PyJWT ---
    # IMPORTANT: algorithms= is always the module-level allowlist constant,
    # never derived from the token header, to prevent algorithm confusion.
    try:
        claims: dict = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALGORITHMS_FOR_DECODE,
            issuer=expected_issuer,
            audience=expected_audience,
            leeway=clock_skew_seconds,
            options={
                "require": ["iss", "aud", "exp", "sub"],
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise IDTokenValidationError(f"id_token has expired: {exc}") from exc
    except jwt.InvalidIssuerError as exc:
        raise IDTokenValidationError(f"id_token 'iss' mismatch: {exc}") from exc
    except jwt.InvalidAudienceError as exc:
        raise IDTokenValidationError(f"id_token 'aud' mismatch: {exc}") from exc
    except jwt.InvalidSignatureError as exc:
        raise IDTokenValidationError(f"id_token signature verification failed: {exc}") from exc
    except jwt.DecodeError as exc:
        raise IDTokenValidationError(f"id_token decode error: {exc}") from exc
    except jwt.PyJWTError as exc:
        raise IDTokenValidationError(f"id_token validation error: {exc}") from exc

    # --- Step 5: nonce (not handled by PyJWT) ---
    nonce = claims.get("nonce")
    if nonce != expected_nonce:
        raise IDTokenValidationError(
            f"id_token 'nonce' mismatch: got '{nonce}', expected '{expected_nonce}'."
        )

    # --- Step 6: azp check whenever azp is present (Fix 4) ---
    # Per OIDC Core §3.1.3.7 rule 10, azp must equal the client_id if present,
    # regardless of whether aud is a string or a list.
    azp = claims.get("azp")
    if azp is not None and azp != expected_audience:
        raise IDTokenValidationError(
            f"id_token 'azp' mismatch: got '{azp}', expected '{expected_audience}'."
        )

    return claims


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


async def exchange_code_for_tokens(
    config: OAuthConfig,
    code: str,
    code_verifier: str,
    http_client: httpx.AsyncClient,
) -> dict:
    """
    POST to the token endpoint to exchange *code* + *code_verifier* for tokens.

    Parameters
    ----------
    config:
        The application OAuth configuration.
    code:
        The authorization code received from the provider callback.
    code_verifier:
        The PKCE code verifier generated at the start of the login flow.
    http_client:
        The shared async HTTP client.  Callers must provide a client constructed
        with appropriate timeouts (e.g. via the FastAPI lifespan handler).

    Returns
    -------
    dict
        The full token response dict (``access_token``, ``id_token``, etc.).

    Raises
    ------
    httpx.HTTPStatusError
        If the provider returns a non-2xx response.
    """
    response = await http_client.post(
        config.token_url,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code_verifier": code_verifier,
        },
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Userinfo fetch
# ---------------------------------------------------------------------------


async def fetch_userinfo(
    config: OAuthConfig,
    access_token: str,
    http_client: httpx.AsyncClient,
) -> dict:
    """
    GET the userinfo endpoint using *access_token* as a Bearer token.

    Parameters
    ----------
    config:
        The application OAuth configuration.
    access_token:
        The access token from the token response.
    http_client:
        The shared async HTTP client.  Callers must provide a client constructed
        with appropriate timeouts.

    Returns
    -------
    dict
        The userinfo JSON dict.

    Raises
    ------
    httpx.HTTPStatusError
        If the provider returns a non-2xx response.
    """
    response = await http_client.get(
        config.userinfo_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    response.raise_for_status()
    return response.json()

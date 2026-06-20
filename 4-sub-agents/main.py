"""
main.py — FastAPI application entrypoint.

OAuth2/OIDC Authorization Code + PKCE client.

Routes
------
GET /login           Start the login flow (generates PKCE/state/nonce, redirects to provider).
GET /auth/callback   Provider redirects here after authentication.
GET /logout          Clear the session.
GET /me              Return the authenticated user's profile (401 if not logged in).

Required environment variables
-------------------------------
OAUTH_ISSUER          Identity provider base URL.
OAUTH_CLIENT_ID       Registered client ID.
OAUTH_CLIENT_SECRET   Registered client secret.
OAUTH_REDIRECT_URI    Callback URL (must match provider registration).
SESSION_SECRET        Secret for signing session cookies (>=32 random chars required).

See auth/config.py for optional endpoint overrides.

Running locally
---------------
    uvicorn main:app --reload

Set environment variables first (never commit secrets):

    export OAUTH_ISSUER=https://your-idp.example.com
    export OAUTH_CLIENT_ID=myclientid
    export OAUTH_CLIENT_SECRET=mysecret
    export OAUTH_REDIRECT_URI=http://localhost:8000/auth/callback
    export OAUTH_ALLOW_INSECURE=1
    export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
"""

import hmac
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from auth.config import load_config
from auth.oauth import (
    IDTokenValidationError,
    build_authorize_url,
    derive_code_challenge,
    exchange_code_for_tokens,
    fetch_userinfo,
    generate_code_verifier,
    generate_nonce,
    generate_state,
    validate_id_token_claims,
)
from auth.session import (
    clear_session,
    get_authenticated_user,
    pop_oauth_params,
    set_authenticated_user,
    store_oauth_params,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Load config eagerly so a missing env var fails at startup, not at request time.
_config = load_config()

# ---------------------------------------------------------------------------
# Lifespan — shared pooled HTTP client
# ---------------------------------------------------------------------------

# Timeouts applied to every outbound request (token exchange, userinfo, JWKS).
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=2.0)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """
    FastAPI lifespan handler.

    Creates a single shared ``httpx.AsyncClient`` with connection pooling and
    explicit timeouts, stored on ``app.state.http_client``.  The client is
    closed cleanly on application shutdown.

    All outbound HTTP calls (token exchange, userinfo fetch, JWKS fetch) share
    this client so connections are pooled and timeouts are consistently applied.
    """
    application.state.http_client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
    logger.debug("HTTP client created (timeout=%s).", _HTTP_TIMEOUT)
    try:
        yield
    finally:
        await application.state.http_client.aclose()
        logger.debug("HTTP client closed.")


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="OAuth2/OIDC Client", version="1.0.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Session middleware
# ---------------------------------------------------------------------------

# In production, https_only=True enforces the Secure flag on the session cookie.
# Allow http:// only when the config (derived from OAUTH_ALLOW_INSECURE=1) says so.
# We consume _config.allow_insecure rather than re-reading the env var to ensure
# the https_only decision is always consistent with the URLs already validated
# by load_config().
app.add_middleware(
    SessionMiddleware,
    secret_key=_config.session_secret,
    # https_only enforces the Secure cookie flag; disable only for local dev.
    https_only=not _config.allow_insecure,
    # same_site="lax" prevents cross-site request forgery on top-level navigation.
    same_site="lax",
    # Absolute session expiry (seconds); prevents indefinitely-lived sessions.
    max_age=3600,
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/login", summary="Initiate OAuth2 Authorization Code + PKCE flow")
async def login(request: Request) -> RedirectResponse:
    """
    Generate PKCE verifier/challenge, CSRF state, and OIDC nonce; store them
    in the session; then redirect the user to the provider's authorization URL.

    The provider will redirect back to /auth/callback after authentication.
    """
    code_verifier = generate_code_verifier()
    code_challenge = derive_code_challenge(code_verifier)
    state = generate_state()
    nonce = generate_nonce()

    store_oauth_params(
        request,
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
    )

    authorize_url = build_authorize_url(
        _config,
        state=state,
        nonce=nonce,
        code_challenge=code_challenge,
    )

    logger.debug("Redirecting to authorization endpoint.")
    return RedirectResponse(url=authorize_url, status_code=302)


@app.get("/auth/callback", summary="OAuth2 callback — exchange code for tokens")
async def auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """
    1. Check for an ``error`` query parameter (provider-signalled failure).
    2. Validate ``state`` against the session (CSRF check).
    3. Exchange ``code`` + ``code_verifier`` for tokens at the token endpoint.
    4. Validate id_token signature and claims (iss, aud, exp, nonce).
    5. Cross-check userinfo ``sub`` against id_token ``sub``.
    6. Store the user profile in the session (rotating the cookie) and redirect to /me.

    One-time session values (state, nonce, verifier) are cleared after use.
    """
    # --- Step 1: provider-signalled error ---
    if error is not None:
        # Sanitize: only log the raw value; return a fixed message to the client
        # to avoid leaking provider-specific error detail through the response.
        logger.warning("OAuth provider returned error on callback: %s", error)
        raise HTTPException(
            status_code=400,
            detail="Authorization failed: provider returned an error.",
        )

    # Both code and state are required when no error is present.
    if code is None or state is None:
        raise HTTPException(
            status_code=400,
            detail="Missing required callback parameters.",
        )

    # --- retrieve and immediately consume the one-time session params ---
    try:
        session_state, session_nonce, code_verifier = pop_oauth_params(request)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail="Missing OAuth session state. Please restart the login flow.",
        )

    # --- CSRF: state must match (constant-time comparison) ---
    if not _constant_time_compare(state, session_state):
        raise HTTPException(
            status_code=400,
            detail="State mismatch — possible CSRF attack. Please restart the login flow.",
        )

    http_client: httpx.AsyncClient = request.app.state.http_client

    # --- exchange code for tokens ---
    try:
        token_response = await exchange_code_for_tokens(
            _config, code, code_verifier, http_client
        )
    except Exception as exc:
        logger.error("Token exchange failed: %s", exc)
        raise HTTPException(status_code=502, detail="Token exchange with provider failed.")

    id_token: str | None = token_response.get("id_token")
    if not id_token:
        raise HTTPException(status_code=502, detail="Provider did not return an id_token.")

    access_token: str | None = token_response.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="Provider did not return an access_token.")

    # --- validate id_token signature + claims ---
    try:
        id_token_claims = await validate_id_token_claims(
            id_token,
            expected_issuer=_config.issuer,
            expected_audience=_config.client_id,
            expected_nonce=session_nonce,
            jwks_uri=_config.jwks_uri,
            http_client=http_client,
        )
    except IDTokenValidationError as exc:
        # Log full detail for diagnostics; return a fixed message to the client
        # to avoid leaking internal token details through the HTTP response.
        logger.warning("id_token validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="id_token validation failed.")

    # --- fetch userinfo ---
    try:
        user_profile = await fetch_userinfo(_config, access_token, http_client)
    except Exception as exc:
        logger.error("Userinfo fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="Userinfo fetch from provider failed.")

    # --- cross-check userinfo sub == id_token sub ---
    id_token_sub = id_token_claims.get("sub")
    userinfo_sub = user_profile.get("sub")
    if id_token_sub != userinfo_sub:
        logger.warning(
            "sub mismatch: id_token sub='%s', userinfo sub='%s'", id_token_sub, userinfo_sub
        )
        raise HTTPException(
            status_code=401,
            detail="id_token validation failed.",
        )

    # --- session fixation mitigation: rotate the session cookie ---
    # Capture post-login values, clear the old session (so the signed cookie
    # value changes), then repopulate.  Starlette re-signs the cookie on the
    # next response, giving the authenticated session a fresh value.
    post_login_user = dict(user_profile)
    request.session.clear()
    set_authenticated_user(request, post_login_user)

    logger.info("User authenticated: %s", post_login_user.get("sub", "<unknown>"))

    return RedirectResponse(url="/me", status_code=302)


@app.get("/logout", summary="Clear the session and log out")
async def logout(request: Request) -> JSONResponse:
    """
    Clear the server-side session.  The signed session cookie is overwritten
    with an empty value by Starlette's SessionMiddleware.
    """
    clear_session(request)
    return JSONResponse({"message": "Logged out successfully."})


@app.get("/me", summary="Return the authenticated user's profile")
async def me(request: Request) -> JSONResponse:
    """
    Return the authenticated user's profile dict.

    Returns 401 if no authenticated session exists.
    """
    user = get_authenticated_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated. Please visit /login.")
    return JSONResponse(user)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _constant_time_compare(a: str, b: str) -> bool:
    """
    Constant-time string comparison to prevent timing-based state oracle attacks.

    Delegates to :func:`hmac.compare_digest` which operates in constant time
    regardless of where the strings differ.
    """
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))

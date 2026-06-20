"""
auth — OAuth2/OIDC Authorization Code + PKCE client package.

Sub-modules
-----------
config   — Environment-based configuration (OAuthConfig, load_config).
oauth    — Pure flow helpers: PKCE, state/nonce generation, id_token
           claim validation, token exchange, userinfo fetch.
session  — Starlette session read/write helpers for the OAuth flow state
           and the authenticated user profile.
"""

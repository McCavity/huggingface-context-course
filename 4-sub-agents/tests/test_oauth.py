"""
Tests for security-critical logic in auth/oauth.py, auth/config.py, and main.py.

Coverage
--------
PKCE
  - code_verifier format and S256 challenge derivation.

State / nonce
  - Entropy and uniqueness.

id_token claim validation (JWKS-based)
  - Valid RSA-signed token passes.
  - Tampered signature (wrong private key) is rejected.
  - Tampered payload (claims modified after signing) is rejected.
  - Unknown kid triggers a JWKS refresh; key found after refresh passes.
  - Unknown kid after refresh still raises IDTokenValidationError.
  - Expired token raises.
  - Wrong iss raises.
  - Wrong aud raises.
  - Nonce mismatch raises.
  - Malformed token raises.
  - aud-as-list happy path passes.
  - aud-as-list missing client_id raises.
  - azp present and matching passes.
  - azp present but wrong raises (aud as list).
  - azp present but wrong raises (aud as string — Fix 4).
  - userinfo sub != id_token sub triggers 401 in callback.

Algorithm allowlist (Fix 1)
  - alg:none is rejected before jwt.decode.
  - alg:HS256 is rejected before jwt.decode.
  - Valid RS256 token still passes.

kid format validation (Fix 2)
  - Malformed kid (special chars) is rejected.
  - Empty kid is rejected.
  - Excessively long kid is rejected.

HTTPS enforcement
  - https:// URLs are always accepted.
  - http://localhost accepted with OAUTH_ALLOW_INSECURE=1.
  - http://other-host rejected even with OAUTH_ALLOW_INSECURE=1.
  - http:// rejected without OAUTH_ALLOW_INSECURE flag.

SESSION_SECRET min length
  - Short secret raises RuntimeError.
  - Exactly 32 chars passes.

OAuth error param
  - Callback with error= returns 400 before processing code.

Session fixation (Fix 6 — real test)
  - request.session is cleared before set_authenticated_user is called in the
    callback route; the session at call time contains no pre-login oauth_ keys.
  - The user profile is correctly stored after the clear.

https_only gating (Fix 5 — single source for insecure flag)
  - SessionMiddleware uses https_only=True without OAUTH_ALLOW_INSECURE.
  - https_only=False with OAUTH_ALLOW_INSECURE=1.
  - config.allow_insecure reflects the env var (not a separate re-read).

Generic 401 detail
  - IDTokenValidationError detail in response is fixed string, not exception text.

No real network calls are made.  RSA keypairs are generated in-process for tests.
"""

import base64
import hashlib
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from auth.oauth import (
    IDTokenValidationError,
    _jwks_cache,
    derive_code_challenge,
    generate_code_verifier,
    generate_nonce,
    generate_state,
    validate_id_token_claims,
)

# ---------------------------------------------------------------------------
# RSA keypair fixtures shared across all signature tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rsa_keypair():
    """Generate a 2048-bit RSA keypair once per test module."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture(scope="module")
def rsa_keypair_other():
    """A second RSA keypair used to test signature rejection."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    return private_key


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_TEST_KID = "test-key-1"
_TEST_ISS = "https://idp.example.com"
_TEST_AUD = "myclient"
_TEST_NONCE = "secret-nonce-value"
_TEST_JWKS_URI = "https://idp.example.com/.well-known/jwks.json"


def _b64url_encode(data: bytes) -> str:
    """base64url-encode without padding (matches JWT convention)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _valid_claims(
    *,
    iss: str = _TEST_ISS,
    aud=_TEST_AUD,
    nonce: str = _TEST_NONCE,
    sub: str = "user-123",
    exp_offset: int = 600,
    extra: dict | None = None,
) -> dict:
    """Return a valid claims dict that should pass all checks."""
    claims = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
        "nonce": nonce,
    }
    if extra:
        claims.update(extra)
    return claims


def _sign_token(claims: dict, private_key, kid: str = _TEST_KID) -> str:
    """Sign *claims* with *private_key* using RS256 and embed *kid* in the header."""
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _make_jwks_response(public_key, kid: str = _TEST_KID) -> dict:
    """Build a minimal JWKS dict for *public_key* with *kid*."""
    from jwt.algorithms import RSAAlgorithm

    jwk_dict = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk_dict["kid"] = kid
    jwk_dict["use"] = "sig"
    return {"keys": [jwk_dict]}


def _make_mock_http_client(jwks_response: dict) -> AsyncMock:
    """
    Return an AsyncMock http_client whose ``.get()`` returns a mocked JWKS response.
    """
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=jwks_response)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)
    return mock_client


async def _validate(
    token: str,
    http_client,
    *,
    iss: str = _TEST_ISS,
    aud: str = _TEST_AUD,
    nonce: str = _TEST_NONCE,
    jwks_uri: str = _TEST_JWKS_URI,
) -> dict:
    """Thin wrapper around validate_id_token_claims for test convenience."""
    return await validate_id_token_claims(
        token,
        expected_issuer=iss,
        expected_audience=aud,
        expected_nonce=nonce,
        jwks_uri=jwks_uri,
        http_client=http_client,
    )


# ---------------------------------------------------------------------------
# PKCE: code_verifier
# ---------------------------------------------------------------------------


class TestGenerateCodeVerifier:
    def test_returns_string(self):
        assert isinstance(generate_code_verifier(), str)

    def test_length_is_43(self):
        # 32 bytes → base64url without padding = 43 chars
        verifier = generate_code_verifier()
        assert len(verifier) == 43

    def test_is_ascii(self):
        verifier = generate_code_verifier()
        verifier.encode("ascii")  # must not raise

    def test_contains_only_base64url_chars(self):
        import re
        verifier = generate_code_verifier()
        assert re.fullmatch(r"[A-Za-z0-9_\-]+", verifier), (
            f"verifier contains non-base64url characters: {verifier!r}"
        )

    def test_unique_on_each_call(self):
        verifiers = {generate_code_verifier() for _ in range(100)}
        assert len(verifiers) == 100, "code_verifiers are not unique"


# ---------------------------------------------------------------------------
# PKCE: S256 challenge derivation
# ---------------------------------------------------------------------------


class TestDeriveCodeChallenge:
    def test_known_vector(self):
        """
        RFC 7636 Appendix B example:
          verifier  = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
          challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        """
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        assert derive_code_challenge(verifier) == expected

    def test_s256_formula(self):
        """Verify the implementation matches BASE64URL(SHA256(ASCII(verifier)))."""
        verifier = generate_code_verifier()
        expected = (
            base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        assert derive_code_challenge(verifier) == expected

    def test_challenge_is_not_equal_to_verifier(self):
        verifier = generate_code_verifier()
        challenge = derive_code_challenge(verifier)
        assert verifier != challenge

    def test_challenge_length_is_43(self):
        # SHA-256 → 32 bytes → base64url without padding = 43 chars
        challenge = derive_code_challenge(generate_code_verifier())
        assert len(challenge) == 43

    def test_challenge_has_no_padding(self):
        challenge = derive_code_challenge(generate_code_verifier())
        assert "=" not in challenge


# ---------------------------------------------------------------------------
# State / nonce generation
# ---------------------------------------------------------------------------


class TestGenerateState:
    def test_returns_string(self):
        assert isinstance(generate_state(), str)

    def test_minimum_length(self):
        # 32 bytes of entropy → token_urlsafe → ~43 chars minimum
        state = generate_state()
        assert len(state) >= 40

    def test_unique_on_each_call(self):
        states = {generate_state() for _ in range(200)}
        assert len(states) == 200


class TestGenerateNonce:
    def test_returns_string(self):
        assert isinstance(generate_nonce(), str)

    def test_minimum_length(self):
        nonce = generate_nonce()
        assert len(nonce) >= 40

    def test_unique_on_each_call(self):
        nonces = {generate_nonce() for _ in range(200)}
        assert len(nonces) == 200

    def test_state_and_nonce_are_different(self):
        # They should almost never collide; test a few pairs.
        for _ in range(20):
            assert generate_state() != generate_nonce()


# ---------------------------------------------------------------------------
# id_token claim validation — RSA signature verification
# ---------------------------------------------------------------------------


class TestValidateIDTokenClaimsSignature:
    """Tests that exercise the full JWKS-based signature verification path."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Ensure the module-level JWKS cache is empty before each test."""
        _jwks_cache.clear()
        yield
        _jwks_cache.clear()

    async def test_valid_signed_token_passes(self, rsa_keypair):
        """A properly signed token with correct claims should validate."""
        private_key, public_key = rsa_keypair
        claims = _valid_claims()
        token = _sign_token(claims, private_key)
        jwks = _make_jwks_response(public_key)
        http_client = _make_mock_http_client(jwks)

        result = await _validate(token, http_client)
        assert result["sub"] == "user-123"
        assert result["iss"] == _TEST_ISS

    async def test_wrong_private_key_rejected(self, rsa_keypair, rsa_keypair_other):
        """A token signed with a different key must be rejected."""
        _, public_key = rsa_keypair
        other_private_key = rsa_keypair_other

        claims = _valid_claims()
        # Sign with the *other* key but present the *correct* public key in JWKS.
        token = _sign_token(claims, other_private_key)
        jwks = _make_jwks_response(public_key)  # correct public key → mismatch
        http_client = _make_mock_http_client(jwks)

        with pytest.raises(IDTokenValidationError, match="signature"):
            await _validate(token, http_client)

    async def test_tampered_payload_rejected(self, rsa_keypair):
        """
        A token whose payload is replaced after signing must be rejected.
        The signature no longer matches the modified payload.
        """
        private_key, public_key = rsa_keypair
        good_claims = _valid_claims()
        token = _sign_token(good_claims, private_key)

        # Replace the payload with a tampered version (different iss).
        evil_claims = dict(good_claims)
        evil_claims["iss"] = "https://evil.example.com"
        evil_payload = _b64url_encode(json.dumps(evil_claims).encode())
        header, _, sig = token.split(".")
        tampered_token = f"{header}.{evil_payload}.{sig}"

        jwks = _make_jwks_response(public_key)
        http_client = _make_mock_http_client(jwks)

        with pytest.raises(IDTokenValidationError):
            await _validate(tampered_token, http_client)

    async def test_unknown_kid_triggers_refresh_and_passes(self, rsa_keypair):
        """
        When the cache is empty (unknown kid), the JWKS endpoint is fetched
        once.  If the key is found after refresh, validation should pass.
        """
        private_key, public_key = rsa_keypair
        claims = _valid_claims()
        token = _sign_token(claims, private_key)
        jwks = _make_jwks_response(public_key)
        http_client = _make_mock_http_client(jwks)

        # Cache is already cleared by autouse fixture; kid not present.
        result = await _validate(token, http_client)
        assert result["sub"] == "user-123"
        # JWKS should have been fetched exactly once.
        http_client.get.assert_called_once()

    async def test_unknown_kid_after_refresh_raises(self, rsa_keypair):
        """
        When the kid is not present even after a JWKS refresh, raise
        IDTokenValidationError rather than looping indefinitely.
        """
        private_key, public_key = rsa_keypair

        different_kid = "some-unknown-kid"
        claims = _valid_claims()
        token = _sign_token(claims, private_key, kid=different_kid)

        # JWKS contains a key with a *different* kid so the lookup will fail.
        jwks = _make_jwks_response(public_key, kid="other-kid")
        http_client = _make_mock_http_client(jwks)

        with pytest.raises(IDTokenValidationError, match="[Uu]nknown.*kid|kid.*[Uu]nknown"):
            await _validate(token, http_client)


# ---------------------------------------------------------------------------
# id_token claim validation — standard claim checks
# ---------------------------------------------------------------------------


class TestValidateIDTokenClaims:
    """Tests for iss/aud/exp/nonce claim checks (use a valid signature)."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _jwks_cache.clear()
        yield
        _jwks_cache.clear()

    @pytest.fixture
    def http_client(self, rsa_keypair):
        _, public_key = rsa_keypair
        jwks = _make_jwks_response(public_key)
        return _make_mock_http_client(jwks)

    def _make_token(self, claims: dict, rsa_keypair) -> str:
        private_key, _ = rsa_keypair
        return _sign_token(claims, private_key)

    async def test_happy_path_returns_claims(self, rsa_keypair, http_client):
        token = self._make_token(_valid_claims(), rsa_keypair)
        result = await _validate(token, http_client)
        assert result["sub"] == "user-123"
        assert result["iss"] == _TEST_ISS

    async def test_aud_as_list_containing_client_id(self, rsa_keypair, http_client):
        """aud claim may be a list per OIDC spec; client_id must be in it."""
        claims = _valid_claims(aud=[_TEST_AUD, "other-service"])
        token = self._make_token(claims, rsa_keypair)
        result = await _validate(token, http_client)
        assert result["sub"] == "user-123"

    # --- iss failures ---

    async def test_wrong_iss_raises(self, rsa_keypair, http_client):
        claims = _valid_claims(iss="https://evil.example.com")
        token = self._make_token(claims, rsa_keypair)
        with pytest.raises(IDTokenValidationError, match="'iss'"):
            await _validate(token, http_client)

    async def test_missing_iss_raises(self, rsa_keypair, http_client):
        claims = _valid_claims()
        del claims["iss"]
        # PyJWT requires iss when issuer is specified; it raises MissingRequiredClaimError.
        token = self._make_token(claims, rsa_keypair)
        with pytest.raises(IDTokenValidationError):
            await _validate(token, http_client)

    # --- aud failures ---

    async def test_wrong_aud_string_raises(self, rsa_keypair, http_client):
        claims = _valid_claims(aud="completely-different-client")
        token = self._make_token(claims, rsa_keypair)
        with pytest.raises(IDTokenValidationError, match="'aud'"):
            await _validate(token, http_client)

    async def test_aud_list_missing_client_id_raises(self, rsa_keypair, http_client):
        claims = _valid_claims(aud=["some-other-service", "another-service"])
        token = self._make_token(claims, rsa_keypair)
        with pytest.raises(IDTokenValidationError, match="'aud'"):
            await _validate(token, http_client)

    # --- exp failures ---

    async def test_expired_token_raises(self, rsa_keypair, http_client):
        # exp = 120 seconds in the past, well outside clock_skew_seconds=30
        claims = _valid_claims(exp_offset=-120)
        token = self._make_token(claims, rsa_keypair)
        with pytest.raises(IDTokenValidationError, match="expired"):
            await _validate(token, http_client)

    async def test_missing_exp_raises(self, rsa_keypair, http_client):
        claims = _valid_claims()
        del claims["exp"]
        token = self._make_token(claims, rsa_keypair)
        with pytest.raises(IDTokenValidationError):
            await _validate(token, http_client)

    async def test_just_within_clock_skew_passes(self, rsa_keypair, http_client):
        """A token expired 10s ago should still pass with default skew of 30s."""
        claims = _valid_claims(exp_offset=-10)
        token = self._make_token(claims, rsa_keypair)
        result = await _validate(token, http_client)
        assert result["iss"] == _TEST_ISS

    async def test_just_outside_clock_skew_fails(self, rsa_keypair, http_client):
        """A token expired 60s ago should fail even with default skew of 30s."""
        claims = _valid_claims(exp_offset=-60)
        token = self._make_token(claims, rsa_keypair)
        with pytest.raises(IDTokenValidationError, match="expired"):
            await _validate(token, http_client)

    # --- nonce failures ---

    async def test_wrong_nonce_raises(self, rsa_keypair, http_client):
        claims = _valid_claims(nonce="tampered-nonce")
        token = self._make_token(claims, rsa_keypair)
        with pytest.raises(IDTokenValidationError, match="'nonce'"):
            await _validate(token, http_client)

    async def test_missing_nonce_raises(self, rsa_keypair, http_client):
        claims = _valid_claims()
        del claims["nonce"]
        token = self._make_token(claims, rsa_keypair)
        with pytest.raises(IDTokenValidationError, match="'nonce'"):
            await _validate(token, http_client)

    # --- structural / malformed ---

    async def test_malformed_token_not_three_parts_raises(self, http_client):
        with pytest.raises(IDTokenValidationError, match="3 dot-separated parts"):
            await _validate("only.two", http_client)

    # --- azp checks ---

    async def test_azp_matching_client_id_passes(self, rsa_keypair, http_client):
        """When aud is a list and azp matches client_id, validation passes."""
        claims = _valid_claims(
            aud=[_TEST_AUD, "other-service"],
            extra={"azp": _TEST_AUD},
        )
        token = self._make_token(claims, rsa_keypair)
        result = await _validate(token, http_client)
        assert result["sub"] == "user-123"

    async def test_azp_wrong_value_raises(self, rsa_keypair, http_client):
        """When aud is a list and azp does not match client_id, raise."""
        claims = _valid_claims(
            aud=[_TEST_AUD, "other-service"],
            extra={"azp": "rogue-client"},
        )
        token = self._make_token(claims, rsa_keypair)
        with pytest.raises(IDTokenValidationError, match="'azp'"):
            await _validate(token, http_client)

    async def test_azp_absent_with_list_aud_passes(self, rsa_keypair, http_client):
        """azp is optional; omitting it when aud is a list is fine."""
        claims = _valid_claims(aud=[_TEST_AUD, "other-service"])
        # No 'azp' key in claims.
        token = self._make_token(claims, rsa_keypair)
        result = await _validate(token, http_client)
        assert result["sub"] == "user-123"


# ---------------------------------------------------------------------------
# Algorithm allowlist (Fix 1)
# ---------------------------------------------------------------------------


class TestAlgorithmAllowlist:
    """
    Tokens whose header 'alg' is not in the asymmetric-algorithm allowlist must
    be rejected BEFORE jwt.decode is called, preventing algorithm confusion
    attacks (alg:none bypass, HS256 downgrade).
    """

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _jwks_cache.clear()
        yield
        _jwks_cache.clear()

    def _craft_token_with_alg(self, alg: str, claims: dict) -> str:
        """
        Build a JWT token with an arbitrary alg header value.

        Both ``none`` and ``HS256`` tokens include a syntactically valid ``kid``
        (``_TEST_KID``) so the kid validation passes and the alg allowlist check
        is the first rejection point.  We don't need a real signature because
        rejection must happen before ``jwt.decode`` is attempted.
        """
        if alg == "none":
            # alg:none token — no signature, third segment is empty.
            # Include a valid kid so kid validation passes; alg check fires next.
            header = _b64url_encode(
                json.dumps({"alg": "none", "typ": "JWT", "kid": _TEST_KID}).encode()
            )
            payload = _b64url_encode(json.dumps(claims).encode())
            return f"{header}.{payload}."
        elif alg == "HS256":
            # alg:HS256 — symmetric algorithm, not in the allowlist.
            header = _b64url_encode(
                json.dumps({"alg": "HS256", "typ": "JWT", "kid": _TEST_KID}).encode()
            )
            payload = _b64url_encode(json.dumps(claims).encode())
            fake_sig = _b64url_encode(b"fakesignature")
            return f"{header}.{payload}.{fake_sig}"
        else:
            raise ValueError(f"Unsupported test alg: {alg}")

    async def test_alg_none_rejected(self, rsa_keypair):
        """A token claiming alg:none must be rejected with IDTokenValidationError."""
        _, public_key = rsa_keypair
        jwks = _make_jwks_response(public_key)
        http_client = _make_mock_http_client(jwks)

        claims = _valid_claims()
        token = self._craft_token_with_alg("none", claims)

        with pytest.raises(IDTokenValidationError, match="alg"):
            await _validate(token, http_client)

        # JWKS fetch must NOT have been triggered; the alg check is before key lookup.
        http_client.get.assert_not_called()

    async def test_alg_hs256_rejected(self, rsa_keypair):
        """A token claiming alg:HS256 must be rejected (symmetric alg not allowed)."""
        _, public_key = rsa_keypair
        jwks = _make_jwks_response(public_key)
        http_client = _make_mock_http_client(jwks)

        claims = _valid_claims()
        token = self._craft_token_with_alg("HS256", claims)

        with pytest.raises(IDTokenValidationError, match="alg"):
            await _validate(token, http_client)

        # Rejection must happen before any JWKS fetch.
        http_client.get.assert_not_called()

    async def test_valid_rs256_still_passes(self, rsa_keypair):
        """RS256 is in the allowlist; a properly signed RS256 token must pass."""
        private_key, public_key = rsa_keypair
        jwks = _make_jwks_response(public_key)
        http_client = _make_mock_http_client(jwks)

        claims = _valid_claims()
        token = _sign_token(claims, private_key)  # RS256 by default

        result = await _validate(token, http_client)
        assert result["sub"] == "user-123"


# ---------------------------------------------------------------------------
# kid format validation (Fix 2)
# ---------------------------------------------------------------------------


class TestKidFormatValidation:
    """
    Tokens with a malformed kid header must be rejected before any cache lookup
    or JWKS fetch to prevent cache-flooding / amplification attacks.
    """

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _jwks_cache.clear()
        yield
        _jwks_cache.clear()

    def _craft_token_with_kid(self, kid: str, private_key) -> str:
        """Sign a valid claims dict but override the kid header to *kid*."""
        claims = _valid_claims()
        return jwt.encode(
            claims,
            private_key,
            algorithm="RS256",
            headers={"kid": kid},
        )

    async def test_malformed_kid_special_chars_rejected(self, rsa_keypair):
        """A kid containing path-traversal characters must be rejected."""
        private_key, public_key = rsa_keypair
        jwks = _make_jwks_response(public_key)
        http_client = _make_mock_http_client(jwks)

        token = self._craft_token_with_kid("../../etc/passwd", private_key)

        with pytest.raises(IDTokenValidationError, match="[Kk]id"):
            await _validate(token, http_client)

        # No JWKS fetch should have occurred.
        http_client.get.assert_not_called()

    async def test_empty_kid_rejected(self, rsa_keypair):
        """An empty kid string must be rejected."""
        private_key, public_key = rsa_keypair
        jwks = _make_jwks_response(public_key)
        http_client = _make_mock_http_client(jwks)

        token = self._craft_token_with_kid("", private_key)

        with pytest.raises(IDTokenValidationError, match="[Kk]id"):
            await _validate(token, http_client)

        http_client.get.assert_not_called()

    async def test_excessively_long_kid_rejected(self, rsa_keypair):
        """A kid longer than 128 characters must be rejected."""
        private_key, public_key = rsa_keypair
        jwks = _make_jwks_response(public_key)
        http_client = _make_mock_http_client(jwks)

        long_kid = "a" * 129
        token = self._craft_token_with_kid(long_kid, private_key)

        with pytest.raises(IDTokenValidationError, match="[Kk]id"):
            await _validate(token, http_client)

        http_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# azp with string aud (Fix 4)
# ---------------------------------------------------------------------------


class TestAzpWithStringAud:
    """
    Per OIDC Core §3.1.3.7 rule 10, azp must equal client_id whenever it is
    present — regardless of whether aud is a string or a list.
    """

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _jwks_cache.clear()
        yield
        _jwks_cache.clear()

    @pytest.fixture
    def http_client(self, rsa_keypair):
        _, public_key = rsa_keypair
        jwks = _make_jwks_response(public_key)
        return _make_mock_http_client(jwks)

    async def test_azp_mismatch_with_string_aud_raises(self, rsa_keypair, http_client):
        """
        When aud is a plain string (not a list) and azp is present but wrong,
        validation must raise IDTokenValidationError.
        """
        private_key, _ = rsa_keypair
        claims = _valid_claims(
            aud=_TEST_AUD,           # string, not a list
            extra={"azp": "rogue-client"},
        )
        token = _sign_token(claims, private_key)

        with pytest.raises(IDTokenValidationError, match="'azp'"):
            await _validate(token, http_client)

    async def test_azp_matching_with_string_aud_passes(self, rsa_keypair, http_client):
        """When aud is a string and azp matches client_id, validation passes."""
        private_key, _ = rsa_keypair
        claims = _valid_claims(
            aud=_TEST_AUD,
            extra={"azp": _TEST_AUD},
        )
        token = _sign_token(claims, private_key)

        result = await _validate(token, http_client)
        assert result["sub"] == "user-123"


# ---------------------------------------------------------------------------
# HTTPS enforcement + SSRF guard
# ---------------------------------------------------------------------------


class TestHttpsEnforcement:
    """Tests for URL security validation in load_config()."""

    _BASE_ENV = {
        "OAUTH_ISSUER": "https://idp.example.com",
        "OAUTH_CLIENT_ID": "myclient",
        "OAUTH_CLIENT_SECRET": "mysecret",
        "OAUTH_REDIRECT_URI": "https://app.example.com/auth/callback",
        "SESSION_SECRET": "a" * 32,
    }

    def _load(self, overrides: dict, monkeypatch):
        env = {**self._BASE_ENV, **overrides}
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        # Remove keys set to None.
        for k, v in overrides.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
        from auth.config import load_config
        return load_config()

    def test_all_https_passes(self, monkeypatch):
        cfg = self._load({}, monkeypatch)
        assert cfg.issuer == "https://idp.example.com"

    def test_http_localhost_allowed_with_insecure_flag(self, monkeypatch):
        cfg = self._load(
            {
                "OAUTH_ISSUER": "http://localhost:8080",
                "OAUTH_REDIRECT_URI": "http://localhost:8000/auth/callback",
                "OAUTH_ALLOW_INSECURE": "1",
            },
            monkeypatch,
        )
        assert cfg.issuer == "http://localhost:8080"

    def test_http_127_0_0_1_allowed_with_insecure_flag(self, monkeypatch):
        cfg = self._load(
            {
                "OAUTH_ISSUER": "http://127.0.0.1:9000",
                "OAUTH_REDIRECT_URI": "http://127.0.0.1:8000/auth/callback",
                "OAUTH_ALLOW_INSECURE": "1",
            },
            monkeypatch,
        )
        assert cfg.issuer == "http://127.0.0.1:9000"

    def test_http_non_localhost_rejected_even_with_insecure_flag(self, monkeypatch):
        with pytest.raises(RuntimeError, match="https://"):
            self._load(
                {
                    "OAUTH_ISSUER": "http://idp.example.com",
                    "OAUTH_ALLOW_INSECURE": "1",
                },
                monkeypatch,
            )

    def test_http_rejected_without_insecure_flag(self, monkeypatch):
        with pytest.raises(RuntimeError, match="https://"):
            self._load(
                {
                    "OAUTH_REDIRECT_URI": "http://localhost:8000/auth/callback",
                },
                monkeypatch,
            )

    def test_http_override_url_rejected(self, monkeypatch):
        with pytest.raises(RuntimeError, match="https://"):
            self._load(
                {"OAUTH_TOKEN_URL": "http://evil.example.com/token"},
                monkeypatch,
            )

    def test_jwks_uri_validated(self, monkeypatch):
        with pytest.raises(RuntimeError, match="https://"):
            self._load(
                {"OAUTH_JWKS_URI": "http://evil.example.com/jwks"},
                monkeypatch,
            )


# ---------------------------------------------------------------------------
# SESSION_SECRET minimum length
# ---------------------------------------------------------------------------


class TestSessionSecretMinLength:
    _BASE_ENV = {
        "OAUTH_ISSUER": "https://idp.example.com",
        "OAUTH_CLIENT_ID": "myclient",
        "OAUTH_CLIENT_SECRET": "mysecret",
        "OAUTH_REDIRECT_URI": "https://app.example.com/auth/callback",
    }

    def _load(self, secret: str, monkeypatch):
        env = {**self._BASE_ENV, "SESSION_SECRET": secret}
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        from auth.config import load_config
        return load_config()

    def test_short_secret_raises(self, monkeypatch):
        with pytest.raises(RuntimeError, match="SESSION_SECRET must be at least 32"):
            self._load("tooshort", monkeypatch)

    def test_31_chars_raises(self, monkeypatch):
        with pytest.raises(RuntimeError, match="SESSION_SECRET must be at least 32"):
            self._load("a" * 31, monkeypatch)

    def test_exactly_32_chars_passes(self, monkeypatch):
        cfg = self._load("a" * 32, monkeypatch)
        assert len(cfg.session_secret) == 32

    def test_longer_than_32_chars_passes(self, monkeypatch):
        cfg = self._load("a" * 64, monkeypatch)
        assert len(cfg.session_secret) == 64


# ---------------------------------------------------------------------------
# FastAPI route / integration tests
# ---------------------------------------------------------------------------

# Shared environment for route tests.
_ROUTE_ENV = {
    "OAUTH_ISSUER": "https://idp.example.com",
    "OAUTH_CLIENT_ID": "myclient",
    "OAUTH_CLIENT_SECRET": "mysecret",
    "OAUTH_REDIRECT_URI": "https://idp.example.com/auth/callback",
    "SESSION_SECRET": "a" * 32,
    "OAUTH_ALLOW_INSECURE": "1",
}


def _route_app():
    """Re-import and return a fresh app instance with test env vars set."""
    import sys

    # Purge cached modules so load_config() re-reads env vars.
    for mod in list(sys.modules.keys()):
        if mod.startswith("auth") or mod == "main":
            del sys.modules[mod]

    import main  # noqa: PLC0415
    return main.app


# ---------------------------------------------------------------------------
# OAuth error parameter on callback
# ---------------------------------------------------------------------------


class TestCallbackErrorParam:
    def test_error_param_returns_400(self, monkeypatch):
        for k, v in _ROUTE_ENV.items():
            monkeypatch.setenv(k, v)

        app = _route_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/auth/callback",
                params={"error": "access_denied", "error_description": "User denied access."},
                follow_redirects=False,
            )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "error" in detail.lower() or "failed" in detail.lower()

    def test_error_param_without_code_returns_400(self, monkeypatch):
        for k, v in _ROUTE_ENV.items():
            monkeypatch.setenv(k, v)

        app = _route_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/auth/callback",
                params={"error": "server_error"},
                follow_redirects=False,
            )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Generic 401 detail
# ---------------------------------------------------------------------------


class TestGeneric401Detail:
    """The exception message must NOT be interpolated into the HTTP response."""

    def test_id_token_failure_returns_fixed_message(self, monkeypatch, rsa_keypair):
        """
        Arrange a valid token exchange but with a mismatched signature, then
        confirm the callback returns the fixed string 'id_token validation failed.'
        and does not leak exception internals.

        Session seeding is bypassed by patching pop_oauth_params and
        _constant_time_compare so we can get through the state/session check
        and reach the actual id_token validation logic.
        """
        for k, v in _ROUTE_ENV.items():
            monkeypatch.setenv(k, v)

        _, public_key = rsa_keypair
        _jwks_cache.clear()

        app = _route_app()

        async def fake_exchange(config, code, verifier, http_client):
            # Sign with a *different* private key so sig verification fails.
            bad_private_key = rsa.generate_private_key(
                public_exponent=65537, key_size=2048
            )
            bad_token = _sign_token(
                _valid_claims(iss=config.issuer, aud=config.client_id, nonce="test-nonce"),
                bad_private_key,
            )
            return {"id_token": bad_token, "access_token": "dummy"}

        async def fake_jwks_fetch(*args, **kwargs):
            # Return the *correct* public key — signature will mismatch.
            return _make_jwks_response(public_key)

        # Patch pop_oauth_params to simulate a seeded session and bypass CSRF
        # check by also patching _constant_time_compare.
        def fake_pop_oauth_params(request):
            return "test-state", "test-nonce", "test-verifier"

        with patch("main.exchange_code_for_tokens", side_effect=fake_exchange), \
             patch("auth.oauth._fetch_jwks", side_effect=fake_jwks_fetch), \
             patch("main.pop_oauth_params", side_effect=fake_pop_oauth_params), \
             patch("main._constant_time_compare", return_value=True):

            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    "/auth/callback",
                    params={"code": "authcode", "state": "test-state"},
                    follow_redirects=False,
                )

        assert response.status_code == 401
        detail = response.json()["detail"]
        # Must be exactly the fixed string.
        assert detail == "id_token validation failed."
        # Must NOT contain internal error details.
        assert "InvalidSignatureError" not in detail
        assert "signature" not in detail.lower()


# ---------------------------------------------------------------------------
# sub cross-check: userinfo sub vs id_token sub
# ---------------------------------------------------------------------------


class TestSubCrossCheck:
    def test_sub_mismatch_returns_401(self, monkeypatch, rsa_keypair):
        """
        When userinfo sub differs from id_token sub the callback must return 401
        with the fixed message.  Session is bypassed via patched helpers.
        """
        for k, v in _ROUTE_ENV.items():
            monkeypatch.setenv(k, v)

        private_key, public_key = rsa_keypair
        _jwks_cache.clear()

        app = _route_app()

        async def fake_exchange(config, code, verifier, http_client):
            id_token = _sign_token(
                _valid_claims(
                    iss=config.issuer,
                    aud=config.client_id,
                    nonce="test-nonce",
                    sub="user-from-id-token",
                ),
                private_key,
            )
            return {"id_token": id_token, "access_token": "dummy"}

        async def fake_userinfo(config, access_token, http_client):
            # Different sub from id_token — should trigger 401.
            return {"sub": "user-from-userinfo", "email": "test@example.com"}

        async def fake_jwks_fetch(*args, **kwargs):
            return _make_jwks_response(public_key)

        def fake_pop_oauth_params(request):
            return "test-state", "test-nonce", "test-verifier"

        with patch("main.exchange_code_for_tokens", side_effect=fake_exchange), \
             patch("main.fetch_userinfo", side_effect=fake_userinfo), \
             patch("auth.oauth._fetch_jwks", side_effect=fake_jwks_fetch), \
             patch("main.pop_oauth_params", side_effect=fake_pop_oauth_params), \
             patch("main._constant_time_compare", return_value=True):

            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    "/auth/callback",
                    params={"code": "authcode", "state": "test-state"},
                    follow_redirects=False,
                )

        assert response.status_code == 401
        assert response.json()["detail"] == "id_token validation failed."


# ---------------------------------------------------------------------------
# Session fixation mitigation (Fix 6 — real tests)
# ---------------------------------------------------------------------------


class TestSessionFixation:
    """
    After a successful login the route must:
    1. Call ``request.session.clear()`` BEFORE ``set_authenticated_user``, so
       that pre-login one-time oauth_ keys are gone from the session at the
       moment set_authenticated_user is invoked.
    2. Store the authenticated user profile so /me returns 200.

    The route implementation (main.py line ~275) calls request.session.clear()
    directly (not via the clear_session helper) and then calls
    set_authenticated_user().  We verify the ordering by capturing the session
    state inside a spy on set_authenticated_user — if clear() ran first the
    session will be empty of oauth_ keys at that point.
    """

    def test_session_cleared_before_set_authenticated_user(self, monkeypatch, rsa_keypair):
        """
        Verify that request.session is empty of pre-login keys at the moment
        set_authenticated_user is called (i.e. clear() ran just before it).
        """
        for k, v in _ROUTE_ENV.items():
            monkeypatch.setenv(k, v)

        private_key, public_key = rsa_keypair
        _jwks_cache.clear()

        app = _route_app()

        userinfo_payload = {"sub": "user-xyz", "email": "user@example.com"}

        async def fake_exchange(config, code, verifier, http_client):
            id_token = _sign_token(
                _valid_claims(
                    iss=config.issuer,
                    aud=config.client_id,
                    nonce="test-nonce",
                    sub="user-xyz",
                ),
                private_key,
            )
            return {"id_token": id_token, "access_token": "at-abc"}

        async def fake_userinfo(config, access_token, http_client):
            return userinfo_payload

        async def fake_jwks_fetch(*args, **kwargs):
            return _make_jwks_response(public_key)

        # Capture the session state at the moment set_authenticated_user is called.
        # At that point request.session.clear() has already run (line 275 in main.py),
        # so the pre-login oauth_ one-time keys must be absent.
        session_snapshot: list[dict] = []
        set_user_args: list = []

        import auth.session as _session_mod
        original_set = _session_mod.set_authenticated_user

        def spy_set(request, user_profile):
            # Capture session contents BEFORE we call the real function; at
            # this point clear() has already been called by the route.
            session_snapshot.append(dict(request.session))
            set_user_args.append(user_profile)
            original_set(request, user_profile)

        def fake_pop_oauth_params(request):
            # Inject pre-login keys into the session to simulate a /login call.
            # These should be absent from the snapshot captured inside spy_set.
            request.session["oauth_state"] = "test-state"
            request.session["oauth_nonce"] = "test-nonce"
            request.session["oauth_code_verifier"] = "test-verifier"
            return "test-state", "test-nonce", "test-verifier"

        with patch("main.exchange_code_for_tokens", side_effect=fake_exchange), \
             patch("main.fetch_userinfo", side_effect=fake_userinfo), \
             patch("auth.oauth._fetch_jwks", side_effect=fake_jwks_fetch), \
             patch("main.pop_oauth_params", side_effect=fake_pop_oauth_params), \
             patch("main._constant_time_compare", return_value=True), \
             patch("main.set_authenticated_user", side_effect=spy_set):

            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    "/auth/callback",
                    params={"code": "authcode", "state": "test-state"},
                    follow_redirects=False,
                )

        # Callback must redirect to /me on success.
        assert response.status_code == 302

        # set_authenticated_user must have been called exactly once.
        assert len(session_snapshot) == 1
        assert len(set_user_args) == 1

        # At the moment set_authenticated_user was called, the session was
        # already cleared — no pre-login oauth_ keys present.
        snap = session_snapshot[0]
        assert "oauth_state" not in snap, (
            "oauth_state still in session when set_authenticated_user was called; "
            "session.clear() did not run before set_authenticated_user"
        )
        assert "oauth_nonce" not in snap
        assert "oauth_code_verifier" not in snap

        # set_authenticated_user was called with the correct user profile.
        assert set_user_args[0] == userinfo_payload

    def test_authenticated_user_accessible_after_login(self, monkeypatch, rsa_keypair):
        """
        After a successful callback, /me must return 200 with the user profile,
        confirming the session was properly set after the clear.
        """
        for k, v in _ROUTE_ENV.items():
            monkeypatch.setenv(k, v)

        private_key, public_key = rsa_keypair
        _jwks_cache.clear()

        app = _route_app()

        userinfo_payload = {"sub": "user-xyz", "email": "user@example.com"}

        async def fake_exchange(config, code, verifier, http_client):
            id_token = _sign_token(
                _valid_claims(
                    iss=config.issuer,
                    aud=config.client_id,
                    nonce="test-nonce",
                    sub="user-xyz",
                ),
                private_key,
            )
            return {"id_token": id_token, "access_token": "at-abc"}

        async def fake_userinfo(config, access_token, http_client):
            return userinfo_payload

        async def fake_jwks_fetch(*args, **kwargs):
            return _make_jwks_response(public_key)

        def fake_pop_oauth_params(request):
            return "test-state", "test-nonce", "test-verifier"

        with patch("main.exchange_code_for_tokens", side_effect=fake_exchange), \
             patch("main.fetch_userinfo", side_effect=fake_userinfo), \
             patch("auth.oauth._fetch_jwks", side_effect=fake_jwks_fetch), \
             patch("main.pop_oauth_params", side_effect=fake_pop_oauth_params), \
             patch("main._constant_time_compare", return_value=True):

            with TestClient(app, raise_server_exceptions=False) as client:
                cb_response = client.get(
                    "/auth/callback",
                    params={"code": "authcode", "state": "test-state"},
                    follow_redirects=False,
                )
                # Follow the redirect to /me to check the user is in session.
                me_response = client.get("/me")

        assert cb_response.status_code == 302
        assert me_response.status_code == 200
        me_data = me_response.json()
        assert me_data.get("sub") == "user-xyz"
        assert me_data.get("email") == "user@example.com"


# ---------------------------------------------------------------------------
# https_only gating (Fix 5 — single source for insecure flag)
# ---------------------------------------------------------------------------


class TestHttpsOnlyGating:
    """
    SessionMiddleware must use https_only=True in production (no insecure flag)
    and https_only=False only when OAUTH_ALLOW_INSECURE=1 is set.

    The decision must come from config.allow_insecure (not a separate env read)
    so there is a single source of truth.
    """

    _BASE_ENV = {
        "OAUTH_ISSUER": "https://idp.example.com",
        "OAUTH_CLIENT_ID": "myclient",
        "OAUTH_CLIENT_SECRET": "mysecret",
        "OAUTH_REDIRECT_URI": "https://idp.example.com/auth/callback",
        "SESSION_SECRET": "a" * 32,
    }

    def _get_middleware_options(self, monkeypatch, extra_env: dict | None = None):
        """Load a fresh app and return the SessionMiddleware kwargs."""
        env = {**self._BASE_ENV, **(extra_env or {})}
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        # Ensure OAUTH_ALLOW_INSECURE is unset unless explicitly provided.
        if "OAUTH_ALLOW_INSECURE" not in (extra_env or {}):
            monkeypatch.delenv("OAUTH_ALLOW_INSECURE", raising=False)

        app = _route_app()

        # Find the SessionMiddleware layer and extract its kwargs.
        from starlette.middleware.sessions import SessionMiddleware
        for middleware in app.user_middleware:
            if middleware.cls is SessionMiddleware:
                return middleware.kwargs
        raise AssertionError("SessionMiddleware not found in app.user_middleware")

    def test_https_only_true_without_insecure_flag(self, monkeypatch):
        """Without OAUTH_ALLOW_INSECURE the SessionMiddleware must have https_only=True."""
        kwargs = self._get_middleware_options(monkeypatch)
        assert kwargs.get("https_only") is True

    def test_https_only_false_with_insecure_flag(self, monkeypatch):
        """With OAUTH_ALLOW_INSECURE=1 the SessionMiddleware must have https_only=False."""
        kwargs = self._get_middleware_options(
            monkeypatch,
            extra_env={
                "OAUTH_ALLOW_INSECURE": "1",
                # Override to local URLs so load_config() doesn't reject them.
                "OAUTH_ISSUER": "http://localhost:8080",
                "OAUTH_REDIRECT_URI": "http://localhost:8000/auth/callback",
            },
        )
        assert kwargs.get("https_only") is False

    def test_config_allow_insecure_field_reflects_env(self, monkeypatch):
        """
        config.allow_insecure must be True when OAUTH_ALLOW_INSECURE=1 and False
        otherwise, confirming it is the single source of truth.
        """
        env = {
            **self._BASE_ENV,
            "OAUTH_ALLOW_INSECURE": "1",
            "OAUTH_ISSUER": "http://localhost:8080",
            "OAUTH_REDIRECT_URI": "http://localhost:8000/auth/callback",
        }
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        from auth.config import load_config
        cfg = load_config()
        assert cfg.allow_insecure is True

        # Without the flag.
        monkeypatch.delenv("OAUTH_ALLOW_INSECURE", raising=False)
        # Restore https URLs to avoid RuntimeError.
        monkeypatch.setenv("OAUTH_ISSUER", "https://idp.example.com")
        monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://app.example.com/auth/callback")
        import sys
        for mod in list(sys.modules.keys()):
            if mod.startswith("auth"):
                del sys.modules[mod]
        from auth.config import load_config as load_config2
        cfg2 = load_config2()
        assert cfg2.allow_insecure is False

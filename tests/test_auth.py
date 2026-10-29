import pytest
from httpx import ASGITransport, AsyncClient

from locus.config import get_settings
from locus.main import app
from locus.models.user import User

settings = get_settings()


@pytest.mark.asyncio
async def test_registration_is_disabled(client: AsyncClient):
    """Public registration must not exist anymore."""
    res_page = await client.get("/register")
    assert res_page.status_code == 404

    res_api = await client.post(
        "/api/v1/auth/register",
        json={"username": "new_user", "password": "securepassword123"},
    )
    assert res_api.status_code == 404


@pytest.mark.asyncio
async def test_login_success_and_failure(client: AsyncClient, test_user: User):
    """Test login with valid and invalid credentials."""
    # Invalid password
    res_fail = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "wrongpassword"},
    )
    assert res_fail.status_code == 401

    # Valid login
    res_ok = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "password123"},
    )
    assert res_ok.status_code == 200
    assert "access_token" in res_ok.json()
    assert settings.COOKIE_NAME in res_ok.cookies


@pytest.mark.asyncio
async def test_me_endpoint_with_bearer_and_cookie(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict,
    auth_token: str,
):
    """Test that /auth/me works with both Bearer header and Cookie."""
    # Without credentials -> 401
    res_no_auth = await client.get("/api/v1/auth/me")
    assert res_no_auth.status_code == 401

    # With Bearer header
    res_bearer = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert res_bearer.status_code == 200
    assert res_bearer.json()["username"] == test_user.username
    assert res_bearer.json()["is_admin"] is True

    # With Cookie
    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res_cookie = await client.get("/api/v1/auth/me")
    assert res_cookie.status_code == 200
    assert res_cookie.json()["username"] == test_user.username


@pytest.mark.asyncio
async def test_case_insensitive_login(client: AsyncClient, test_user: User):
    """Test that login works case-insensitively across API and web form."""
    # test_user has username 'student'
    # 1. API login with mixed case
    res_api = await client.post(
        "/api/v1/auth/login",
        json={"username": "sTuDenT", "password": "password123"},
    )
    assert res_api.status_code == 200
    assert "access_token" in res_api.json()

    # 2. Web login with UPPERCASE
    res_web = await client.post(
        "/auth/login",
        data={"username": "STUDENT", "password": "password123"},
        follow_redirects=False,
    )
    assert res_web.status_code == 303
    assert res_web.headers["Location"] == "/"
    assert settings.COOKIE_NAME in res_web.cookies


@pytest.mark.asyncio
async def test_login_rate_limiting(client: AsyncClient, test_user: User):
    """After 5 consecutive failed login attempts, requests are blocked with 429."""
    from locus.rate_limiter import login_limiter
    login_limiter.reset()

    # 5 failed attempts
    for _ in range(5):
        res = await client.post(
            "/api/v1/auth/login",
            json={"username": test_user.username, "password": "wrong_password"},
        )
        assert res.status_code in (401, 429)

    # 6th attempt is blocked with 429 and includes Retry-After header
    res_blocked = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "wrong_password"},
    )
    assert res_blocked.status_code == 429
    assert "Retry-After" in res_blocked.headers
    assert "Слишком много неудачных попыток входа" in res_blocked.json()["detail"]

    # Account Lockout DoS protection: different username from same IP is NOT blocked
    res_other = await client.post(
        "/api/v1/auth/login",
        json={"username": "other_user", "password": "wrong_password"},
    )
    assert res_other.status_code == 401

    # Even with correct password, the blocked (ip, user) pair is blocked until rate limit clears
    res_correct_blocked = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "password123"},
    )
    assert res_correct_blocked.status_code == 429

    # Reset limiter simulates expiration
    login_limiter.reset()
    res_ok = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "password123"},
    )
    assert res_ok.status_code == 200


@pytest.mark.asyncio
async def test_web_login_failure_retains_username_and_clears_password(client: AsyncClient):
    """When login fails in web form, username remains in the field while password is not prefilled."""
    from locus.rate_limiter import login_limiter
    login_limiter.reset()

    res = await client.post(
        "/auth/login",
        data={"username": "persisted_user", "password": "bad_password"},
    )
    assert res.status_code == 400
    assert 'value="persisted_user"' in res.text
    assert 'value="bad_password"' not in res.text
    assert "Неверный логин или пароль" in res.text


@pytest.mark.asyncio
async def test_token_invalidated_when_password_changes(
    client: AsyncClient,
    test_user: User,
    db_session,
):
    from locus.security import hash_password

    # 1. Login to obtain token with password fingerprint
    res_login = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "password123"},
    )
    assert res_login.status_code == 200
    token = res_login.json()["access_token"]

    # 2. Token works
    res_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res_me.status_code == 200

    # 3. Change password in database
    test_user.hashed_password = hash_password("brandnewpassword789")
    await db_session.commit()

    # 4. Old token is immediately rejected with 401
    res_old = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res_old.status_code == 401

    # 5. Login with new password issues working token
    res_new_login = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "brandnewpassword789"},
    )
    assert res_new_login.status_code == 200
    new_token = res_new_login.json()["access_token"]

    res_new_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert res_new_me.status_code == 200


def test_production_secret_key_validation():
    from locus.config import Settings
    import pytest

    # Default secret key in production raises error
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="change-this-to-a-very-secret-random-key-in-production-min-32-chars",
        )

    # Short secret key in production raises error
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(ENVIRONMENT="production", SECRET_KEY="short-secret-key")

    # Whitespace-only secret key in production raises error
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(ENVIRONMENT="production", SECRET_KEY=" " * 32)

    # Valid secret key in production succeeds and whitespace is stripped
    valid_settings = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="  " + "a" * 32 + "  ",
    )
    assert valid_settings.is_production is True
    assert valid_settings.SECRET_KEY == "a" * 32


@pytest.mark.asyncio
async def test_token_without_pwd_fingerprint_is_rejected(
    client: AsyncClient,
    test_user: User,
):
    from locus.security import create_access_token

    # Token with missing 'pwd' fingerprint cannot be used
    legacy_token = create_access_token({"sub": str(test_user.id)})
    res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {legacy_token}"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_csrf_origin_protection(client: AsyncClient, test_user: User, monkeypatch):
    # Untrusted Origin on POST is blocked with 403
    res_blocked = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "password123"},
        headers={"Origin": "https://malicious-website.com"},
    )
    assert res_blocked.status_code == 403
    assert "CSRF validation failed" in res_blocked.text

    # Trusted / matching Host Origin succeeds
    res_allowed = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "password123"},
        headers={"Origin": "http://test"},
    )
    assert res_allowed.status_code == 200

    # Matching X-Forwarded-Host and X-Forwarded-Proto from reverse proxy (e.g. Render.com)
    res_proxy = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "password123"},
        headers={
            "Origin": "https://school.example.com",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "school.example.com:443",
        },
    )
    assert res_proxy.status_code == 200

    # Scheme mismatch (http Origin when site is served over https) is blocked
    res_scheme_mismatch = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "password123"},
        headers={
            "Origin": "http://school.example.com",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "school.example.com",
        },
    )
    assert res_scheme_mismatch.status_code == 403
    assert "CSRF validation failed" in res_scheme_mismatch.text

    # Referer header fallback when Origin is omitted (bare client: no default Origin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as bare:
        res_referer_valid = await bare.post(
            "/api/v1/auth/login",
            json={"username": test_user.username, "password": "password123"},
            headers={"Referer": "http://test/login"},
        )
        assert res_referer_valid.status_code == 200

        res_referer_invalid = await bare.post(
            "/api/v1/auth/login",
            json={"username": test_user.username, "password": "password123"},
            headers={"Referer": "https://evil.com/fake-login"},
        )
        assert res_referer_invalid.status_code == 403

        # No Origin and no Referer: rejected on web routes, allowed on the API
        res_missing = await bare.post(
            "/auth/login",
            data={"username": test_user.username, "password": "password123"},
        )
        assert res_missing.status_code == 403
        assert "missing origin" in res_missing.text

        res_missing_api = await bare.post(
            "/api/v1/auth/login",
            json={"username": test_user.username, "password": "password123"},
        )
        assert res_missing_api.status_code == 200

    # Dev default origin succeeds in development
    res_dev = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "password123"},
        headers={"Origin": "http://localhost:8010"},
    )
    assert res_dev.status_code == 200

    # In production, dev origins like localhost:8010 are rejected
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    res_prod_dev = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "password123"},
        headers={"Origin": "http://localhost:8010"},
    )
    assert res_prod_dev.status_code == 403


def _request(peer: str, forwarded: str | None = None):
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_client_ip_uses_forwarded_hop_only_from_trusted_peer(monkeypatch):
    from locus.rate_limiter import get_client_ip

    # Private peer (our proxy): the last hop is what it appended, a spoofed prefix is ignored
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    assert get_client_ip(_request("10.0.0.5", "1.2.3.4, 5.6.7.8")) == "5.6.7.8"

    # Directly exposed: X-Forwarded-For is client-controlled and must be ignored
    assert get_client_ip(_request("8.8.8.8", "1.2.3.4")) == "8.8.8.8"

    # A proxy on a public IP can be trusted explicitly
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    assert get_client_ip(_request("1.1.1.1", "1.2.3.4")) == "1.2.3.4"


def test_spray_across_usernames_is_limited_per_ip():
    from locus.rate_limiter import (
        check_login_rate_limit,
        record_login_failure,
        spray_limiter,
    )

    request = _request("10.0.0.5")
    for i in range(spray_limiter.max_attempts):
        record_login_failure(request, f"user{i}")

    assert check_login_rate_limit(request, "user0")[0] is True
    assert check_login_rate_limit(request, "another_user")[0] is True


@pytest.mark.asyncio
async def test_logout_revokes_existing_token(client: AsyncClient, test_user: User):
    res_login = await client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "password123"},
    )
    assert res_login.status_code == 200
    token = res_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200

    assert (await client.post("/api/v1/auth/logout")).status_code == 200

    # Replaying the same token after logout must fail
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient):
    res = await client.get("/login")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Referrer-Policy"] == "same-origin"

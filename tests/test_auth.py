import pytest
from httpx import AsyncClient

from locus.config import get_settings
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

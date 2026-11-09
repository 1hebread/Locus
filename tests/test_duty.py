import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.config import get_settings
from locus.constants import DAY_NAMES, get_current_date
from locus.duty import parse_duty_day
from locus.models.duty_day import DutyDay
from locus.models.user import User

settings = get_settings()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Иван И. (student)", [{"name": "Иван И.", "login": "student"}]),
        ("Иван (8А) (student)", [{"name": "Иван (8А)", "login": "student"}]),
        ("Пётр П.\n\n  (ghost", [{"name": "Пётр П.", "login": None}, {"name": "(ghost", "login": None}]),
        ("", []),
        (None, []),
    ],
)
def test_parse_duty_day(text, expected):
    assert parse_duty_day(text) == expected


@pytest.mark.asyncio
async def test_duty_page_requires_login(client: AsyncClient):
    res = await client.get("/duty", follow_redirects=False)

    assert res.status_code == 303
    assert res.headers["Location"] == "/login"


@pytest.mark.asyncio
async def test_duty_page_highlights_linked_user_today(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    db_session: AsyncSession,
):
    today = get_current_date().isoweekday()
    db_session.add(DutyDay(day_of_week=today, text="Иван И. (student)\nПётр П."))
    await db_session.commit()

    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res = await client.get("/duty")

    assert res.status_code == 200
    assert '<span class="truncate">Иван И.</span>' in res.text
    assert "text-emerald-400 font-semibold" in res.text
    assert "Пётр П." in res.text
    assert "Сегодня" in res.text


@pytest.mark.asyncio
async def test_duty_page_keeps_unknown_login_as_text(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    db_session: AsyncSession,
):
    db_session.add(DutyDay(day_of_week=1, text="Иван И. (ghost)"))
    await db_session.commit()

    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res = await client.get("/duty")

    assert res.status_code == 200
    assert "(ghost)" in res.text


@pytest.mark.asyncio
async def test_regular_user_cannot_save_duty(
    client: AsyncClient,
    regular_user: User,
    regular_token: str,
    db_session: AsyncSession,
):
    client.cookies.set(settings.COOKIE_NAME, regular_token)
    res = await client.post("/duty", data={"day_1": "Иван И."}, follow_redirects=False)

    assert res.status_code == 403
    assert (await db_session.execute(select(DutyDay))).scalars().all() == []


@pytest.mark.asyncio
async def test_admin_saves_duty(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    db_session: AsyncSession,
):
    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res = await client.post(
        "/duty",
        data={"day_1": "Иван И. (student)", "day_2": "Пётр П."},
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["Location"] == "/duty"

    rows = (await db_session.execute(select(DutyDay).order_by(DutyDay.day_of_week))).scalars().all()
    saved = {row.day_of_week: row.text for row in rows}
    assert saved[1] == "Иван И. (student)"
    assert saved[2] == "Пётр П."


@pytest.mark.asyncio
async def test_api_duty_requires_auth(client: AsyncClient):
    res = await client.get("/api/v1/duty")

    assert res.status_code == 401


@pytest.mark.asyncio
async def test_api_lists_duty_days(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict,
    db_session: AsyncSession,
):
    today = get_current_date().isoweekday()
    db_session.add(DutyDay(day_of_week=today, text="Иван И. (student)\nПётр П. (ghost)"))
    await db_session.commit()

    res = await client.get("/api/v1/duty", headers=auth_headers)

    assert res.status_code == 200
    days = res.json()
    assert [day["day_of_week"] for day in days] == list(range(1, 8))
    assert [day["name"] for day in days] == [DAY_NAMES[num] for num in range(1, 8)]

    today_payload = days[today - 1]
    assert today_payload["is_today"] is True
    assert today_payload["entries"] == [
        {"name": "Иван И.", "login": "student", "linked": True},
        {"name": "Пётр П.", "login": "ghost", "linked": False},
    ]
    assert [day["is_today"] for day in days].count(True) == 1


@pytest.mark.asyncio
async def test_api_admin_replaces_duty_day(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict,
    db_session: AsyncSession,
):
    res = await client.put(
        "/api/v1/duty/3",
        json={"text": "  Иван И. (student)\n\nПётр П. "},
        headers=auth_headers,
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["day_of_week"] == 3
    assert payload["name"] == DAY_NAMES[3]
    assert payload["text"] == "Иван И. (student)\n\nПётр П."
    assert payload["entries"] == [
        {"name": "Иван И.", "login": "student", "linked": True},
        {"name": "Пётр П.", "login": None, "linked": False},
    ]

    again = await client.put("/api/v1/duty/3", json={"text": ""}, headers=auth_headers)
    assert again.status_code == 200
    assert again.json()["entries"] == []

    rows = (await db_session.execute(select(DutyDay))).scalars().all()
    assert [(row.day_of_week, row.text) for row in rows] == [(3, "")]


@pytest.mark.asyncio
async def test_api_regular_user_cannot_update_duty(
    client: AsyncClient,
    regular_user: User,
    regular_auth_headers: dict,
    db_session: AsyncSession,
):
    res = await client.put(
        "/api/v1/duty/1", json={"text": "Иван И."}, headers=regular_auth_headers
    )

    assert res.status_code == 403
    assert (await db_session.execute(select(DutyDay))).scalars().all() == []


@pytest.mark.asyncio
async def test_api_duty_rejects_bad_day_and_text(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict,
    db_session: AsyncSession,
):
    for day in (0, 8):
        res = await client.put(f"/api/v1/duty/{day}", json={"text": "x"}, headers=auth_headers)
        assert res.status_code == 422

    assert (
        await client.put("/api/v1/duty/1", json={}, headers=auth_headers)
    ).status_code == 422
    assert (
        await client.put("/api/v1/duty/1", json={"text": "x" * 2001}, headers=auth_headers)
    ).status_code == 422
    assert (await db_session.execute(select(DutyDay))).scalars().all() == []


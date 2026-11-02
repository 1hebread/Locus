from datetime import date, datetime
import re
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from locus.api.deps import get_current_admin_web
from locus.config import get_settings
from locus.constants import DAY_SHORT_NAMES
from locus.database import get_db
from locus.homework_audit import local_datetime
from locus.models.api_key import ApiKey
from locus.models.homework import Homework
from locus.models.homework_completion import HomeworkCompletion
from locus.models.homework_event import HomeworkEvent
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.security import (
    MAX_PASSWORD_BYTES,
    create_access_token,
    generate_api_key,
    get_password_fingerprint,
    hash_api_key,
    hash_password_async,
    set_session_cookie,
)
from locus.templates_config import templates

router = APIRouter(prefix="/admin", tags=["Web Admin"])
USERNAME_PATTERN = re.compile(r"^[\w.-]+$", re.UNICODE)


async def _render_users(
    request: Request,
    db: AsyncSession,
    current_user: User,
    error: str | None = None,
    form_username: str = "",
    created: bool = False,
    deleted: bool = False,
    password_changed: bool = False,
    username_changed: bool = False,
    subgroup_changed: bool = False,
    status_code: int = status.HTTP_200_OK,
):
    result = await db.execute(select(User).order_by(User.id))
    users = result.scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context={
            "current_user": current_user,
            "active_page": "admin",
            "users": users,
            "error": error,
            "form_username": form_username,
            "created": created,
            "deleted": deleted,
            "password_changed": password_changed,
            "username_changed": username_changed,
            "subgroup_changed": subgroup_changed,
        },
        status_code=status_code,
    )


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    return await _render_users(
        request,
        db,
        current_user,
        error=request.query_params.get("error"),
        created=request.query_params.get("created") == "1",
        deleted=request.query_params.get("deleted") == "1",
        password_changed=request.query_params.get("password_changed") == "1",
        username_changed=request.query_params.get("username_changed") == "1",
        subgroup_changed=request.query_params.get("subgroup_changed") == "1",
    )


@router.post("/users")
async def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    subgroup: str | None = Form(default=None),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    username = username.strip().lower()

    clean_subgroup: int | None = None
    if subgroup and subgroup.strip():
        if subgroup.strip() in ("1", "2"):
            clean_subgroup = int(subgroup.strip())
        else:
            return await _render_users(
                request,
                db,
                current_user,
                error="Номер подгруппы должен быть 1 или 2",
                form_username=username,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    if len(username) < 3:
        error = "Логин должен быть не короче 3 символов"
    elif len(username) > 255:
        error = "Логин должен быть не длиннее 255 символов"
    elif any(char.isspace() for char in username):
        error = "Логин не должен содержать пробелы"
    elif not USERNAME_PATTERN.match(username):
        error = "Логин может содержать только буквы, цифры, точки, дефисы и знаки подчеркивания"
    elif len(password) < 8:
        error = "Пароль должен быть не короче 8 символов"
    elif len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        error = f"Пароль должен быть не длиннее {MAX_PASSWORD_BYTES} байт"
    else:
        existing = await db.execute(
            select(User).where(func.lower(User.username) == username)
        )
        if existing.scalar_one_or_none():
            error = "Пользователь с таким логином уже существует"
        else:
            db.add(
                User(
                    username=username,
                    hashed_password=await hash_password_async(password),
                    is_active=True,
                    is_admin=False,
                    subgroup=clean_subgroup,
                )
            )
            await db.commit()
            return RedirectResponse(
                url="/admin/users?created=1",
                status_code=status.HTTP_303_SEE_OTHER,
            )

    return await _render_users(
        request,
        db,
        current_user,
        error=error,
        form_username=username,
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@router.get("/users/{user_id}/username")
async def get_change_username_redirect(user_id: int):
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/username")
async def change_username(
    request: Request,
    user_id: int,
    username: str = Form(...),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        return await _render_users(
            request,
            db,
            current_user,
            error="Пользователь не найден",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    clean_username = username.strip().lower()

    if len(clean_username) < 3:
        error = "Логин должен быть не короче 3 символов"
    elif len(clean_username) > 255:
        error = "Логин должен быть не длиннее 255 символов"
    elif any(char.isspace() for char in clean_username):
        error = "Логин не должен содержать пробелы"
    elif not USERNAME_PATTERN.match(clean_username):
        error = "Логин может содержать только буквы, цифры, точки, дефисы и знаки подчеркивания"
    else:
        existing = await db.execute(
            select(User).where(
                func.lower(User.username) == clean_username,
                User.id != user_id,
            )
        )
        if existing.scalar_one_or_none():
            error = "Пользователь с таким логином уже существует"
        else:
            user.username = clean_username
            await db.commit()
            return RedirectResponse(
                url="/admin/users?username_changed=1",
                status_code=status.HTTP_303_SEE_OTHER,
            )

    return await _render_users(
        request,
        db,
        current_user,
        error=error,
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@router.get("/users/{user_id}/subgroup")
async def get_change_subgroup_redirect(user_id: int):
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/subgroup")
async def change_subgroup(
    request: Request,
    user_id: int,
    subgroup: str | None = Form(default=None),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        return await _render_users(
            request,
            db,
            current_user,
            error="Пользователь не найден",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    clean_subgroup: int | None = None
    if subgroup and subgroup.strip():
        if subgroup.strip() in ("1", "2"):
            clean_subgroup = int(subgroup.strip())
        else:
            return await _render_users(
                request,
                db,
                current_user,
                error="Номер подгруппы должен быть 1 или 2",
                form_username=user.username,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    user.subgroup = clean_subgroup
    await db.commit()
    return RedirectResponse(
        url="/admin/users?subgroup_changed=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/users/{user_id}/password")
async def get_change_password_redirect(user_id: int):
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/password")
async def change_password(
    request: Request,
    user_id: int,
    password: str = Form(...),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        return await _render_users(
            request,
            db,
            current_user,
            error="Пользователь не найден",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if len(password) < 8:
        return await _render_users(
            request,
            db,
            current_user,
            error="Пароль должен быть не короче 8 символов",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return await _render_users(
            request,
            db,
            current_user,
            error=f"Пароль должен быть не длиннее {MAX_PASSWORD_BYTES} байт",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user.hashed_password = await hash_password_async(password)
    await db.commit()

    response = RedirectResponse(
        url="/admin/users?password_changed=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    if current_user.id == user.id:
        new_token = create_access_token({
            "sub": str(user.id),
            "pwd": get_password_fingerprint(user.hashed_password),
            "ver": user.token_version,
        })
        set_session_cookie(response, new_token)

    return response


@router.get("/users/{user_id}/delete")
async def get_delete_user_redirect(user_id: int):
    return RedirectResponse(url="/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/delete")
async def delete_user(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        return await _render_users(
            request,
            db,
            current_user,
            error="Пользователь не найден",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if user.id == current_user.id:
        return await _render_users(
            request,
            db,
            current_user,
            error="Нельзя удалить свой аккаунт",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    await db.execute(
        delete(HomeworkCompletion).where(HomeworkCompletion.user_id == user.id)
    )
    await db.delete(user)
    await db.commit()
    return RedirectResponse(
        url="/admin/users?deleted=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


HISTORY_LIMIT = 200

ACTION_LABELS = {
    "created": "Создал",
    "updated": "Изменил",
    "deleted": "Удалил",
}
FIELD_LABELS = {
    "subject_id": "Предмет",
    "lesson_id": "Урок",
    "due_date": "Дата",
    "subgroup": "Подгруппа",
    "title": "Текст",
}
FIELD_ORDER = ("subject_id", "due_date", "lesson_id", "subgroup", "title")


def _display_value(
    field: str,
    value,
    subject_names: dict[int, str],
    lesson_names: dict[int, str],
) -> str:
    if value is None or value == "":
        return "—"
    if field == "subject_id":
        return subject_names.get(value, f"#{value}")
    if field == "lesson_id":
        return lesson_names.get(value, f"урок #{value}")
    if field == "due_date":
        if isinstance(value, str):
            try:
                d = date.fromisoformat(value)
                return d.strftime("%d.%m.%Y")
            except ValueError:
                return str(value)
        elif isinstance(value, date):
            return value.strftime("%d.%m.%Y")
    if field == "subgroup":
        return f"{value} подгруппа"
    return str(value)


@router.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HomeworkEvent)
        .order_by(HomeworkEvent.created_at.desc(), HomeworkEvent.id.desc())
        .limit(HISTORY_LIMIT)
    )
    events = list(result.scalars().all())
    subject_names = dict((await db.execute(select(Subject.id, Subject.name))).all())

    # 1. Fetch live homeworks as fallback for legacy events that didn't persist subject/date
    hw_ids = {event.homework_id for event in events if event.homework_id is not None}
    homeworks_by_id: dict[int, Homework] = {}
    if hw_ids:
        hw_rows = (
            await db.execute(
                select(Homework).where(Homework.id.in_(hw_ids))
            )
        ).scalars().all()
        homeworks_by_id = {hw.id: hw for hw in hw_rows}

    # 2. Build fallback context map per homework_id for legacy update events
    hw_context: dict[int, dict[str, Any]] = {}
    for event in events:
        if not event.homework_id:
            continue
        ctx = hw_context.setdefault(event.homework_id, {})
        ch = event.changes or {}
        if "subject_id" in ch and "subject_id" not in ctx:
            vals = ch["subject_id"]
            if isinstance(vals, (list, tuple)) and len(vals) >= 1:
                val = vals[1] if len(vals) >= 2 and vals[1] is not None else vals[0]
                if val is not None:
                    ctx["subject_id"] = val
        if "due_date" in ch and "due_date" not in ctx:
            vals = ch["due_date"]
            if isinstance(vals, (list, tuple)) and len(vals) >= 1:
                val = vals[1] if len(vals) >= 2 and vals[1] is not None else vals[0]
                if val is not None:
                    ctx["due_date"] = val

    for hw_id, hw in homeworks_by_id.items():
        ctx = hw_context.setdefault(hw_id, {})
        ctx.setdefault("subject_id", hw.subject_id)
        ctx.setdefault(
            "due_date",
            hw.due_date.isoformat() if isinstance(hw.due_date, (date, datetime)) else str(hw.due_date),
        )

    # 3. Lesson names
    lesson_ids = {
        value
        for event in events
        for field, values in (event.changes or {}).items()
        if field == "lesson_id" and isinstance(values, (list, tuple))
        for value in values
        if isinstance(value, int)
    }

    lesson_names: dict[int, str] = {}
    if lesson_ids:
        lessons = (
            await db.execute(
                select(Lesson)
                .options(selectinload(Lesson.subject))
                .where(Lesson.id.in_(lesson_ids))
            )
        ).scalars().all()
        lesson_names = {
            lesson.id: (
                f"{lesson.subject.name} · "
                f"{DAY_SHORT_NAMES.get(lesson.day_of_week, '')}, "
                f"{lesson.lesson_number} урок"
            )
            for lesson in lessons
        }

    rows = []
    for event in events:
        event_changes = dict(event.changes or {})

        # If subject_id or due_date is missing from legacy event changes,
        # fill in from homework context so the admin always sees what subject and date were affected
        if event.homework_id and event.homework_id in hw_context:
            ctx = hw_context[event.homework_id]
            if "subject_id" not in event_changes and "subject_id" in ctx:
                event_changes["subject_id"] = [ctx["subject_id"], ctx["subject_id"]]
            if "due_date" not in event_changes and "due_date" in ctx:
                event_changes["due_date"] = [ctx["due_date"], ctx["due_date"]]

        # Display fields in clean logical order (subject -> due_date -> lesson -> subgroup -> title)
        ordered_fields = [f for f in FIELD_ORDER if f in event_changes] + [
            f for f in event_changes if f not in FIELD_ORDER
        ]

        changes_list = []
        for field in ordered_fields:
            vals = event_changes.get(field)
            if not isinstance(vals, (list, tuple)) or len(vals) < 2:
                continue
            changes_list.append(
                {
                    "label": FIELD_LABELS.get(field, field),
                    "old": _display_value(field, vals[0], subject_names, lesson_names),
                    "new": _display_value(field, vals[1], subject_names, lesson_names),
                }
            )

        rows.append(
            {
                "when": local_datetime(event.created_at).strftime("%d.%m.%Y %H:%M"),
                "actor": event.actor_username,
                "key": event.actor_key_name,
                "action": ACTION_LABELS.get(event.action, event.action),
                "changes": changes_list,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="admin/history.html",
        context={
            "current_user": current_user,
            "active_page": "admin_history",
            "rows": rows,
        },
    )


API_KEY_NAME_MAX = 100
NEW_API_KEY_COOKIE = "locus_new_api_key"


async def _render_api_keys(
    request: Request,
    db: AsyncSession,
    current_user: User,
    new_key: str | None = None,
    error: str | None = None,
    deleted: bool = False,
    status_code: int = status.HTTP_200_OK,
):
    rows = (
        await db.execute(
            select(ApiKey, User.username)
            .join(User, ApiKey.user_id == User.id)
            .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
        )
    ).all()
    users = (await db.execute(select(User).order_by(User.username))).scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="admin/api_keys.html",
        context={
            "current_user": current_user,
            "active_page": "admin_api_keys",
            "rows": [
                {
                    "id": key.id,
                    "name": key.name,
                    "username": username,
                    "created_at": local_datetime(key.created_at).strftime("%d.%m.%Y %H:%M"),
                }
                for key, username in rows
            ],
            "users": users,
            "new_key": new_key,
            "error": error,
            "deleted": deleted,
        },
        status_code=status_code,
    )


@router.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(
    request: Request,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    # The freshly created key is flashed via a short-lived cookie so that a page
    # reload after creation cannot re-submit the form and mint another key.
    new_key = request.cookies.get(NEW_API_KEY_COOKIE)
    response = await _render_api_keys(
        request,
        db,
        current_user,
        new_key=new_key,
        deleted=request.query_params.get("deleted") == "1",
    )
    if new_key:
        response.delete_cookie(NEW_API_KEY_COOKIE, path="/admin")
    return response


@router.post("/api-keys")
async def create_api_key(
    request: Request,
    name: str = Form(...),
    user_id: int = Form(...),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    name = name.strip()
    if not name:
        return await _render_api_keys(
            request,
            db,
            current_user,
            error="Название ключа не может быть пустым",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if len(name) > API_KEY_NAME_MAX:
        return await _render_api_keys(
            request,
            db,
            current_user,
            error=f"Название ключа не должно быть длиннее {API_KEY_NAME_MAX} символов",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = await db.get(User, user_id)
    if not user:
        return await _render_api_keys(
            request,
            db,
            current_user,
            error="Пользователь не найден",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    key = generate_api_key()
    db.add(ApiKey(name=name, key_hash=hash_api_key(key), user_id=user.id))
    await db.commit()

    response = RedirectResponse(url="/admin/api-keys", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        NEW_API_KEY_COOKIE,
        key,
        max_age=60,
        httponly=True,
        samesite="lax",
        secure=get_settings().is_production,
        path="/admin",
    )
    return response


@router.get("/api-keys/{key_id}/delete")
async def get_delete_api_key_redirect(key_id: int):
    return RedirectResponse(url="/admin/api-keys", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api-keys/{key_id}/delete")
async def delete_api_key(
    key_id: int,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(ApiKey, key_id)
    if key:
        await db.delete(key)
        await db.commit()
    return RedirectResponse(
        url="/admin/api-keys?deleted=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )

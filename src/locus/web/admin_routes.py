import re
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from locus.api.deps import get_current_admin_web
from locus.constants import DAY_SHORT_NAMES
from locus.database import get_db
from locus.homework_audit import local_datetime
from locus.models.homework_completion import HomeworkCompletion
from locus.models.homework_event import HomeworkEvent
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.security import (
    create_access_token,
    get_password_fingerprint,
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
    elif len(password) < 6:
        error = "Пароль должен быть не короче 6 символов"
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

    if len(password) < 6:
        return await _render_users(
            request,
            db,
            current_user,
            error="Пароль должен быть не короче 6 символов",
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
    "title": "Текст",
    "due_date": "Срок",
    "subgroup": "Подгруппа",
}


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

    lesson_ids = {
        value
        for event in events
        for field, values in (event.changes or {}).items()
        if field == "lesson_id"
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
        rows.append(
            {
                "when": local_datetime(event.created_at).strftime("%d.%m.%Y %H:%M"),
                "actor": event.actor_username,
                "action": ACTION_LABELS.get(event.action, event.action),
                "changes": [
                    {
                        "label": FIELD_LABELS.get(field, field),
                        "old": _display_value(field, values[0], subject_names, lesson_names),
                        "new": _display_value(field, values[1], subject_names, lesson_names),
                    }
                    for field, values in (event.changes or {}).items()
                ],
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

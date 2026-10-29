import re
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.api.deps import get_current_admin_web, get_current_user_web
from locus.database import get_db
from locus.models.subject import Subject
from locus.models.user import User
from locus.templates_config import templates

router = APIRouter(prefix="/subjects", tags=["Web Subjects"])


@router.get("", response_class=HTMLResponse)
async def subjects_page(
    request: Request,
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Subject).order_by(Subject.name)
    res = await db.execute(stmt)
    subjects = res.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="subjects/index.html",
        context={
            "current_user": current_user,
            "active_page": "subjects",
            "subjects": subjects,
        },
    )


def _clean_str(val: Optional[str], max_len: Optional[int] = None) -> Optional[str]:
    if not val:
        return None
    s = val.strip()
    if not s:
        return None
    if max_len:
        s = s[:max_len]
    return s


def _clean_phone(val: Optional[str], max_len: int = 50) -> Optional[str]:
    cleaned = _clean_str(val, max_len)
    if not cleaned:
        return None
    # Only keep digits, spaces, +, -, (, )
    if not re.fullmatch(r"[\d\s\+\-\(\)]+", cleaned):
        return None
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) < 7:
        return None
    return cleaned


@router.post("")
async def create_subject_web(
    name: str = Form(...),
    teacher_name: Optional[str] = Form(default=None),
    teacher_phone: Optional[str] = Form(default=None),
    room: Optional[str] = Form(default=None),
    teacher2_name: Optional[str] = Form(default=None),
    teacher2_phone: Optional[str] = Form(default=None),
    room2: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    clean_name = _clean_str(name, max_len=100)
    if not clean_name:
        return RedirectResponse(url="/subjects", status_code=status.HTTP_303_SEE_OTHER)

    subject = Subject(
        name=clean_name,
        teacher_name=_clean_str(teacher_name, max_len=120),
        teacher_phone=_clean_phone(teacher_phone, max_len=50),
        room=_clean_str(room, max_len=50),
        teacher2_name=_clean_str(teacher2_name, max_len=120),
        teacher2_phone=_clean_phone(teacher2_phone, max_len=50),
        room2=_clean_str(room2, max_len=50),
    )
    db.add(subject)
    await db.commit()

    return RedirectResponse(url="/subjects", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{subject_id}/edit")
async def edit_subject_web_get(
    subject_id: int,
    current_user: User = Depends(get_current_admin_web),
):
    return RedirectResponse(url="/subjects", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{subject_id}/edit")
async def edit_subject_web(
    subject_id: int,
    name: str = Form(...),
    teacher_name: Optional[str] = Form(default=None),
    teacher_phone: Optional[str] = Form(default=None),
    room: Optional[str] = Form(default=None),
    teacher2_name: Optional[str] = Form(default=None),
    teacher2_phone: Optional[str] = Form(default=None),
    room2: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    clean_name = _clean_str(name, max_len=100)
    if not clean_name:
        return RedirectResponse(url="/subjects", status_code=status.HTTP_303_SEE_OTHER)

    subject = await db.get(Subject, subject_id)
    if subject:
        subject.name = clean_name
        subject.teacher_name = _clean_str(teacher_name, max_len=120)
        subject.room = _clean_str(room, max_len=50)

        if teacher_phone is not None:
            trimmed_phone = teacher_phone.strip()
            if not trimmed_phone:
                subject.teacher_phone = None
            else:
                valid_phone = _clean_phone(trimmed_phone, max_len=50)
                if valid_phone:
                    subject.teacher_phone = valid_phone

        subject.teacher2_name = _clean_str(teacher2_name, max_len=120)
        subject.room2 = _clean_str(room2, max_len=50)

        if teacher2_phone is not None:
            trimmed_phone2 = teacher2_phone.strip()
            if not trimmed_phone2:
                subject.teacher2_phone = None
            else:
                valid_phone2 = _clean_phone(trimmed_phone2, max_len=50)
                if valid_phone2:
                    subject.teacher2_phone = valid_phone2

        await db.commit()

    return RedirectResponse(url="/subjects", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/{subject_id}")
async def delete_subject_web(
    subject_id: int,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    subject = await db.get(Subject, subject_id)
    if subject:
        await db.delete(subject)
        await db.commit()

    return Response(content="", status_code=status.HTTP_200_OK)

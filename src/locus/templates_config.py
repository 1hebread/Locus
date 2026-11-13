from datetime import date
from pathlib import Path
from fastapi.templating import Jinja2Templates

from locus.constants import DAY_SHORT_NAMES, SUBGROUP_BADGES, SUBGROUP_LABELS

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def subgroup_badge(val: object) -> str:
    if val is None:
        return ""
    return SUBGROUP_BADGES.get(str(val), str(val))


def subgroup_label(val: object) -> str:
    if val is None:
        return ""
    return SUBGROUP_LABELS.get(str(val), str(val))


def due_meta(due: date, today: date) -> tuple[str, str]:
    """Human due-date label and its text color for homework cards."""
    days_left = (due - today).days
    if days_left < 0:
        return "Просрочено", "text-rose-400"
    if days_left == 0:
        return "Сегодня", "text-emerald-400 font-semibold"
    if days_left == 1:
        return "Завтра", "text-zinc-300"
    return f"{DAY_SHORT_NAMES[due.isoweekday()]}, {due.strftime('%d.%m')}", "text-zinc-400"


templates.env.filters["subgroup_badge"] = subgroup_badge
templates.env.filters["subgroup_label"] = subgroup_label
templates.env.filters["due_meta"] = due_meta


def asset_version(rel_path: str) -> int:
    """Cache-busting version based on the file modification time."""
    try:
        return int((STATIC_DIR / rel_path).stat().st_mtime)
    except OSError:
        return 0


templates.env.globals["asset_version"] = asset_version

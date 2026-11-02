from pathlib import Path
from fastapi.templating import Jinja2Templates

from locus.constants import SUBGROUP_BADGES, SUBGROUP_LABELS

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


templates.env.filters["subgroup_badge"] = subgroup_badge
templates.env.filters["subgroup_label"] = subgroup_label


def asset_version(rel_path: str) -> int:
    """Cache-busting version based on the file modification time."""
    try:
        return int((STATIC_DIR / rel_path).stat().st_mtime)
    except OSError:
        return 0


templates.env.globals["asset_version"] = asset_version

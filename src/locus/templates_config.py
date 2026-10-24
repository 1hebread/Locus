from pathlib import Path
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def asset_version(rel_path: str) -> int:
    """Cache-busting version based on the file modification time."""
    try:
        return int((STATIC_DIR / rel_path).stat().st_mtime)
    except OSError:
        return 0


templates.env.globals["asset_version"] = asset_version

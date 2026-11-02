from typing import Any, List, Optional
from sqlalchemy import or_

from locus.constants import ACADEMIC_SUBGROUPS, GENDER_SUBGROUPS, VALID_SUBGROUPS
from locus.models.user import User


def normalize_subgroup(val: Any) -> Optional[str]:
    """Clean and validate subgroup identifier ('1', '2', 'boys', 'girls' or None)."""
    if val is None:
        return None
    cleaned = str(val).strip()
    if not cleaned or cleaned in ("0", "all", "none", "None", ""):
        return None
    if cleaned in VALID_SUBGROUPS:
        return cleaned
    raise ValueError(f"Недопустимая подгруппа: {val}")


def user_matches_subgroup(user: User, target_subgroup: Optional[object]) -> bool:
    """Check if the user has access to content assigned to target_subgroup.

    - Admins have access to all subgroups.
    - Whole-class content (None or empty) is accessible to everyone.
    - If user's specific dimension is unassigned (None), they see all content in that dimension.
    - If user's dimension is set, content must match their assigned subgroup.
    """
    if getattr(user, "is_admin", False):
        return True
    if target_subgroup is None or str(target_subgroup).strip() in ("", "0", "all", "none"):
        return True
    target_str = str(target_subgroup).strip()
    if target_str in GENDER_SUBGROUPS:
        if getattr(user, "gender_subgroup", None) is None:
            return True
        return user.gender_subgroup == target_str
    if target_str in ACADEMIC_SUBGROUPS:
        if getattr(user, "subgroup", None) is None:
            return True
        return str(user.subgroup) == target_str
    return False


def build_user_subgroup_filter(user: User, column: Any) -> Any:
    """Build an SQLAlchemy filter expression for a user's visible subgroups."""
    if user.is_admin or (user.subgroup is None and user.gender_subgroup is None):
        return None

    if user.subgroup is not None and user.gender_subgroup is not None:
        return or_(column.is_(None), column == str(user.subgroup), column == user.gender_subgroup)
    if user.subgroup is not None and user.gender_subgroup is None:
        return or_(column.is_(None), column == str(user.subgroup), column.in_(list(GENDER_SUBGROUPS)))
    if user.subgroup is None and user.gender_subgroup is not None:
        return or_(column.is_(None), column.in_(list(ACADEMIC_SUBGROUPS)), column == user.gender_subgroup)
    return None

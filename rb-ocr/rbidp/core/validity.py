from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from rbidp.core.config import UTC_OFFSET_HOURS
from rbidp.core.dates import parse_doc_date

# Canonical doc_type strings (must match extractor output)
DOC_DECREE_ORDER = "Приказ о выходе в декретный отпуск по уходу за ребенком"
DOC_VKK = "Заключение врачебно-консультативной комиссии (ВКК)"
DOC_DISABILITY_CERT = "Справка об инвалидности"
DOC_LOSS_OF_WORK_CAPACITY = "Справка о степени утраты общей трудоспособности"

# Default and overrides
DEFAULT_FIXED_DAYS = 30

VALIDITY_OVERRIDES: Dict[str, Dict[str, Any]] = {
    DOC_VKK: {"type": "fixed_days", "days": 180},
    DOC_DISABILITY_CERT: {"type": "fixed_days", "days": 360},
    DOC_LOSS_OF_WORK_CAPACITY: {"type": "fixed_days", "days": 360},
    DOC_DECREE_ORDER: {"type": "explicit_end_date"},
}


def _timezone() -> timezone:
    return timezone(timedelta(hours=UTC_OFFSET_HOURS))


def _format_date(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.strftime("%d.%m.%Y")


def resolve_policy(doc_type: Any) -> Dict[str, Any]:
    if isinstance(doc_type, str):
        dt = doc_type.strip()
        if dt in VALIDITY_OVERRIDES:
            return VALIDITY_OVERRIDES[dt]
    return {"type": "fixed_days", "days": DEFAULT_FIXED_DAYS}


def compute_valid_until(
    doc_type: Any,
    doc_date_str: Any,
    valid_until_str: Any,
) -> Tuple[Optional[datetime], str, Optional[int], Optional[str]]:
    """
    Returns (valid_until_dt_with_tz, policy_type, window_days_if_fixed, error)
    - fixed_days: requires doc_date; computes doc_date + days
    - explicit_end_date: requires valid_until_str; uses it directly
    Dates are localized to UTC+offset.
    """
    tz = _timezone()
    policy = resolve_policy(doc_type)
    ptype = policy.get("type")
    if ptype == "fixed_days":
        days = int(policy.get("days", DEFAULT_FIXED_DAYS))
        d = parse_doc_date(doc_date_str)
        if d is None:
            return None, "fixed_days", days, "DOC_DATE_MISSING_OR_INVALID"
        d_local = d.replace(tzinfo=tz)
        return d_local + timedelta(days=days), "fixed_days", days, None
    elif ptype == "explicit_end_date":
        vu = parse_doc_date(valid_until_str)
        if vu is None:
            return None, "explicit_end_date", None, "VALID_UNTIL_MISSING_OR_INVALID"
        return vu.replace(tzinfo=tz), "explicit_end_date", None, None
    else:
        # Fallback to default fixed days
        days = DEFAULT_FIXED_DAYS
        d = parse_doc_date(doc_date_str)
        if d is None:
            return None, "fixed_days", days, "DOC_DATE_MISSING_OR_INVALID"
        d_local = d.replace(tzinfo=tz)
        return d_local + timedelta(days=days), "fixed_days", days, None


def is_within_validity(valid_until_dt: Optional[datetime], now_dt: Optional[datetime] = None) -> Optional[bool]:
    if valid_until_dt is None:
        return None
    now = now_dt or datetime.now(_timezone())
    return now <= valid_until_dt


def format_date(dt: Optional[datetime]) -> Optional[str]:
    return _format_date(dt)
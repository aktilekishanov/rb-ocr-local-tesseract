from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def parse_doc_date(s: Any) -> Optional[datetime]:
    if not isinstance(s, str):
        return None
    s2 = s.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s2, fmt)
        except Exception:
            continue
    return None


def now_utc_plus(hours: int = 5) -> datetime:
    tz = timezone(timedelta(hours=hours))
    return datetime.now(tz)
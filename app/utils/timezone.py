from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    JAKARTA_TZ = ZoneInfo("Asia/Jakarta")
except Exception:
    JAKARTA_TZ = timezone(timedelta(hours=7))

def get_jakarta_tz():
    return JAKARTA_TZ

def now_jakarta() -> datetime:
    """
    Mengembalikan objek datetime saat ini dalam zona waktu Asia/Jakarta (WIB, UTC+7).
    """
    return datetime.now(JAKARTA_TZ)

def now_jakarta_naive() -> datetime:
    """
    Mengembalikan datetime waktu Jakarta tanpa tzinfo (naive)
    untuk kompatibilitas penyimpanan SQLite DateTime column.
    """
    return datetime.now(JAKARTA_TZ).replace(tzinfo=None)

def to_jakarta(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Mengonversi datetime apapun (UTC atau naive) ke waktu Jakarta.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(JAKARTA_TZ)

def format_wib(dt: Optional[datetime], fmt: str = "%d %b %Y %H:%M WIB") -> str:
    """
    Memformat datetime ke string berzona WIB.
    Contoh: 20 Sep 2026 00:30 WIB
    """
    if dt is None:
        return "-"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return dt
    return dt.strftime(fmt)

def format_time_wib(dt: Optional[datetime]) -> str:
    """
    Memformat datetime ke jam saja: HH:MM:SS WIB
    """
    if dt is None:
        return "-"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return dt
    return dt.strftime("%H:%M:%S WIB")

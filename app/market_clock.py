from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def market_phase(now: datetime | None = None) -> dict[str, str | bool]:
    now = now.astimezone(TAIPEI) if now else datetime.now(TAIPEI)
    weekday_open = now.weekday() < 5
    t = now.time()
    if not weekday_open:
        phase = "休市"
        formal = True
    elif t < time(8, 30):
        phase = "盤前"
        formal = True
    elif time(8, 30) <= t < time(9, 0):
        phase = "集合競價"
        formal = False
    elif time(9, 0) <= t <= time(13, 30):
        phase = "盤中"
        formal = False
    elif time(13, 30) < t < time(17, 0):
        phase = "收盤資料整理中"
        formal = False
    else:
        phase = "盤後"
        formal = True
    return {"phase": phase,"is_formal_close_mode": formal,"now": now.isoformat(timespec="seconds"),"timezone": "Asia/Taipei"}

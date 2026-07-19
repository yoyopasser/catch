from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AnalysisResult:
    code: str
    name: str
    exchange: str
    asset_type: str
    data_date: str
    data_status: str
    score: float
    market_state: str
    signal: str
    today_action: str
    tomorrow_plan: list[str]
    reasons: list[str]
    warnings: list[str] = field(default_factory=list)
    close: float | None = None
    ma5: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    atr14: float | None = None
    volume_ratio: float | None = None
    entry_low: float | None = None
    entry_high: float | None = None
    stop_loss: float | None = None
    resistance: float | None = None
    risk_reward: float | None = None
    position_qty: float = 0.0
    avg_cost: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

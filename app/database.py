from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def init_schema(self) -> None:
        with self.connect() as con:
            con.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS securities (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    close REAL,
                    open REAL,
                    high REAL,
                    low REAL,
                    volume REAL,
                    turnover REAL,
                    change_value REAL,
                    data_date TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS watchlist (
                    code TEXT PRIMARY KEY,
                    custom_asset_type TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(code) REFERENCES securities(code)
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
                    quantity REAL NOT NULL CHECK(quantity > 0),
                    price REAL NOT NULL CHECK(price > 0),
                    fee REAL NOT NULL DEFAULT 0,
                    tax REAL NOT NULL DEFAULT 0,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    analysis_date TEXT NOT NULL,
                    data_date TEXT,
                    score REAL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(code, analysis_date)
                );
                CREATE INDEX IF NOT EXISTS idx_trades_code_date ON trades(code, trade_date);
                CREATE INDEX IF NOT EXISTS idx_analyses_date_score ON analyses(analysis_date, score DESC);
                """
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        text = json.dumps(value, ensure_ascii=False)
        with self.connect() as con:
            con.execute(
                """INSERT INTO settings(key,value,updated_at) VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, text, _utc_now()),
            )

    def upsert_securities(self, rows: Iterable[dict[str, Any]]) -> int:
        payload = []
        now = _utc_now()
        for r in rows:
            payload.append((str(r.get("code", "")).strip(),str(r.get("name", "")).strip(),str(r.get("exchange", "")).strip(),str(r.get("asset_type", "STOCK")).strip(),r.get("close"), r.get("open"), r.get("high"), r.get("low"),r.get("volume"), r.get("turnover"), r.get("change_value"),r.get("data_date"), now))
        payload = [p for p in payload if p[0] and p[1]]
        if not payload:
            return 0
        with self.connect() as con:
            con.executemany(
                """
                INSERT INTO securities(code,name,exchange,asset_type,close,open,high,low,volume,turnover,change_value,data_date,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(code) DO UPDATE SET
                    name=excluded.name, exchange=excluded.exchange, asset_type=excluded.asset_type,
                    close=excluded.close, open=excluded.open, high=excluded.high, low=excluded.low,
                    volume=excluded.volume, turnover=excluded.turnover, change_value=excluded.change_value,
                    data_date=excluded.data_date, updated_at=excluded.updated_at
                """, payload)
        return len(payload)

    def list_securities(self, asset_filter: str = "ALL", limit: int | None = None, order_by_turnover: bool = True) -> list[dict[str, Any]]:
        clauses, args = [], []
        if asset_filter == "STOCK": clauses.append("asset_type='STOCK'")
        elif asset_filter == "ETF": clauses.append("asset_type<>'STOCK'")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        order = " ORDER BY COALESCE(turnover,0) DESC" if order_by_turnover else " ORDER BY code"
        lim = " LIMIT ?" if limit else ""
        if limit: args.append(limit)
        with self.connect() as con: rows = con.execute(f"SELECT * FROM securities{where}{order}{lim}", args).fetchall()
        return [dict(r) for r in rows]

    def get_security(self, code: str) -> dict[str, Any] | None:
        with self.connect() as con: row = con.execute("SELECT * FROM securities WHERE code=?", (code,)).fetchone()
        return dict(row) if row else None

    def add_watch(self, code: str, custom_asset_type: str | None = None, note: str = "") -> None:
        with self.connect() as con:
            con.execute("""INSERT INTO watchlist(code,custom_asset_type,note,created_at) VALUES(?,?,?,?)
                   ON CONFLICT(code) DO UPDATE SET custom_asset_type=excluded.custom_asset_type,note=excluded.note""",(code, custom_asset_type, note, _utc_now()))

    def remove_watch(self, code: str) -> None:
        with self.connect() as con: con.execute("DELETE FROM watchlist WHERE code=?", (code,))

    def list_watchlist(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("""SELECT w.code, s.name, s.exchange,COALESCE(w.custom_asset_type,s.asset_type) AS asset_type,w.note, s.close, s.data_date, w.created_at FROM watchlist w JOIN securities s ON s.code=w.code ORDER BY w.created_at DESC""").fetchall()
        return [dict(r) for r in rows]

    def add_trade(self, trade: dict[str, Any]) -> int:
        with self.connect() as con:
            cur = con.execute("""INSERT INTO trades(trade_date,code,side,quantity,price,fee,tax,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",(trade["trade_date"], trade["code"], trade["side"], float(trade["quantity"]),float(trade["price"]), float(trade.get("fee", 0) or 0),float(trade.get("tax", 0) or 0), trade.get("note", ""), _utc_now()))
            return int(cur.lastrowid)

    def delete_trade(self, trade_id: int) -> None:
        with self.connect() as con: con.execute("DELETE FROM trades WHERE id=?", (trade_id,))

    def list_trades(self, code: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM trades"; args: tuple[Any, ...] = ()
        if code: query += " WHERE code=?"; args = (code,)
        query += " ORDER BY trade_date DESC, id DESC"
        with self.connect() as con: rows = con.execute(query, args).fetchall()
        return [dict(r) for r in rows]

    def positions(self) -> list[dict[str, Any]]:
        trades = sorted(self.list_trades(), key=lambda x: (x["trade_date"], x["id"])); state = {}
        for t in trades:
            p = state.setdefault(t["code"], {"quantity": 0.0, "cost": 0.0, "realized": 0.0}); qty, px = float(t["quantity"]), float(t["price"]); fees = float(t.get("fee", 0) or 0) + float(t.get("tax", 0) or 0)
            if t["side"] == "BUY": p["cost"] += qty * px + fees; p["quantity"] += qty
            else:
                sell_qty = min(qty, p["quantity"]); avg = p["cost"] / p["quantity"] if p["quantity"] > 0 else 0
                p["realized"] += sell_qty * px - fees - sell_qty * avg; p["quantity"] -= sell_qty; p["cost"] -= sell_qty * avg
                if p["quantity"] <= 1e-9: p["quantity"], p["cost"] = 0.0, 0.0
        out = []
        for code, p in state.items():
            if p["quantity"] <= 0: continue
            sec = self.get_security(code) or {"name": code, "close": None}; avg = p["cost"] / p["quantity"] if p["quantity"] else None; close = sec.get("close"); unrealized = (close - avg) * p["quantity"] if close is not None and avg is not None else None
            out.append({"code": code, "name": sec.get("name", code), "quantity": p["quantity"],"avg_cost": avg, "close": close, "unrealized": unrealized,"realized": p["realized"]})
        return sorted(out, key=lambda x: x["code"])

    def get_position(self, code: str) -> dict[str, Any] | None:
        return next((p for p in self.positions() if p["code"] == code), None)

    def save_analysis(self, result: dict[str, Any], analysis_date: str) -> None:
        with self.connect() as con:
            con.execute("""INSERT INTO analyses(code,analysis_date,data_date,score,result_json,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(code,analysis_date) DO UPDATE SET data_date=excluded.data_date,score=excluded.score,result_json=excluded.result_json,created_at=excluded.created_at""",(result["code"], analysis_date, result.get("data_date"), result.get("score"),json.dumps(result, ensure_ascii=False), _utc_now()))

    def latest_analysis(self, code: str) -> dict[str, Any] | None:
        with self.connect() as con: row = con.execute("SELECT result_json FROM analyses WHERE code=? ORDER BY analysis_date DESC LIMIT 1",(code,)).fetchone()
        return json.loads(row["result_json"]) if row else None

    def latest_scan(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as con:
            date_row = con.execute("SELECT MAX(analysis_date) d FROM analyses").fetchone(); latest = date_row["d"] if date_row else None
            if not latest: return []
            rows = con.execute("SELECT result_json FROM analyses WHERE analysis_date=? ORDER BY score DESC LIMIT ?",(latest, limit)).fetchall()
        return [json.loads(r["result_json"]) for r in rows]

    def export_user_data(self) -> dict[str, Any]:
        with self.connect() as con:
            setting_rows = con.execute("SELECT key,value FROM settings WHERE key IN ('capital','risk_pct','max_position_pct')").fetchall(); watch_rows = con.execute("SELECT code,custom_asset_type,note,created_at FROM watchlist ORDER BY created_at").fetchall(); trade_rows = con.execute("SELECT trade_date,code,side,quantity,price,fee,tax,note,created_at FROM trades ORDER BY trade_date,id").fetchall()
        settings = {}
        for row in setting_rows:
            try: settings[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError: settings[row["key"]] = row["value"]
        return {"schema_version":1,"exported_at":_utc_now(),"settings":settings,"watchlist":[dict(r) for r in watch_rows],"trades":[dict(r) for r in trade_rows]}

    def restore_user_data(self, payload: dict[str, Any], replace: bool = True) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("schema_version") != 1: raise ValueError("備份格式不正確或版本不支援")
        settings=payload.get("settings") or {}; watchlist=payload.get("watchlist") or []; trades=payload.get("trades") or []
        if not isinstance(settings,dict) or not isinstance(watchlist,list) or not isinstance(trades,list): raise ValueError("備份內容結構不正確")
        warnings=[]; restored_watch=0; restored_trades=0
        with self.connect() as con:
            if replace: con.execute("DELETE FROM watchlist"); con.execute("DELETE FROM trades")
            for key,value in settings.items():
                if key not in {"capital","risk_pct","max_position_pct"}: continue
                con.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",(key,json.dumps(value,ensure_ascii=False),_utc_now()))
            known={r["code"] for r in con.execute("SELECT code FROM securities").fetchall()}
            for item in watchlist:
                if not isinstance(item,dict): continue
                code=str(item.get("code","")).strip()
                if not code: continue
                if code not in known: warnings.append(f"{code} 尚未出現在市場清單，未恢復鎖定"); continue
                con.execute("INSERT INTO watchlist(code,custom_asset_type,note,created_at) VALUES(?,?,?,?) ON CONFLICT(code) DO UPDATE SET custom_asset_type=excluded.custom_asset_type,note=excluded.note",(code,item.get("custom_asset_type"),str(item.get("note","")),str(item.get("created_at") or _utc_now()))); restored_watch += 1
            for item in trades:
                if not isinstance(item,dict): continue
                try:
                    side=str(item.get("side","")).upper(); qty=float(item.get("quantity",0)); price=float(item.get("price",0))
                    if side not in {"BUY","SELL"} or qty<=0 or price<=0: raise ValueError
                    con.execute("INSERT INTO trades(trade_date,code,side,quantity,price,fee,tax,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(str(item["trade_date"]),str(item["code"]),side,qty,price,float(item.get("fee",0) or 0),float(item.get("tax",0) or 0),str(item.get("note","")),str(item.get("created_at") or _utc_now()))); restored_trades += 1
                except (KeyError,TypeError,ValueError): warnings.append("有一筆交易格式不正確，已略過")
        return {"ok":True,"watchlist_count":restored_watch,"trade_count":restored_trades,"warnings":warnings}

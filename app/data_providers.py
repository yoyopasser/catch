from __future__ import annotations

import json
import math
import re
import time as time_mod
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests

from .config import (
    DEFAULTS,
    FINMIND_URL,
    HISTORY_DIR,
    TPEX_DAILY_ALL_URL,
    TWSE_DAILY_ALL_URL,
    TWSE_MIS_URL,
    USER_AGENT,
    YAHOO_CHART_URL,
)

NUMERIC_RE = re.compile(r"[^0-9.\-]")
TAIPEI = ZoneInfo("Asia/Taipei")


def _normalize_date_value(value: Any, fallback: str | None = None) -> str | None:
    if value is None or str(value).strip() == "":
        return fallback
    text = str(value).strip()
    digits = re.sub(r"[^0-9]", "", text)
    try:
        if len(digits) == 8 and int(digits[:4]) >= 1900:
            return datetime.strptime(digits, "%Y%m%d").date().isoformat()
        if len(digits) == 7:
            year = int(digits[:3]) + 1911
            return date(year, int(digits[3:5]), int(digits[5:7])).isoformat()
        if "/" in text:
            parts = text.split("/")
            if len(parts) == 3 and int(parts[0]) < 1911:
                return date(int(parts[0]) + 1911, int(parts[1]), int(parts[2])).isoformat()
        return pd.to_datetime(text).date().isoformat()
    except Exception:
        return fallback


def _response_data_date(response: requests.Response) -> str:
    last_modified = response.headers.get("Last-Modified")
    if last_modified:
        try:
            return parsedate_to_datetime(last_modified).astimezone(TAIPEI).date().isoformat()
        except Exception:
            pass
    today = datetime.now(TAIPEI).date()
    while today.weekday() >= 5:
        today -= timedelta(days=1)
    return today.isoformat()


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, np.number)):
        if pd.isna(value):
            return None
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "---", "-", "除權", "除息", "除權息"}:
        return None
    text = NUMERIC_RE.sub("", text)
    try:
        return float(text)
    except ValueError:
        return None


def infer_asset_type(code: str, name: str) -> str:
    code, name = str(code), str(name)
    if not (code.startswith("00") or "ETF" in name.upper()):
        return "STOCK"
    leveraged_words = ("正2", "正向2", "兩倍", "2X", "槓桿")
    inverse_words = ("反1", "反向", "-1X")
    if any(w in name.upper() for w in leveraged_words + inverse_words):
        return "LEVERAGED_INVERSE_ETF"
    if any(w in name for w in ("債", "公司債", "公債", "金融債")):
        return "BOND_ETF"
    if any(w in name for w in ("黃金", "原油", "白銀", "銅", "能源", "商品")):
        return "COMMODITY_ETF"
    if any(w in name for w in ("美國", "日本", "印度", "越南", "中國", "香港", "全球", "那斯達克", "標普", "費城", "韓國")):
        return "OVERSEAS_EQUITY_ETF"
    return "DOMESTIC_EQUITY_ETF"


class DataError(RuntimeError):
    pass


class MarketDataService:
    def __init__(self, timeout: int = DEFAULTS.request_timeout_seconds):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"})

    def fetch_official_universe(self) -> tuple[list[dict[str, Any]], list[str]]:
        rows, warnings = [], []
        try:
            rows.extend(self._fetch_twse_daily())
        except Exception as exc:
            warnings.append(f"上市資料取得失敗：{exc}")
        try:
            rows.extend(self._fetch_tpex_daily())
        except Exception as exc:
            warnings.append(f"上櫃資料取得失敗：{exc}")
        if not rows:
            raise DataError("上市與上櫃資料皆無法取得。請檢查網路或稍後重試。")
        return rows, warnings

    def _fetch_twse_daily(self) -> list[dict[str, Any]]:
        r = self.session.get(TWSE_DAILY_ALL_URL, timeout=self.timeout); r.raise_for_status(); payload = r.json(); response_date = _response_data_date(r)
        if not isinstance(payload, list): raise DataError("TWSE 回傳格式不是清單")
        out=[]
        for item in payload:
            code=str(item.get("Code") or item.get("證券代號") or "").strip(); name=str(item.get("Name") or item.get("證券名稱") or "").strip()
            if not code or not name: continue
            out.append({"code":code,"name":name,"exchange":"TWSE","asset_type":infer_asset_type(code,name),"open":_number(item.get("OpeningPrice") or item.get("開盤價")),"high":_number(item.get("HighestPrice") or item.get("最高價")),"low":_number(item.get("LowestPrice") or item.get("最低價")),"close":_number(item.get("ClosingPrice") or item.get("收盤價")),"volume":_number(item.get("TradeVolume") or item.get("成交股數")),"turnover":_number(item.get("TradeValue") or item.get("成交金額")),"change_value":_number(item.get("Change") or item.get("漲跌價差")),"data_date":_normalize_date_value(item.get("Date") or item.get("日期"),response_date)})
        if not out: raise DataError("TWSE 回傳資料無有效股票")
        return out

    def _fetch_tpex_daily(self) -> list[dict[str, Any]]:
        r=self.session.get(TPEX_DAILY_ALL_URL,params={"l":"zh-tw"},timeout=self.timeout); r.raise_for_status(); payload=r.json(); response_date=_response_data_date(r)
        if isinstance(payload,dict): payload=payload.get("data") or payload.get("aaData") or payload.get("tables") or []
        if not isinstance(payload,list): raise DataError("TPEx 回傳格式不是清單")
        out=[]
        for item in payload:
            if isinstance(item,list):
                if len(item)<9: continue
                code,name=str(item[0]).strip(),str(item[1]).strip(); close,change,open_,high,low,volume,turnover=(_number(item[2]),_number(item[3]),_number(item[4]),_number(item[5]),_number(item[6]),_number(item[7]),_number(item[8])); data_date=response_date
            else:
                code=str(item.get("SecuritiesCompanyCode") or item.get("Code") or item.get("證券代號") or "").strip(); name=str(item.get("CompanyName") or item.get("Name") or item.get("證券名稱") or "").strip(); close=_number(item.get("Close") or item.get("ClosingPrice") or item.get("收盤價")); change=_number(item.get("Change") or item.get("漲跌") or item.get("漲跌價差")); open_=_number(item.get("Open") or item.get("OpeningPrice") or item.get("開盤價")); high=_number(item.get("High") or item.get("HighestPrice") or item.get("最高價")); low=_number(item.get("Low") or item.get("LowestPrice") or item.get("最低價")); volume=_number(item.get("TradingShares") or item.get("TradeVolume") or item.get("成交股數")); turnover=_number(item.get("TransactionAmount") or item.get("TradeValue") or item.get("成交金額")); data_date=_normalize_date_value(item.get("Date") or item.get("日期"),response_date)
            if not code or not name or close is None: continue
            out.append({"code":code,"name":name,"exchange":"TPEX","asset_type":infer_asset_type(code,name),"open":open_,"high":high,"low":low,"close":close,"volume":volume,"turnover":turnover,"change_value":change,"data_date":data_date})
        if not out: raise DataError("TPEx 回傳資料無有效股票")
        return out

    @staticmethod
    def yahoo_ticker(code: str, exchange: str) -> str:
        return f"{code}.TW" if exchange.upper()=="TWSE" else f"{code}.TWO"

    def fetch_yahoo_symbol(self,ticker:str,days:int=DEFAULTS.history_days)->pd.DataFrame:
        end=datetime.utcnow()+timedelta(days=2); start=end-timedelta(days=max(days*2,400)); url=YAHOO_CHART_URL.format(ticker=ticker); params={"period1":int(start.timestamp()),"period2":int(end.timestamp()),"interval":"1d","events":"div,splits","includeAdjustedClose":"true"}; r=self.session.get(url,params=params,timeout=self.timeout); r.raise_for_status(); payload=r.json(); chart=payload.get("chart",{})
        if chart.get("error"): raise DataError(f"Yahoo {ticker}: {chart['error']}")
        result=(chart.get("result") or [None])[0]
        if not result: raise DataError(f"Yahoo {ticker}: 無歷史資料")
        stamps=result.get("timestamp") or []; quote=((result.get("indicators") or {}).get("quote") or [{}])[0]; adj=((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose"); n=len(stamps)
        def series(name):
            values=quote.get(name) or [None]*n; return (values+[None]*n)[:n]
        df=pd.DataFrame({"date":pd.to_datetime(stamps,unit="s",utc=True).tz_convert("Asia/Taipei").tz_localize(None).normalize(),"open":series("open"),"high":series("high"),"low":series("low"),"close":series("close"),"adj_close":((adj or series("close"))+[None]*n)[:n],"volume":series("volume")})
        return self._normalize_history(df).tail(days)

    def fetch_history(self,code:str,exchange:str,days:int=DEFAULTS.history_days,force:bool=False)->pd.DataFrame:
        cache=HISTORY_DIR/f"{code}_{exchange}.csv"
        if cache.exists() and not force:
            if (time_mod.time()-cache.stat().st_mtime)/3600<=DEFAULTS.history_cache_hours: return self._normalize_history(pd.read_csv(cache,parse_dates=["date"]))
        df=self.fetch_yahoo_symbol(self.yahoo_ticker(code,exchange),days); df.to_csv(cache,index=False); return df

    def fetch_histories(self,securities:Iterable[dict[str,Any]],days:int=DEFAULTS.history_days,force:bool=False,max_workers:int=DEFAULTS.max_workers)->tuple[dict[str,pd.DataFrame],dict[str,str]]:
        items=list(securities); out={}; errors={}; workers=max(1,min(max_workers,12))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures={pool.submit(self.fetch_history,s["code"],s["exchange"],days,force):s for s in items}
            for fut in as_completed(futures):
                sec=futures[fut]
                try: out[sec["code"]]=fut.result()
                except Exception as exc: errors[sec["code"]]=str(exc)
        return out,errors

    def fetch_realtime_quotes(self,securities:Iterable[dict[str,Any]])->tuple[list[dict[str,Any]],list[str]]:
        securities=list(securities)
        if not securities: return [],[]
        warnings=[]; rows=[]
        for offset in range(0,len(securities),40):
            chunk=securities[offset:offset+40]; ex_ch="|".join(f"{'tse' if s['exchange']=='TWSE' else 'otc'}_{s['code']}.tw" for s in chunk)
            try:
                r=self.session.get(TWSE_MIS_URL,params={"ex_ch":ex_ch,"json":"1","delay":"0"},headers={"Referer":"https://mis.twse.com.tw/stock/fibest.jsp"},timeout=self.timeout); r.raise_for_status(); payload=r.json()
                if payload.get("rtcode") not in ("0000",0,None): raise DataError(payload.get("rtmessage","MIS 即時資料錯誤"))
                for item in payload.get("msgArray",[]):
                    last=_number(item.get("z")) or _number(item.get("y")); rows.append({"code":str(item.get("c","")),"name":str(item.get("n","")),"exchange":"TWSE" if item.get("ex")=="tse" else "TPEX","last":last,"open":_number(item.get("o")),"high":_number(item.get("h")),"low":_number(item.get("l")),"previous_close":_number(item.get("y")),"volume_lots":_number(item.get("v")),"trade_date":item.get("d"),"trade_time":item.get("t"),"source":"TWSE MIS"})
            except Exception as exc: warnings.append(f"即時報價區塊取得失敗：{exc}")
        return rows,warnings

    @staticmethod
    def _normalize_history(df:pd.DataFrame)->pd.DataFrame:
        needed=["date","open","high","low","close","volume"]; missing=[c for c in needed if c not in df.columns]
        if missing: raise DataError(f"歷史資料缺少欄位：{','.join(missing)}")
        out=df.copy(); out["date"]=pd.to_datetime(out["date"],errors="coerce")
        for c in ["open","high","low","close","volume"]: out[c]=pd.to_numeric(out[c],errors="coerce")
        if "adj_close" not in out.columns: out["adj_close"]=out["close"]
        out["adj_close"]=pd.to_numeric(out["adj_close"],errors="coerce"); out=out.dropna(subset=["date","open","high","low","close"]); out=out[out["close"]>0].sort_values("date").drop_duplicates("date",keep="last")
        return out.reset_index(drop=True)


def synthetic_demo_history(kind:str="bull_breakout",rows:int=180,seed:int=7)->pd.DataFrame:
    rng=np.random.default_rng(seed); dates=pd.bdate_range(end=pd.Timestamp.today().normalize(),periods=rows); drift=-0.0012 if kind=="bear" else 0.0010; returns=rng.normal(drift,0.012,rows); price=60*np.exp(np.cumsum(returns))
    if kind=="bull_breakout": price[-20:-1]=np.linspace(price[-21]*0.99,price[-21]*1.02,19); price[-1]=max(price[-20:-1])*1.035
    close=price; open_=close*(1+rng.normal(0,0.004,rows)); high=np.maximum(open_,close)*(1+rng.uniform(0.002,0.012,rows)); low=np.minimum(open_,close)*(1-rng.uniform(0.002,0.012,rows)); volume=rng.integers(1_000_000,5_000_000,rows).astype(float)
    if kind=="bull_breakout": volume[-1]=volume[-2]*1.7; open_[-1]=close[-1]*0.975
    return pd.DataFrame({"date":dates,"open":open_,"high":high,"low":low,"close":close,"adj_close":close,"volume":volume})

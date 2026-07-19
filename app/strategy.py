from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config import DEFAULTS
from .models import AnalysisResult

ETF_TYPES={"DOMESTIC_EQUITY_ETF","OVERSEAS_EQUITY_ETF","BOND_ETF","COMMODITY_ETF","LEVERAGED_INVERSE_ETF"}

@dataclass
class PivotSummary:
    highs:list[tuple[int,float]]
    lows:list[tuple[int,float]]

def _safe(v:Any,digits:int=2)->float|None:
    try:
        if v is None or pd.isna(v) or np.isinf(v): return None
        return round(float(v),digits)
    except (TypeError,ValueError): return None

def add_indicators(df:pd.DataFrame)->pd.DataFrame:
    d=df.copy().sort_values("date").reset_index(drop=True)
    for n in (5,20,60): d[f"ma{n}"]=d["close"].rolling(n).mean()
    prev_close=d["close"].shift(1); tr=pd.concat([d["high"]-d["low"],(d["high"]-prev_close).abs(),(d["low"]-prev_close).abs()],axis=1).max(axis=1)
    d["atr14"]=tr.rolling(14).mean(); d["vol_med20"]=d["volume"].rolling(20).median(); d["vol_ratio20"]=d["volume"]/d["vol_med20"].replace(0,np.nan); d["body_pct"]=(d["close"]-d["open"])/d["open"].replace(0,np.nan); d["prev20_high"]=d["high"].shift(1).rolling(20).max(); d["prev20_low"]=d["low"].shift(1).rolling(20).min(); d["prev60_high"]=d["high"].shift(1).rolling(60).max(); d["prev60_low"]=d["low"].shift(1).rolling(60).min(); d["ma20_slope5"]=d["ma20"]-d["ma20"].shift(5); d["ma60_slope10"]=d["ma60"]-d["ma60"].shift(10)
    return d

def confirmed_pivots(df:pd.DataFrame,window:int=DEFAULTS.pivot_window)->PivotSummary:
    highs=[]; lows=[]
    for i in range(window,len(df)-window):
        hs=df["high"].iloc[i-window:i+window+1]; ls=df["low"].iloc[i-window:i+window+1]; h=float(df["high"].iloc[i]); l=float(df["low"].iloc[i])
        if h==float(hs.max()) and (hs==h).sum()==1: highs.append((i,h))
        if l==float(ls.min()) and (ls==l).sum()==1: lows.append((i,l))
    return PivotSummary(highs,lows)

def classify_structure(pivots:PivotSummary)->tuple[str,list[str]]:
    if len(pivots.highs)<2 or len(pivots.lows)<2: return "資料不足",["尚未形成兩組可確認的轉折高點與低點。"]
    h1,h2=pivots.highs[-2][1],pivots.highs[-1][1]; l1,l2=pivots.lows[-2][1],pivots.lows[-1][1]
    if h2>h1 and l2>l1: return "多頭",[f"最近兩個確認高點提高（{h1:.2f}→{h2:.2f}）。",f"最近兩個確認低點提高（{l1:.2f}→{l2:.2f}）。"]
    if h2<h1 and l2<l1: return "空頭",[f"最近兩個確認高點降低（{h1:.2f}→{h2:.2f}）。",f"最近兩個確認低點降低（{l1:.2f}→{l2:.2f}）。"]
    return "盤整／轉折",["高低點方向不一致，趨勢尚未完整確認。"]

def _descending_correction_breakout(d,p):
    if len(p.highs)<2:return False
    (i1,h1),(i2,h2)=p.highs[-2],p.highs[-1]
    if i2<=i1 or h2>=h1 or len(d)-1<=i2:return False
    slope=(h2-h1)/(i2-i1); line_now=h2+slope*((len(d)-1)-i2); prev_line=h2+slope*((len(d)-2)-i2)
    return bool(d["close"].iloc[-1]>line_now and d["close"].iloc[-2]<=prev_line)

def _latest_support(d,p):
    row=d.iloc[-1]; c=[]
    for key in ("ma20","prev20_high","prev20_low"):
        v=row.get(key)
        if pd.notna(v) and float(v)<float(row["close"]):c.append(float(v))
    if p.lows:c.extend(v for _,v in p.lows[-3:] if v<float(row["close"]))
    return max(c) if c else float(row["low"])

def _next_resistance(d,p):
    close=float(d["close"].iloc[-1]); c=[v for _,v in p.highs[-6:] if v>close]; prev60=d["prev60_high"].iloc[-1]
    if pd.notna(prev60) and float(prev60)>close:c.append(float(prev60))
    return min(c) if c else None

def _params(asset_type):
    body=DEFAULTS.red_body_etf if asset_type in ETF_TYPES else DEFAULTS.red_body_stock; volume=DEFAULTS.volume_ratio_etf if asset_type in ETF_TYPES else DEFAULTS.volume_ratio_stock; extension=DEFAULTS.max_extension_atr_etf if asset_type in ETF_TYPES else DEFAULTS.max_extension_atr_stock
    if asset_type=="BOND_ETF":body,volume=.004,1.05
    if asset_type=="LEVERAGED_INVERSE_ETF":body,volume,extension=.012,1.10,1.5
    return {"body":body,"volume":volume,"extension":extension}

def analyze_security(df:pd.DataFrame,security:dict[str,Any],position:dict[str,Any]|None=None,market_regime:str="未知",formal_close:bool=True)->AnalysisResult:
    code=str(security.get("code","")); name=str(security.get("name",code)); exchange=str(security.get("exchange","")); asset_type=str(security.get("asset_type","STOCK")); position=position or {}; qty=float(position.get("quantity",0) or 0); avg_cost=position.get("avg_cost")
    if df is None or len(df)<DEFAULTS.min_history_rows:
        data_date="" if df is None or df.empty else pd.Timestamp(df["date"].iloc[-1]).date().isoformat(); return AnalysisResult(code=code,name=name,exchange=exchange,asset_type=asset_type,data_date=data_date,data_status="資料不足",score=0,market_state="資料不足",signal="無",today_action="不交易",tomorrow_plan=["補足至少90個有效交易日後重新判斷。"],reasons=["歷史資料不足，無法可靠計算MA60與轉折結構。"],position_qty=qty,avg_cost=_safe(avg_cost))
    d=add_indicators(df); row,prev=d.iloc[-1],d.iloc[-2]; piv=confirmed_pivots(d); structure,reasons=classify_structure(piv); p=_params(asset_type); close,open_,high,low=map(float,(row["close"],row["open"],row["high"],row["low"])); ma5,ma20,ma60,atr=map(float,(row["ma5"],row["ma20"],row["ma60"],row["atr14"])); vol_ratio=float(row["vol_ratio20"]) if pd.notna(row["vol_ratio20"]) else 0; body_pct=float(row["body_pct"]) if pd.notna(row["body_pct"]) else 0; extension=(close-ma20)/atr if atr>0 else np.nan
    ma_bull=close>ma20>ma60 and row["ma20_slope5"]>0 and row["ma60_slope10"]>0; break20=bool(pd.notna(row["prev20_high"]) and close>float(row["prev20_high"])); close_break=break20 and (pd.isna(prev["prev20_high"]) or float(prev["close"])<=float(prev["prev20_high"])); volume_ok=vol_ratio>=p["volume"]; strong_red=close>open_ and body_pct>=p["body"]; abc=_descending_correction_breakout(d,piv); support=_latest_support(d,piv); near_support=abs(close-ma20)<=.75*atr or abs(close-support)<=.75*atr; stop=min(low,support) if close_break else support; resistance=_next_resistance(d,piv); resistance=resistance if resistance is not None else close+2*max(close-stop,atr*.6); risk=close-stop; rr=(resistance-close)/risk if risk>0 else None
    warnings=[]; stale_days=(datetime.now(ZoneInfo("Asia/Taipei")).date()-pd.Timestamp(row["date"]).date()).days; stale=stale_days>7; score=24 if structure=="多頭" else 8 if structure=="盤整／轉折" else -10; signal="無"
    if stale:warnings.append(f"最新K線距今已{stale_days}天，資料可能過舊；不得據此建立新部位。")
    if ma_bull:score+=20;reasons.append("收盤價位於上揚的MA20與MA60之上，且呈多頭排列。")
    elif close>ma20 and row["ma20_slope5"]>0:score+=9;reasons.append("股價站上上揚MA20，但長均線條件尚未完全一致。")
    if close_break:score+=18;signal="盤整突破";reasons.append("收盤價正式突破前20日壓力，不是只有盤中刺穿。")
    if abc:score+=12;signal="ABC修正突破" if signal=="無" else signal+"＋ABC修正突破"
    if near_support and structure=="多頭" and close>prev["high"] and close>open_:score+=15;signal="回檔後再上漲" if signal=="無" else signal+"＋回檔再上漲"
    if volume_ok:score+=8
    elif signal!="無":score-=5;warnings.append(f"量能僅為20日中位量的{vol_ratio:.2f}倍，訊號品質需降級。")
    if strong_red:score+=7
    elif signal!="無":score-=4
    if rr is not None:
        if rr>=2:score+=12
        elif rr>=1.5:score+=5
        else:score-=12;warnings.append(f"估算風險報酬比僅{rr:.2f}，上方空間相對不足。")
    if pd.notna(extension) and extension>p["extension"]:score-=16;warnings.append(f"股價已高於MA20約{extension:.2f}個ATR，屬追價區。")
    if market_regime=="空頭":score-=12
    elif market_regime=="多頭":score+=5
    latest_low=piv.lows[-1][1] if piv.lows else None; broke=latest_low is not None and close<latest_low; heavy_black=body_pct<=-p["body"] and vol_ratio>=p["volume"]
    if qty>0:
        pnl=(close/float(avg_cost)-1) if avg_cost else None
        if broke or (avg_cost and close<=min(stop,float(avg_cost)*.93)):action="全部退出";signal="多頭結構失效／停損"
        elif close<ma20:action="減碼並提高停損";signal="多頭轉弱"
        elif heavy_black and pnl is not None and pnl>=.1:action="優先停利／至少減碼";signal="高檔量價轉弱"
        elif close<ma5:action="續抱但可分批減碼";signal="短線轉弱"
        else:action="續抱"
    else:
        if stale:action="資料過舊，不產生新訊號"
        elif signal!="無" and score>=70 and rr is not None and rr>=1.5:action="列為隔日優先候選"
        elif signal!="無" and score>=55:action="觀察／小部位試單"
        elif structure=="多頭":action="等待合格進場型態，不追價"
        elif structure=="空頭":action="不做多"
        else:action="等待方向確認"
    if not formal_close:
        warnings.insert(0,"目前為盤中或收盤資料整理期，所有突破／跌破僅為暫估，正式行動須等收盤確認。")
        if qty<=0 and action.startswith("列為"):action="盤中暫估：收盤後再決定"
    entry_low=close-.2*atr;entry_high=close+.25*atr
    if qty>0:tomorrow=[f"若收盤守在MA20（約{ma20:.2f}）及停損價（約{stop:.2f}）之上：依今日結論續抱。",f"若收盤跌破{stop:.2f}：執行退出，不以盤中反彈取消停損。","若高開後爆量不漲或出現長黑：先減碼保護獲利。"]
    elif signal!="無":tomorrow=[f"若開盤落在約{entry_low:.2f}～{entry_high:.2f}，且盤中未跌破{stop:.2f}，收盤仍守住突破位：可依風險額度進場。",f"若跳空高開超過約{close+atr:.2f}：不追價，等待回測或下一次型態。",f"若收盤跌回突破位置或跌破{stop:.2f}：取消買進計畫／視為假突破。"]
    else:tomorrow=["若未出現收盤確認的突破或回檔後再上漲：繼續等待。",f"若跌破MA20（約{ma20:.2f}）或最近重要支撐（約{support:.2f}）：移出做多優先名單。","不得因單根盤中紅K或消息而跳過既定進場條件。"]
    return AnalysisResult(code=code,name=name,exchange=exchange,asset_type=asset_type,data_date=pd.Timestamp(row["date"]).date().isoformat(),data_status="收盤正式確認" if formal_close else "盤中暫估",score=max(0,min(100,round(score,1))),market_state=structure,signal=signal,today_action=action,tomorrow_plan=tomorrow,reasons=reasons[:8],warnings=warnings,close=_safe(close),ma5=_safe(ma5),ma20=_safe(ma20),ma60=_safe(ma60),atr14=_safe(atr),volume_ratio=_safe(vol_ratio),entry_low=_safe(entry_low),entry_high=_safe(entry_high),stop_loss=_safe(stop),resistance=_safe(resistance),risk_reward=_safe(rr),position_qty=qty,avg_cost=_safe(avg_cost),metadata={"extension_atr":_safe(extension),"data_stale":stale})

def analyze_market_index(df:pd.DataFrame)->str:
    if df is None or len(df)<DEFAULTS.min_history_rows:return "未知"
    d=add_indicators(df); structure,_=classify_structure(confirmed_pivots(d)); row=d.iloc[-1]
    if structure=="多頭" and row["close"]>row["ma20"]>row["ma60"]:return "多頭"
    if structure=="空頭" and row["close"]<row["ma20"]<row["ma60"]:return "空頭"
    return "盤整／轉折"

def position_size(capital:float,entry:float,stop:float,risk_pct:float=DEFAULTS.default_risk_per_trade_pct,max_position_pct:float=DEFAULTS.max_position_pct)->dict[str,float]:
    if capital<=0 or entry<=0 or stop<=0 or entry<=stop:return {"shares":0,"risk_amount":0,"position_value":0}
    risk_amount=capital*max(.001,min(risk_pct,.05)); per_share=entry-stop; shares=max(0,min(int(risk_amount//per_share),int((capital*max_position_pct)//entry)))
    return {"shares":shares,"risk_amount":round(shares*per_share,2),"position_value":round(shares*entry,2)}

from __future__ import annotations
import threading,uuid
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime
from typing import Any,Callable
import pandas as pd
from .config import DEFAULTS
from .database import Database
from .data_providers import MarketDataService
from .market_clock import market_phase
from .strategy import analyze_market_index,analyze_security

class Scanner:
    def __init__(self,db:Database,data:MarketDataService):self.db=db;self.data=data
    def refresh_universe(self):
        rows,warnings=self.data.fetch_official_universe();count=self.db.upsert_securities(rows);self.db.set_setting("last_universe_refresh",datetime.utcnow().isoformat());return {"count":count,"warnings":warnings}
    @staticmethod
    def _scope_limit(scope):return {"liquid200":200,"liquid500":500,"liquid1000":1000,"full":None}.get(scope,500)
    def choose_universe(self,scope,asset_filter):
        if scope=="watchlist":return [self.db.get_security(x["code"]) for x in self.db.list_watchlist() if self.db.get_security(x["code"])]
        return self.db.list_securities(asset_filter=asset_filter,limit=self._scope_limit(scope),order_by_turnover=True)
    @staticmethod
    def _merge_latest_bar(history,sec):
        if history.empty or sec.get("close") is None or not sec.get("data_date"):return history
        try:
            latest=pd.to_datetime(sec["data_date"],errors="coerce")
            if pd.isna(latest):return history
            latest=latest.normalize();h=history.copy()
            if latest<h["date"].max().normalize():return h
            row={"date":latest,"open":sec.get("open") or sec["close"],"high":sec.get("high") or sec["close"],"low":sec.get("low") or sec["close"],"close":sec["close"],"adj_close":sec["close"],"volume":sec.get("volume") or 0}
            if latest==h["date"].max().normalize():h=h[h["date"].dt.normalize()!=latest]
            return pd.concat([h,pd.DataFrame([row])],ignore_index=True).sort_values("date")
        except Exception:return history
    def _market_regime(self):
        try:return analyze_market_index(self.data.fetch_yahoo_symbol("^TWII",260))
        except Exception:return "未知"
    def run_scan(self,scope="liquid500",asset_filter="ALL",force_history=False,progress:Callable[[dict[str,Any]],None]|None=None):
        if not self.db.list_securities(limit=1):self.refresh_universe()
        universe=self.choose_universe(scope,asset_filter)
        if not universe:raise RuntimeError("篩選母體為空，請先更新市場資料。")
        phase=market_phase();regime=self._market_regime();total=len(universe);results=[];errors={};analysis_date=datetime.now().date().isoformat()
        def emit(done,code=""):
            if progress:progress({"done":done,"total":total,"code":code,"market_regime":regime,"phase":phase["phase"]})
        emit(0)
        with ThreadPoolExecutor(max_workers=min(DEFAULTS.max_workers,max(1,total))) as pool:
            fs={pool.submit(self.data.fetch_history,s["code"],s["exchange"],DEFAULTS.history_days,force_history):s for s in universe};done=0
            for fut in as_completed(fs):
                sec=fs[fut]
                try:
                    result=analyze_security(self._merge_latest_bar(fut.result(),sec),sec,self.db.get_position(sec["code"]),regime,bool(phase["is_formal_close_mode"])).to_dict();self.db.save_analysis(result,analysis_date);results.append(result)
                except Exception as exc:errors[sec["code"]]=str(exc)
                done+=1;emit(done,sec["code"])
        results.sort(key=lambda x:(x.get("score",0),x.get("risk_reward") or 0),reverse=True)
        return {"scope":scope,"asset_filter":asset_filter,"market_regime":regime,"market_phase":phase,"total":total,"completed":len(results),"failed":len(errors),"errors":errors,"results":results,"analysis_date":analysis_date}
    def analyze_codes(self,codes,force_history=False):
        phase=market_phase();regime=self._market_regime();out=[]
        for sec in [self.db.get_security(c) for c in codes]:
            if not sec:continue
            history=self._merge_latest_bar(self.data.fetch_history(sec["code"],sec["exchange"],force=force_history),sec);result=analyze_security(history,sec,self.db.get_position(sec["code"]),regime,bool(phase["is_formal_close_mode"])).to_dict();self.db.save_analysis(result,datetime.now().date().isoformat());out.append(result)
        return out

class ScanJobManager:
    def __init__(self,scanner):self.scanner=scanner;self.jobs={};self.lock=threading.Lock()
    def start(self,scope,asset_filter,force_history=False):
        job_id=uuid.uuid4().hex[:12];self.jobs[job_id]={"id":job_id,"status":"queued","done":0,"total":0,"result":None,"error":None}
        def update(info):
            with self.lock:self.jobs[job_id].update(info);self.jobs[job_id]["status"]="running"
        def work():
            try:
                result=self.scanner.run_scan(scope,asset_filter,force_history,update)
                with self.lock:self.jobs[job_id].update({"status":"completed","result":result,"done":result["total"],"total":result["total"]})
            except Exception as exc:
                with self.lock:self.jobs[job_id].update({"status":"failed","error":str(exc)})
        threading.Thread(target=work,daemon=True).start();return job_id
    def get(self,job_id):
        with self.lock:return dict(self.jobs[job_id]) if job_id in self.jobs else None

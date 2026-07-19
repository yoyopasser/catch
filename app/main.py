from __future__ import annotations

import csv, io, json
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from .config import DEFAULTS
from .database import Database
from .data_providers import DataError, MarketDataService
from .market_clock import market_phase
from .scanner import Scanner, ScanJobManager
from .strategy import position_size

app=FastAPI(title="台股決策工具",version="1.1.0")
db=Database(); data_service=MarketDataService(); scanner=Scanner(db,data_service); jobs=ScanJobManager(scanner)

class ScanRequest(BaseModel):
    scope:str="liquid200"; asset_filter:str="ALL"; force_history:bool=False
class WatchRequest(BaseModel):
    code:str; note:str=""
class TradeRequest(BaseModel):
    trade_date:str; code:str; side:str; quantity:float=Field(gt=0); price:float=Field(gt=0); fee:float=Field(default=0,ge=0); tax:float=Field(default=0,ge=0); note:str=""
class PositionSizeRequest(BaseModel):
    capital:float=Field(gt=0); entry:float=Field(gt=0); stop:float=Field(gt=0); risk_pct:float=Field(default=.01,gt=0,le=.05); max_position_pct:float=Field(default=.2,gt=0,le=1)

PAGE='''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>台股決策工具</title><style>
:root{font-family:system-ui,-apple-system,"Noto Sans TC",sans-serif;color:#172033;background:#f3f6fb}body{margin:0}.wrap{max-width:1180px;margin:auto;padding:20px}.hero,.card{background:white;border:1px solid #dce3ee;border-radius:18px;padding:20px;margin-bottom:16px;box-shadow:0 8px 28px #20314b0d}h1{margin:0 0 8px}h2{font-size:1.1rem}button,input,select{font:inherit;padding:10px;border:1px solid #bbc7d8;border-radius:10px}button{background:#155eef;color:white;border:0;cursor:pointer}.secondary{background:#e8eef8;color:#172033}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.muted{color:#60708a}.warn{color:#9a4d00}.good{color:#087443}.bad{color:#b42318}table{width:100%;border-collapse:collapse;font-size:.92rem}th,td{text-align:left;padding:9px;border-bottom:1px solid #e7ebf2;vertical-align:top}.scroll{overflow:auto}.pill{display:inline-block;padding:4px 8px;border-radius:999px;background:#edf3ff}.plans{margin:6px 0;padding-left:20px}.status{padding:10px;border-radius:10px;background:#f0f4fa;margin-top:10px}@media(max-width:600px){.wrap{padding:10px}.card,.hero{padding:14px}table{min-width:900px}}
</style></head><body><div class="wrap"><section class="hero"><h1>台股決策工具</h1><p>以收盤確認、趨勢結構、均線、位置、量能、風險報酬與停損優先規則產生條件式方案。</p><div id="market" class="status">載入中…</div></section>
<section class="card"><h2>1. 更新與全市場篩選</h2><div class="toolbar"><button onclick="refreshMarket()">更新上市櫃清單</button><select id="scope"><option value="liquid200">成交值前200</option><option value="liquid500">前500</option><option value="liquid1000">前1000</option><option value="full">全部</option></select><select id="asset"><option value="ALL">股票＋ETF</option><option value="STOCK">股票</option><option value="ETF">ETF</option></select><button onclick="startScan()">開始掃描</button></div><div id="scanStatus" class="status muted">尚未掃描</div><div class="scroll"><table><thead><tr><th>代碼／名稱</th><th>分數</th><th>狀態</th><th>訊號</th><th>今日行動</th><th>停損</th><th>風報比</th><th>原因與隔日方案</th><th></th></tr></thead><tbody id="results"></tbody></table></div></section>
<section class="card"><h2>2. 鎖定清單與每日分析</h2><div class="toolbar"><button onclick="analyzeWatch()">更新並重新分析</button></div><div id="watch" class="grid"></div></section>
<section class="card"><h2>3. 登記買賣</h2><form id="trade" class="grid"><input name="trade_date" type="date" required><input name="code" placeholder="股票代碼" required><select name="side"><option value="BUY">買進</option><option value="SELL">賣出</option></select><input name="quantity" type="number" min="1" placeholder="股數" required><input name="price" type="number" step=".01" placeholder="成交價" required><input name="fee" type="number" step=".01" value="0" placeholder="手續費"><input name="tax" type="number" step=".01" value="0" placeholder="交易稅"><input name="note" placeholder="備註"><button>儲存交易</button></form><div class="scroll"><table><thead><tr><th>日期</th><th>代碼</th><th>方向</th><th>股數</th><th>價格</th><th>費稅</th><th>備註</th></tr></thead><tbody id="trades"></tbody></table></div></section>
<section class="card"><h2>4. 資料備份</h2><p>Codespace 被刪除時資料會消失。備份包含風險設定、自選股與交易紀錄，不包含 Token。</p><div class="toolbar"><a href="/api/backup/export.json"><button>下載完整備份</button></a><input id="backup" type="file" accept=".json"><button class="secondary" onclick="restore()">還原備份</button></div></section>
<p class="muted">本工具只提供研究與紀律輔助，不保證未來漲跌，也不構成個別投資建議。</p></div><script>
const $=s=>document.querySelector(s);const fmt=n=>n==null?'—':Number(n).toFixed(2);async function api(url,opt){const r=await fetch(url,opt);let d;try{d=await r.json()}catch{d=await r.text()}if(!r.ok)throw Error(d.detail||d);return d}function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
async function status(){const d=await api('/api/status');$('#market').innerHTML=`市場：<b>${d.market.phase}</b>　時間：${d.market.now}<br>市場清單：${d.universe_ready?'已就緒':'尚未更新'}　鎖定：${d.watch_count}　持倉：${d.position_count}`}
async function refreshMarket(){try{$('#scanStatus').textContent='更新中…';const d=await api('/api/market/refresh',{method:'POST'});$('#scanStatus').textContent=`已更新 ${d.count} 檔。${(d.warnings||[]).join('；')}`;status()}catch(e){$('#scanStatus').textContent=e.message}}
async function startScan(){try{const d=await api('/api/scan/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope:$('#scope').value,asset_filter:$('#asset').value})});poll(d.job_id)}catch(e){$('#scanStatus').textContent=e.message}}
async function poll(id){const d=await api('/api/scan/'+id);$('#scanStatus').textContent=`${d.status}：${d.done||0}/${d.total||0}`;if(d.status==='completed'){renderResults(d.result.results);return}if(d.status==='failed'){$('#scanStatus').textContent=d.error;return}setTimeout(()=>poll(id),1200)}
function renderResults(rows){$('#results').innerHTML=rows.slice(0,50).map(r=>`<tr><td><b>${esc(r.code)} ${esc(r.name)}</b><br><span class="pill">${esc(r.asset_type)}</span></td><td>${fmt(r.score)}</td><td>${esc(r.market_state)}<br>${esc(r.data_status)}</td><td>${esc(r.signal)}</td><td><b>${esc(r.today_action)}</b></td><td>${fmt(r.stop_loss)}</td><td>${fmt(r.risk_reward)}</td><td>${(r.reasons||[]).slice(0,3).map(esc).join('<br>')}<ol class="plans">${(r.tomorrow_plan||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ol>${(r.warnings||[]).map(x=>`<div class="warn">${esc(x)}</div>`).join('')}</td><td><button onclick="watch('${esc(r.code)}')">鎖定</button></td></tr>`).join('')}
async function watch(code){await api('/api/watchlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})});loadWatch();status()}
async function loadWatch(){const rows=await api('/api/watchlist');$('#watch').innerHTML=rows.map(x=>{const r=x.analysis||{};return `<div class="card"><b>${esc(x.code)} ${esc(x.name)}</b><p>${esc(r.today_action||'尚未分析')}</p><p class="muted">${(r.reasons||[]).slice(0,2).map(esc).join('<br>')}</p><ol>${(r.tomorrow_plan||[]).map(y=>`<li>${esc(y)}</li>`).join('')}</ol><button class="secondary" onclick="unwatch('${esc(x.code)}')">移除</button></div>`}).join('')||'<p class="muted">尚未鎖定股票</p>'}
async function unwatch(c){await api('/api/watchlist/'+c,{method:'DELETE'});loadWatch();status()}async function analyzeWatch(){await api('/api/watchlist/analyze',{method:'POST'});loadWatch()}
$('#trade').addEventListener('submit',async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));['quantity','price','fee','tax'].forEach(k=>o[k]=Number(o[k]||0));try{await api('/api/trades',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});e.target.reset();e.target.trade_date.value=new Date().toISOString().slice(0,10);loadTrades();loadWatch();status()}catch(err){alert(err.message)}})
async function loadTrades(){const rows=await api('/api/trades');$('#trades').innerHTML=rows.map(t=>`<tr><td>${esc(t.trade_date)}</td><td>${esc(t.code)}</td><td>${t.side==='BUY'?'買進':'賣出'}</td><td>${t.quantity}</td><td>${fmt(t.price)}</td><td>${fmt(Number(t.fee)+Number(t.tax))}</td><td>${esc(t.note)}</td></tr>`).join('')}
async function restore(){const f=$('#backup').files[0];if(!f)return alert('請選擇備份檔');if(!confirm('將取代目前自選股與交易紀錄，確定？'))return;const form=new FormData();form.append('file',f);try{await api('/api/backup/import?replace=true',{method:'POST',body:form});location.reload()}catch(e){alert(e.message)}}
$('#trade').trade_date.value=new Date().toISOString().slice(0,10);status();loadWatch();loadTrades();
</script></body></html>'''

@app.get('/',response_class=HTMLResponse)
def home():return PAGE
@app.get('/api/status')
def status():return {'ok':True,'market':market_phase(),'universe_ready':bool(db.list_securities(limit=1)),'last_universe_refresh':db.get_setting('last_universe_refresh'),'watch_count':len(db.list_watchlist()),'position_count':len(db.positions())}
@app.post('/api/market/refresh')
def refresh_market():
    try:return scanner.refresh_universe()
    except Exception as exc:raise HTTPException(502,str(exc)) from exc
@app.post('/api/scan/start')
def start_scan(req:ScanRequest):return {'job_id':jobs.start(req.scope,req.asset_filter,req.force_history)}
@app.get('/api/scan/{job_id}')
def scan_status(job_id:str):
    job=jobs.get(job_id)
    if not job:raise HTTPException(404,'找不到掃描工作')
    return job
@app.get('/api/watchlist')
def get_watchlist():return [{**r,'analysis':db.latest_analysis(r['code'])} for r in db.list_watchlist()]
@app.post('/api/watchlist')
def add_watch(req:WatchRequest):
    if not db.get_security(req.code):raise HTTPException(404,'股票代碼不在市場清單，請先更新')
    db.add_watch(req.code,note=req.note);return {'ok':True}
@app.delete('/api/watchlist/{code}')
def remove_watch(code:str):db.remove_watch(code);return {'ok':True}
@app.post('/api/watchlist/analyze')
def analyze_watchlist():return scanner.analyze_codes([x['code'] for x in db.list_watchlist()])
@app.get('/api/trades')
def get_trades():return db.list_trades()
@app.post('/api/trades')
def add_trade(req:TradeRequest):
    req.side=req.side.upper()
    if req.side not in {'BUY','SELL'}:raise HTTPException(400,'方向錯誤')
    if not db.get_security(req.code):raise HTTPException(404,'股票代碼不在市場清單')
    i=db.add_trade(req.model_dump());db.add_watch(req.code,note='由交易紀錄自動鎖定');return {'ok':True,'id':i}
@app.post('/api/position-size')
def calc_size(req:PositionSizeRequest):return position_size(**req.model_dump())
@app.get('/api/backup/export.json')
def export_backup():
    payload=json.dumps(db.export_user_data(),ensure_ascii=False,indent=2).encode();return StreamingResponse(iter([payload]),media_type='application/json',headers={'Content-Disposition':'attachment; filename=stock-tool-backup.json'})
@app.post('/api/backup/import')
async def import_backup(file:UploadFile=File(...),replace:bool=True):
    raw=await file.read()
    if len(raw)>5*1024*1024:raise HTTPException(413,'備份檔超過 5 MB')
    try:return db.restore_user_data(json.loads(raw.decode('utf-8-sig')),replace)
    except Exception as exc:raise HTTPException(400,str(exc)) from exc

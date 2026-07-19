from pathlib import Path
from app.database import Database
from app.data_providers import synthetic_demo_history
from app.strategy import analyze_security, position_size

SEC={'code':'9999','name':'測試股','exchange':'TWSE','asset_type':'STOCK'}

def test_insufficient_data_refuses_trade():
    r=analyze_security(synthetic_demo_history(rows=50),SEC).to_dict()
    assert r['market_state']=='資料不足' and r['today_action']=='不交易'

def test_intraday_is_not_formal():
    r=analyze_security(synthetic_demo_history('bull_breakout',180),SEC,formal_close=False).to_dict()
    assert r['data_status']=='盤中暫估'

def test_position_size_cap():
    r=position_size(1_000_000,100,95,.01,.2)
    assert r['shares']==2000

def test_database_and_backup(tmp_path:Path):
    db=Database(tmp_path/'test.db');db.upsert_securities([{'code':'2330','name':'台積電','exchange':'TWSE','asset_type':'STOCK','close':1000}]);db.add_watch('2330');db.add_trade({'trade_date':'2026-07-01','code':'2330','side':'BUY','quantity':100,'price':900,'fee':0,'tax':0});payload=db.export_user_data();assert payload['watchlist'][0]['code']=='2330';assert db.get_position('2330')['quantity']==100

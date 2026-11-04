"""Authenticated Sniper-style UI and verified news-only paper runtime.

Direct signal API routes remain at /api/v1/signals/{incoming,latest,status}.
All broker order routes are intentionally absent from this application.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from bridge.app import create_app as create_bridge_app
from desk.engine import NewsPaperEngine, PaperLedger

IST=ZoneInfo("Asia/Kolkata")
STATIC=Path(__file__).resolve().parent/"static"
COOKIE="news_paper_session"


def create_desk_app(*, database_url=None, bearer_token=None, dashboard_password=None,
                    session_secret=None, ledger=None, clock=None, data_client=None,
                    start_engine=True):
    password=dashboard_password if dashboard_password is not None else os.environ.get("DASHBOARD_PASSWORD","")
    secret=session_secret if session_secret is not None else os.environ.get("DASHBOARD_SESSION_SECRET","")
    if not password or len(secret)<32:
        raise RuntimeError("DASHBOARD_PASSWORD and 32+ character DASHBOARD_SESSION_SECRET are required")
    bridge=create_bridge_app(database_url=database_url,bearer_token=bearer_token,
                            now_provider=clock)
    paper=NewsPaperEngine(
        bridge.state.engine,
        ledger=ledger,
        data_client=data_client,
        clock=clock if clock is not None else __import__("desk.engine",fromlist=["now_ist"]).now_ist,
        capital=float(os.getenv("DESK_STARTING_CAPITAL_INR","1000000")),
        per_stock=float(os.getenv("DESK_CAPITAL_PER_STOCK_INR","100000")),
        stop_pct=float(os.getenv("DESK_STOP_LOSS_PCT","2")),
        entry_cutoff=os.getenv("DESK_ENTRY_CUTOFF_IST","09:20"),
        exit_at=os.getenv("DESK_EXIT_TIME_IST","15:25")
    )
    bridge.state.news_engine=paper
    bridge.title="News Signals · Sniper Paper Desk"
    bridge.mount("/static",StaticFiles(directory=STATIC),name="static")

    def cookie_value():
        return hmac.new(secret.encode(),"sniper-news-paper-desk".encode(),hashlib.sha256).hexdigest()

    def authed_cookie(raw):
        return hmac.compare_digest(str(raw or ""),cookie_value())

    def authed(request:Request):
        return authed_cookie(request.cookies.get(COOKIE))

    def require(request:Request):
        if not authed(request):
            raise HTTPException(status_code=401,detail="Dashboard login required")

    @bridge.on_event("startup")
    async def start():
        if start_engine:paper.start()

    @bridge.on_event("shutdown")
    async def stop():
        if start_engine:paper.stop()
        bridge.state.engine.dispose()

    @bridge.get("/health")
    async def health():
        return {"status":"up","paper_only":True,"execution_enabled":False,
                "signal_status":paper.snapshot()["signal_status"]}

    @bridge.get("/ready")
    async def ready():
        s=paper.snapshot()
        if not s["strategy"]["runtime_ready"]:
            raise HTTPException(status_code=503,detail={"signal_status":s["signal_status"],
                                "dhan_auth":s["dhan_auth"]["state"],
                                "error":s["engine"]["error"]})
        return {"status":"ready","paper_only":True,"execution_enabled":False}

    @bridge.get("/login")
    async def login_page(request:Request):
        if authed(request):return RedirectResponse("/",status_code=303)
        return FileResponse(STATIC/"login.html")

    @bridge.post("/api/auth/login")
    async def login(payload:dict,response:Response):
        if not hmac.compare_digest(str(payload.get("password","")).encode(),password.encode()):
            raise HTTPException(status_code=401,detail="Incorrect credentials")
        response.set_cookie(COOKIE,cookie_value(),httponly=True,samesite="strict",
                            secure=os.getenv("DASHBOARD_COOKIE_SECURE","true").lower()=="true",
                            max_age=24*3600,path="/")
        return {"status":"ok"}

    @bridge.post("/api/auth/logout")
    async def logout(response:Response):
        response.delete_cookie(COOKIE,path="/")
        return {"status":"ok"}

    @bridge.get("/")
    async def home(request:Request):
        if not authed(request):return RedirectResponse("/login",status_code=303)
        return FileResponse(STATIC/"index.html")

    @bridge.get("/api/state")
    async def state(request:Request):
        require(request)
        return paper.snapshot()

    @bridge.get("/api/portfolio/config")
    async def portfolio_config(request:Request):
        require(request)
        snap=paper.snapshot()
        return {"portfolio":snap["strategy"],"runtime_ready":snap["strategy"]["runtime_ready"],
                "paper_only":True}

    @bridge.get("/api/news/signals")
    async def news_signals(request:Request):
        require(request)
        snap=paper.snapshot()
        return {"status":snap["signal_status"],"session_date":snap["server_time"][:10],
                "news_cutoff_at":snap["signal_cutoff"],
                "generated_at":snap["signal_generated_at"],
                "signals":[{"symbol":row["symbol"],
                            "side":"LONG" if row["signal"]=="BUY" else "SHORT",
                            "rank":row["rank"],"news_summary":row["news_summary"],
                            "reason":row["signal_note"],"sources":row["sources"]}
                           for row in snap["symbols"]],
                "execution_enabled":False}

    @bridge.get("/api/trades")
    async def trades(request:Request,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200),
                     symbol:str|None=None,side:str|None=None,outcome:str|None=None,
                     start:str|None=None,end:str|None=None):
        require(request)
        rows=[x for x in paper.all_trades() if x["status"]=="CLOSED"]
        if symbol:rows=[x for x in rows if x["symbol"]==symbol]
        if side in ("LONG","SHORT"):rows=[x for x in rows if x["side"]==side]
        if outcome=="WIN":rows=[x for x in rows if (x["net_pnl"] or 0)>0]
        if outcome=="LOSS":rows=[x for x in rows if (x["net_pnl"] or 0)<0]
        if start:rows=[x for x in rows if x["exit_date"]>=start]
        if end:rows=[x for x in rows if x["exit_date"]<=end]
        return {"trades":rows[offset:offset+limit],"total":len(rows),
                "offset":offset,"limit":limit}

    @bridge.post("/api/paper/toggle")
    async def paper_toggle(request:Request):
        require(request)
        try:return {"paper_enabled":paper.toggle_entries()}
        except RuntimeError as exc:
            raise HTTPException(status_code=409,detail=str(exc)) from exc

    @bridge.websocket("/ws")
    async def websocket_state(websocket:WebSocket):
        if not authed_cookie(websocket.cookies.get(COOKIE)):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(paper.snapshot())
                await asyncio.sleep(2)
        except (WebSocketDisconnect,RuntimeError):
            return

    return bridge


def run():
    import uvicorn
    uvicorn.run(create_desk_app(),host=os.getenv("DESK_HOST","127.0.0.1"),
                port=int(os.getenv("DESK_PORT","8004")))


if __name__=="__main__":
    run()

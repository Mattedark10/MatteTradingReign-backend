import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
API_KEYS = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]
REST = f"{SUPABASE_URL}/rest/v1"
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not (SUPABASE_URL and SUPABASE_KEY and API_KEYS):
        print("ATTENZIONE: imposta SUPABASE_URL, SUPABASE_SERVICE_KEY e API_KEYS")
    app.state.http = httpx.AsyncClient(timeout=15, headers=HEADERS)
    yield
    await app.state.http.aclose()


app = FastAPI(title="MatteTradingReign", version="1.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def require_key(authorization: Optional[str] = Header(default=None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token or not any(hmac.compare_digest(token, k) for k in API_KEYS):
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})


def platform_of(p: Optional[str]) -> str:
    return "console" if p == "console" else "pc"


def iso(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def to_deal(r: dict) -> dict:
    created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
    return {
        "id": str(r["id"]), "definitionId": r["definition_id"], "name": r["name"],
        "rating": r["rating"], "version": r["version"], "platform": r["platform"],
        "buyNow": r["buy_now"], "marketPrice": r["market_price"], "avg4h": r["avg4h"],
        "avg23h": r["avg23h"], "lastSold": r["last_sold"], "nextUp": r["next_up"],
        "autoBuy": r["auto_buy"], "source": r["source"],
        "createdAt": int(created.timestamp() * 1000),
    }


@app.get("/")
def home():
    return {"name": "MatteTradingReign", "status": "online", "version": "1.1.0"}


@app.get("/health")
def health():
    return {"ok": True, "service": "MatteTradingReign"}


@app.get("/version")
def version():
    return {"version": "1.1.0"}


@app.get("/deals", dependencies=[Depends(require_key)])
async def get_deals(
    request: Request,
    platform: str = "pc",
    since: Optional[float] = None,
    wait: int = Query(default=0, ge=0),
):
    http: httpx.AsyncClient = request.app.state.http
    since_ms = since if since else (datetime.now(timezone.utc).timestamp() * 1000 - 60_000)
    deadline = asyncio.get_event_loop().time() + min(wait, 20)
    while not await request.is_disconnected():
        r = await http.get(f"{REST}/deals", params={
            "select": "*", "platform": f"eq.{platform_of(platform)}",
            "created_at": f"gt.{iso(since_ms)}", "order": "created_at.asc", "limit": "50",
        })
        if r.status_code >= 400:
            raise HTTPException(status_code=500, detail={"error": "db_error"})
        rows = r.json()
        if rows or asyncio.get_event_loop().time() >= deadline:
            deals = [to_deal(x) for x in rows]
            cursor = deals[-1]["createdAt"] if deals else since_ms
            return {"deals": deals, "count": len(deals), "cursor": cursor, "live": True}
        await asyncio.sleep(1.5)
    return {"deals": [], "count": 0}


class DealIn(BaseModel):
    definitionId: int
    buyNow: int
    platform: str = "pc"
    name: Optional[str] = None
    rating: Optional[int] = None
    version: Optional[str] = None
    marketPrice: Optional[int] = None
    avg4h: Optional[int] = None
    avg23h: Optional[int] = None
    lastSold: Optional[int] = None
    nextUp: Optional[int] = None
    autoBuy: bool = True
    source: Optional[str] = "manual"


@app.post("/deals", dependencies=[Depends(require_key)])
async def add_deal(d: DealIn, request: Request):
    row = {
        "platform": platform_of(d.platform), "definition_id": d.definitionId, "name": d.name,
        "rating": d.rating, "version": d.version, "buy_now": d.buyNow, "market_price": d.marketPrice,
        "avg4h": d.avg4h, "avg23h": d.avg23h, "last_sold": d.lastSold, "next_up": d.nextUp,
        "auto_buy": d.autoBuy, "source": d.source,
    }
    r = await request.app.state.http.post(f"{REST}/deals", json=row, headers={"Prefer": "return=representation"})
    if r.status_code >= 400:
        raise HTTPException(status_code=500, detail={"error": "db_error"})
    return {"ok": True, "id": r.json()[0]["id"]}


class ScanFound(BaseModel):
    platform: str = "pc"
    definitionId: int
    price: int


@app.post("/scan/found", dependencies=[Depends(require_key)])
async def scan_found(b: ScanFound, request: Request):
    await request.app.state.http.post(f"{REST}/scan_found", json={
        "platform": platform_of(b.platform), "definition_id": b.definitionId, "price": b.price})
    return {"ok": True}


@app.get("/scan/list", dependencies=[Depends(require_key)])
async def scan_list(request: Request, platform: str = "pc", max: int = 30):
    r = await request.app.state.http.get(f"{REST}/watch_cards", params={
        "select": "*", "platform": f"eq.{platform_of(platform)}", "limit": str(min(max, 60))})
    if r.status_code >= 400:
        raise HTTPException(status_code=500, detail={"error": "db_error"})
    return {"cards": [{"id": c["definition_id"], "definitionId": c["definition_id"], "name": c["name"],
                       "rating": c["rating"], "version": c["version"], "maxPrice": c["max_price"]}
                      for c in r.json()]}


@app.get("/scan/browse", dependencies=[Depends(require_key)])
def scan_browse():
    return {"cards": [], "total": 0}


class Event(BaseModel):
    kind: str = Field(default="extension_event", max_length=100)
    data: dict = Field(default_factory=dict)
    id: Optional[str] = None


@app.post("/events", dependencies=[Depends(require_key)])
async def receive_event(e: Event, request: Request):
    await request.app.state.http.post(f"{REST}/events", json={"event_type": e.kind, "payload": e.data})
    return {"ok": True}


@app.get("/events", dependencies=[Depends(require_key)])
async def list_events(request: Request):
    r = await request.app.state.http.get(f"{REST}/events", params={
        "select": "*", "order": "id.desc", "limit": "50"})
    return {"events": r.json() if r.status_code < 400 else []}


@app.get("/leaderboard", dependencies=[Depends(require_key)])
def leaderboard():
    return {"entries": []}


@app.post("/presets", dependencies=[Depends(require_key)])
def presets():
    raise HTTPException(status_code=501, detail={"error": "not_supported"})

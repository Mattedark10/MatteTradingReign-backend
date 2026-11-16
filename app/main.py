import os
import sqlite3
import json
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="MatteTradingReign",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.getenv("DB_PATH", "/tmp/matte_trading_reign.db")


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        """)


@app.on_event("startup")
def startup():
    init_db()


class Event(BaseModel):
    type: str = Field(default="extension_event", max_length=100)
    payload: dict = Field(default_factory=dict)


@app.get("/")
def home():
    return {
        "name": "MatteTradingReign",
        "status": "online",
        "version": "1.0.0"
    }


@app.get("/health")
def health():
    return {"ok": True, "service": "MatteTradingReign"}


@app.get("/version")
def version():
    return {"version": "1.0.0"}


@app.get("/config")
def config():
    return {
        "name": "MatteTradingReign",
        "discord": False,
        "deals_feed": False
    }


@app.get("/deals")
def deals():
    return {
        "deals": [],
        "count": 0,
        "available": False,
        "message": "Feed offerte non ancora configurato."
    }


@app.post("/events")
def receive_event(event: Event):
    now = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as db:
        cursor = db.execute(
            """INSERT INTO events
            (created_at, event_type, payload)
            VALUES (?, ?, ?)""",
            (now, event.type, json.dumps(event.payload))
        )

    return {"ok": True, "id": cursor.lastrowid}


@app.get("/events")
def get_events():
    with sqlite3.connect(DB_PATH) as db:
        rows = db.execute(
            """SELECT id, created_at, event_type, payload
            FROM events ORDER BY id DESC LIMIT 50"""
        ).fetchall()

    return {
        "events": [
            {
                "id": row[0],
                "created_at": row[1],
                "type": row[2],
                "payload": json.loads(row[3])
            }
            for row in rows
        ]
    }

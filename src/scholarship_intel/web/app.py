"""Scholarship Intelligence dashboard."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from scholarship_intel.store import db as store

ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"

app = FastAPI(title="Scholarship Intelligence", version="1.0.0")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _db():
    path = os.environ.get("SCHOLARSHIP_DB") or str(ROOT / "data" / "scholarships.db")
    return store.connect(path)


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    q: str | None = None,
    status: str | None = None,
    label: str | None = None,
):
    conn = _db()
    stats = store.dashboard_stats(conn)
    rows = store.list_scholarships(conn, q=q, status=status, label=label)
    conn.close()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "stats": stats,
            "rows": rows,
            "q": q or "",
            "status": status or "",
            "label": label or "",
        },
    )


@app.get("/scholarship/{sid}", response_class=HTMLResponse)
def detail(request: Request, sid: int):
    conn = _db()
    row = store.get_scholarship(conn, sid)
    if not row:
        conn.close()
        return RedirectResponse("/")
    changes = store.get_changes(conn, sid)
    conf = {}
    if row.get("confidence_json"):
        try:
            conf = json.loads(row["confidence_json"])
        except json.JSONDecodeError:
            conf = {}
    evidence = {}
    if row.get("evidence_json"):
        try:
            evidence = json.loads(row["evidence_json"])
        except json.JSONDecodeError:
            evidence = {}
    conn.close()
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "s": row,
            "changes": changes,
            "conf": conf,
            "evidence": evidence,
        },
    )


@app.get("/api/stats")
def api_stats():
    conn = _db()
    s = store.dashboard_stats(conn)
    conn.close()
    return s

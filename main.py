import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()

TOKEN = os.environ["X_TOKEN"]
API_BASE = os.environ.get("API_BASE", "https://prask.ksp.sk/")
PUBLIC_TASK_URL = os.environ.get("PUBLIC_TASK_URL", API_BASE)
DATA_FILE = Path("data/submissions.json")
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET"],
)
templates = Jinja2Templates(directory="templates")

HEADERS = {"X-Token": TOKEN, "Content-Type": "application/json"}


def load_submissions():
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE) as f:
        return json.load(f)


def save_submission(entry):
    data = load_submissions()
    data.append(entry)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, token: str | None = None):
    if token:
        async with httpx.AsyncClient() as client:
            print("Posting to ",token)
            r = await client.post(
                f"{API_BASE}/api/external-submit/exchange/{token}/",
                headers=HEADERS,
                timeout=10,
            )

        if r.status_code != 200:
            return HTMLResponse(f"Token exchange failed: {r.request.headers} {r.request.extensions} {r.request.url} {r.content}", status_code=400)

        data = r.json()
        request.session["user_id"] = data["user"]["id"]
        request.session["user_name"] = data["user"]["name"]
        request.session["max_points"] = data["problem"]["points"]
        request.session["problem_set_start"] = data["problem"]["problem_set"]["start"]
        request.session["problem_set_end"] = data["problem"]["problem_set"]["end"]
        return RedirectResponse(url="/")

    user_id = request.session.get("user_id")
    user_name = request.session.get("user_name")
    if not user_id:
        return HTMLResponse(
            "<!DOCTYPE html>"
            '<html lang="sk">'
            '<head><meta charset="UTF-8"><title>Interaktívka</title>'
            "<style>"
            "body{font-family:sans-serif;max-width:480px;margin:4rem auto;padding:0 1rem;text-align:center;line-height:1.6}"
            "a{color:#06b}"
            "</style>"
            "</head>"
            "<body>"
            "<h2>Vitaj v interaktívke</h2>"
            f'<p>Pre prihlásenie prejdi na <a href="{PUBLIC_TASK_URL}">{PUBLIC_TASK_URL}</a> a klikni na tlačidlo "Spustiť interaktívku".</p>'
            "</body></html>",
            status_code=200,
        )

    if "session_started_at" not in request.session:
        request.session["session_started_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
    if "attempt_count" not in request.session:
        request.session["attempt_count"] = 0

    submits = []
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{API_BASE}/api/external-submit/submits/",
            headers={**HEADERS, "X-User-Id": str(user_id)},
            timeout=10,
        )
        if r.status_code == 200:
            submits = r.json()

    return templates.TemplateResponse(
        request,
        "form.html",
        {
            "user_id": user_id,
            "user_name": user_name,
            "max_points": request.session.get("max_points"),
            "problem_set_start": request.session.get("problem_set_start"),
            "problem_set_end": request.session.get("problem_set_end"),
            "attempt_count": request.session["attempt_count"],
            "session_started_at": request.session["session_started_at"],
            "submits": submits,
        },
    )


@app.post("/submit")
async def submit(
        request: Request,
        score: float = Form(...),
):
    user_id = request.session.get("user_id")
    if not user_id:
        return HTMLResponse("Unauthorized.", status_code=403)

    attempt_count = request.session.get("attempt_count", 0)
    request.session["attempt_count"] = attempt_count + 1

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{API_BASE}/api/external-submit/submits/",
            headers={**HEADERS, "X-User-Id": str(user_id)},
            json={
                "score": score,
                "external_data": {
                    "attempt": attempt_count + 1,
                    "session_started_at": request.session.get("session_started_at"),
                },
            },
            timeout=10,
        )

    if r.status_code not in (200, 201):
        return HTMLResponse(f"Submit failed: {r.text}", status_code=400)

    api_data = r.json()

    entry = {
        "api_id": api_data["id"],
        "user_id": user_id,
        "score": api_data["score"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_submission(entry)

    return templates.TemplateResponse(
        request,
        "result.html",
        {"entry": entry},
    )


@app.get("/data")
async def view_data():
    return load_submissions()

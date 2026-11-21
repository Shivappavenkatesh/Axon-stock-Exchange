"""Web dashboard and API (finding 3).

- Every page and every /api route requires login. Only /login and /healthz are open.
- Listens on 127.0.0.1 by default: reach it through an SSH tunnel or VPN, never an open port.
- Session cookies are HttpOnly and SameSite=Strict; set AXON_WEB_HTTPS=true behind HTTPS.
- State-changing API calls must be JSON with the X-Axon-Request header (blocks cross-site forms).
- Switching a part to LIVE needs the login plus the typed confirmation "LIVE <part>".
- Five failed logins lock the login for 15 minutes.
- There is no manual order endpoint: orders only come from the engine.
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from axon.clock import now_ist
from axon.context import Axon
from axon.evaluation import pass_test
from axon.models import Mode, Part
from axon.modes import ModeChangeRefused, change_mode, live_confirmation_text
from axon.risk import RiskEngine

MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60


class WebConfigError(Exception):
    pass


def create_app(axon: Axon, *, username: str | None = None, password_hash: str | None = None,
               secret_key: str | None = None, https: bool | None = None, clock=now_ist) -> Flask:
    username = username or os.getenv("AXON_WEB_USERNAME", "")
    password_hash = password_hash or os.getenv("AXON_WEB_PASSWORD_HASH", "")
    if not password_hash and os.getenv("AXON_WEB_PASSWORD"):
        password_hash = generate_password_hash(os.environ["AXON_WEB_PASSWORD"])
    if not username or not password_hash:
        raise WebConfigError("Set AXON_WEB_USERNAME and AXON_WEB_PASSWORD_HASH (or AXON_WEB_PASSWORD) first.")
    if https is None:
        https = os.getenv("AXON_WEB_HTTPS", "false").lower() in {"1", "true", "yes"}

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=secret_key or os.getenv("AXON_WEB_SECRET_KEY") or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=https,
        PERMANENT_SESSION_LIFETIME=8 * 3600,
    )
    failures = {"count": 0, "locked_until": 0.0}
    risk = RiskEngine(axon.settings, axon.ledger)

    def login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("user"):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "login required"}), 401
                return redirect(url_for("login"))
            if request.method in {"POST", "PUT", "DELETE"} and request.headers.get("X-Axon-Request") != "1":
                return jsonify({"error": "missing X-Axon-Request header"}), 403
            return view(*args, **kwargs)
        return wrapper

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
        return resp

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True})

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            if time.time() < failures["locked_until"]:
                error = "Too many failed attempts. Try again later."
            elif secrets.compare_digest(request.form.get("username", ""), username) and \
                    check_password_hash(password_hash, request.form.get("password", "")):
                session.clear()
                session["user"] = username
                session.permanent = True
                failures["count"] = 0
                return redirect(url_for("index"))
            else:
                failures["count"] += 1
                if failures["count"] >= MAX_FAILURES:
                    failures["locked_until"] = time.time() + LOCKOUT_SECONDS
                    failures["count"] = 0
                error = "Wrong username or password."
        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def index():
        return render_template("dashboard.html", parts=[p.value for p in Part])

    def _status() -> dict:
        ledger = axon.ledger
        books = sorted({m.book for m in ledger.modes().values() if m is not Mode.OFF} | {"paper"})
        return {
            "now": clock().isoformat(),
            "modes": {p.value: m.value for p, m in ledger.modes().items()},
            "kill_switch": bool(ledger.kill_switch().get("active")),
            "books": {
                b: {"value": round(ledger.nav(b), 2), "value_per_unit": round(ledger.nav_per_unit(b), 4),
                    "brakes": risk.current_brakes(b).describe(), "locked": risk.current_brakes(b).locked}
                for b in books
            },
            "pass_tests": {p.value: pass_test(ledger, p).__dict__ | {"part": p.value}
                           for p in (Part.INTRADAY, Part.SWING)},
            "last_cycle": str(ledger.last_beat("cycle") or ""),
        }

    @app.get("/api/status")
    @login_required
    def api_status():
        return jsonify(_status())

    @app.get("/api/positions")
    @login_required
    def api_positions():
        return jsonify([{**p.__dict__, "part": p.part.value, "entry_ts": p.entry_ts.isoformat()}
                        for p in axon.ledger.open_positions()])

    @app.get("/api/orders")
    @login_required
    def api_orders():
        return jsonify(axon.ledger.orders()[-200:])

    @app.get("/api/alerts")
    @login_required
    def api_alerts():
        return jsonify(axon.ledger.alerts(50))

    @app.post("/api/mode")
    @login_required
    def api_mode():
        body = request.get_json(silent=True) or {}
        try:
            part = Part(body.get("part", ""))
            mode = Mode(body.get("mode", ""))
        except ValueError:
            return jsonify({"error": "unknown part or mode"}), 400
        try:
            old = change_mode(ledger=axon.ledger, alerter=axon.alerter, settings=axon.settings, part=part,
                              new_mode=mode, actor=session["user"], now=clock(), confirm=body.get("confirm", ""))
        except ModeChangeRefused as exc:
            return jsonify({"error": str(exc), "confirm_text": live_confirmation_text(part)}), 409
        return jsonify({"part": part.value, "old": old.value, "new": mode.value})

    @app.post("/api/kill-switch")
    @login_required
    def api_kill_switch():
        body = request.get_json(silent=True) or {}
        active = bool(body.get("active"))
        now = clock()
        axon.ledger.set_kill_switch(active, now, session["user"], body.get("note", ""))
        axon.alerter.send(f"Kill switch {'ON' if active else 'OFF'} (by {session['user']})", now)
        return jsonify({"active": active})

    @app.post("/api/brakes/unlock")
    @login_required
    def api_unlock():
        body = request.get_json(silent=True) or {}
        book = body.get("book", "")
        if body.get("confirm", "") != f"UNLOCK {book}":
            return jsonify({"error": f"type 'UNLOCK {book}' to confirm the review is done"}), 409
        now = clock()
        axon.ledger.unlock_brakes(book, now, session["user"])
        axon.alerter.send(f"Brakes unlocked for {book} by {session['user']} after review", now)
        return jsonify({"book": book, "unlocked": True})

    return app


def main() -> None:
    from axon.context import build

    app = create_app(build())
    host = os.getenv("AXON_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("AXON_WEB_PORT", "8080"))
    app.run(host=host, port=port, debug=False)

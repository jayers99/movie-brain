from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

from flask import Flask, Response, jsonify, render_template, request

from movie_brain.application.ratings import rate_film
from movie_brain.application.sync import SOURCE
from movie_brain.domain.audit import VERDICTS
from movie_brain.domain.filters import CHIPS, thresholds
from movie_brain.infrastructure.database import Repository


def create_app(repo: Repository, today: Callable[[], date] = date.today) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/films")
    def list_films() -> Response:
        return jsonify([v.to_dict() for v in repo.list_views(SOURCE, today())])

    @app.get("/api/films/<int:film_id>")
    def film_detail(film_id: int) -> tuple[Response, int]:
        view = repo.get_view(film_id, today())
        if view is None:
            return jsonify({"error": "not found"}), 404
        raw = repo.get_payload(film_id)
        payload: object = None
        if raw is not None:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"_raw": raw}
        return jsonify({**view.to_dict(), "payload": payload}), 200

    @app.post("/api/films/<int:film_id>/watchlist")
    def toggle_watchlist(film_id: int) -> tuple[Response, int]:
        watchlisted = repo.toggle_watchlist(film_id, today())
        if watchlisted is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({"watchlisted": watchlisted}), 200

    @app.post("/api/films/<int:film_id>/revisit")
    def toggle_revisit(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        note = body.get("note") if isinstance(body, dict) and isinstance(body.get("note"), str) else None
        flagged = repo.toggle_revisit(film_id, today(), note=note or None)
        if flagged is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({"needs_revisit": flagged}), 200

    @app.put("/api/films/<int:film_id>/revisit")
    def put_revisit_note(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "note" not in body or not isinstance(body["note"], (str, type(None))):
            return jsonify({"error": 'body must be JSON {"note": str | null}'}), 400
        if not repo.set_revisit_note(film_id, body["note"] or None):
            return jsonify({"error": "not flagged"}), 404
        return jsonify({"ok": True}), 200

    @app.post("/api/films/<int:film_id>/verdict")
    def post_verdict(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get("verdict") not in VERDICTS:
            msg = f"body must be JSON {{\"verdict\": one of {', '.join(VERDICTS)}, \"note\"?: str}}"
            return jsonify({"error": msg}), 400
        note = body.get("note")
        if note is not None and not isinstance(note, str):
            return jsonify({"error": "note must be a string"}), 400
        reasons = repo.current_reasons(film_id)
        result = repo.add_verdict(film_id, body["verdict"], reasons, note or None, today())
        if result is None:
            return jsonify({"error": "not found"}), 404
        view = repo.get_view(film_id, today())
        # result["reasons"] is a comma-joined sorted string (audit_verdict storage format),
        # asymmetric with view.audit["reasons"] which is a list of {code, detail} dicts.
        return jsonify({**result, "audit": view.audit if view else None}), 200

    @app.put("/api/films/<int:film_id>/rating")
    def put_rating(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "score" not in body:
            return jsonify({"error": 'body must be JSON {"score": 0-10 | null}'}), 400
        score = body["score"]
        if score is not None and not isinstance(score, int):
            return jsonify({"error": "score must be an integer 0–10"}), 400
        try:
            view = rate_film(repo, film_id, score, today())
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except LookupError:
            return jsonify({"error": "not found"}), 404
        return jsonify(view.to_dict()), 200

    @app.get("/api/summary")
    def summary() -> Response:
        return jsonify(repo.summary(SOURCE))

    @app.get("/api/config")
    def config() -> Response:
        return jsonify({"canned_thresholds": thresholds(), "chips": list(CHIPS), "today": today().isoformat()})

    return app

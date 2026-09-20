from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from movie_brain.application import rank as ranker
from movie_brain.application.rank import RankError
from movie_brain.application.ratings import rate_film
from movie_brain.application.search import run_search
from movie_brain.application.sync import SOURCE
from movie_brain.application.wishlist import (
    NotForSale,
    WishlistError,
    WishlistGateway,
    unwishlist_film,
    wishlist_film,
)
from movie_brain.domain.audit import VERDICTS
from movie_brain.domain.filters import CHIPS, thresholds
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.embeddings import Embedder, VectorIndex
from movie_brain.infrastructure.listfile import LISTS_DIR


def _json_object() -> dict[str, object]:
    """The request body as a JSON object, or a 400 RankError — the shape check every rank route shares."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise RankError(400, "body must be a JSON object")
    return body


def create_app(
    repo: Repository,
    today: Callable[[], date] = date.today,
    embedder: Embedder | None = None,
    lists_dir: Path = LISTS_DIR,
    wishlist: WishlistGateway | None = None,
) -> Flask:
    app = Flask(__name__)
    # Stage 4 of the bar (Plan C). The index is built lazily on the first semantic query and
    # refreshed when `film_embedding` changes; with no embedder the bar is exactly Phase 1.
    # Named `vector_index`, not `index`, to avoid shadowing the `/` route handler below (same
    # function scope; a closure over `index` would otherwise resolve to that view function).
    vector_index = VectorIndex(repo, embedder) if embedder is not None else None
    RANK_SOURCE = "owned"  # v1 (tier-ranker spec D7); read by the rank routes AND the film detail
    UNREACHABLE = "Couldn't reach CheapCharts."  # the brief's one failure line, whatever went wrong
    # One click at a time: a click is four or five paced calls to one account, and the dev
    # server is threaded.
    wishlist_lock = threading.Lock()

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
        ids = repo.external_ids_for(film_id)
        credits = repo.film_credits(film_id)
        return jsonify({
            **view.to_dict(),
            "payload": payload,
            # Detail-only (spec D10): credits and prose never ride on /api/films.
            "credits": credits.to_dict() if credits is not None else None,
            "overview": repo.overview_for(film_id),
            "tmdb_url": f"https://www.themoviedb.org/movie/{ids['tmdb']}" if "tmdb" in ids else None,
            # Detail-only too (move-tier spec M7): the drawer's tier row and its "Rank this"
            # awaiting state, derived per read from the open session; a READ, never a seed.
            **_rank_keys(film_id),
        }), 200

    def _rank_keys(film_id: int) -> dict[str, object]:
        status = ranker.rank_status(repo, RANK_SOURCE, film_id)
        return {"rank_tier": status["tier"], "rank_how": status["how"], "awaiting_order": status["awaiting_order"]}

    @app.post("/api/films/<int:film_id>/watchlist")
    def toggle_watchlist(film_id: int) -> tuple[Response, int]:
        watchlisted = repo.toggle_watchlist(film_id, today())
        if watchlisted is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({"watchlisted": watchlisted}), 200

    @app.post("/api/films/<int:film_id>/wishlist")
    def post_wishlist(film_id: int) -> tuple[Response, int]:
        if wishlist is None:  # no credentials file: the same line as any other failure
            return jsonify({"error": UNREACHABLE}), 502
        try:
            with wishlist_lock:
                wishlist_film(repo, wishlist, film_id, today())
        except LookupError:
            return jsonify({"error": "not found"}), 404
        except NotForSale:
            return jsonify({"error": "not for sale"}), 409
        except WishlistError as exc:
            # The screen says one thing whatever happened; the terminal names the reason, which
            # is OUR wording by construction — never the API's text, a token, an email or a price.
            app.logger.warning("wishlist click failed: %s", exc)
            return jsonify({"error": UNREACHABLE}), 502
        return jsonify({"wishlisted": True}), 200

    @app.delete("/api/films/<int:film_id>/wishlist")
    def delete_wishlist(film_id: int) -> tuple[Response, int]:
        if wishlist is None:
            return jsonify({"error": UNREACHABLE}), 502
        try:
            with wishlist_lock:
                unwishlist_film(repo, wishlist, film_id, today())
        except LookupError:
            return jsonify({"error": "not found"}), 404
        except WishlistError as exc:
            app.logger.warning("wishlist click failed: %s", exc)
            return jsonify({"error": UNREACHABLE}), 502
        return jsonify({"wishlisted": False}), 200

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

    @app.get("/api/search")
    def search() -> tuple[Response, int]:
        q = (request.args.get("q") or "").strip()
        if not q:
            return jsonify({"error": "q is required"}), 400
        result = run_search(repo, q, index=vector_index)
        return jsonify({"q": q, **result.to_dict()}), 200

    @app.errorhandler(RankError)
    def rank_error(exc: RankError) -> tuple[Response, int]:
        return jsonify({"error": exc.message}), exc.status

    @app.get("/rank")
    def rank_page() -> str:
        return render_template("rank.html")

    @app.get("/api/rank/proposal")
    def rank_proposal() -> Response:
        return jsonify(ranker.proposal(repo, RANK_SOURCE))

    @app.get("/api/rank/session")
    def rank_session() -> Response:
        return jsonify(ranker.session_state(repo, RANK_SOURCE, today()))

    @app.post("/api/rank/session")
    def rank_start() -> tuple[Response, int]:
        body = _json_object()
        anchors = body.get("anchors")
        if not isinstance(anchors, dict):
            raise RankError(400, 'body must be JSON {"anchors": {"1": film_id, …, "5": film_id}}')
        try:
            parsed = {int(k): int(v) for k, v in anchors.items()}
        except (TypeError, ValueError):
            raise RankError(400, "anchors must map tier → film_id") from None
        sid = ranker.start_session(repo, RANK_SOURCE, parsed, today())
        return jsonify({"session_id": sid, **ranker.session_state(repo, RANK_SOURCE, today())}), 201

    @app.post("/api/rank/verdict")
    def rank_verdict() -> Response:
        body = _json_object()
        film_id, anchor_tier = body.get("film_id"), body.get("anchor_tier")
        if not isinstance(film_id, int) or not isinstance(anchor_tier, int):
            raise RankError(400, 'body must be JSON {"film_id": int, "anchor_tier": int, "verdict": "better"|"worse"}')
        return jsonify(
            ranker.record_verdict(repo, RANK_SOURCE, film_id, anchor_tier, str(body.get("verdict")), today())
        )

    @app.post("/api/rank/pass")
    def rank_pass() -> Response:
        body = _json_object()
        film_id = body.get("film_id")
        if not isinstance(film_id, int):
            raise RankError(400, 'body must be JSON {"film_id": int, "candidate_unseen": bool, "anchor_unseen": bool}')
        candidate_unseen = bool(body.get("candidate_unseen"))
        anchor_unseen = bool(body.get("anchor_unseen"))
        return jsonify(ranker.pass_film(repo, RANK_SOURCE, film_id, candidate_unseen, anchor_unseen, today()))

    @app.post("/api/rank/undo")
    def rank_undo() -> Response:
        return jsonify(ranker.undo(repo, RANK_SOURCE, today()))

    @app.put("/api/rank/anchor")
    def rank_anchor() -> Response:
        body = _json_object()
        tier, film_id = body.get("tier"), body.get("film_id")
        if not isinstance(tier, int) or not isinstance(film_id, int):
            raise RankError(400, 'body must be JSON {"tier": int, "film_id": int}')
        return jsonify(ranker.swap_anchor(repo, RANK_SOURCE, tier, film_id, today()))

    @app.post("/api/rank/move")
    def rank_move() -> Response:
        body = _json_object()
        film_id, tier = body.get("film_id"), body.get("tier")
        if not isinstance(film_id, int) or not isinstance(tier, int):
            raise RankError(400, 'body must be JSON {"film_id": int, "tier": int}')
        return jsonify(ranker.move_film(repo, RANK_SOURCE, film_id, tier, today()))

    @app.post("/api/rank/rerank")
    def rank_rerank() -> Response:
        body = _json_object()
        film_id = body.get("film_id")
        if not isinstance(film_id, int):
            raise RankError(400, 'body must be JSON {"film_id": int}')
        return jsonify(ranker.rerank_film(repo, RANK_SOURCE, film_id, today()))

    @app.post("/api/rank/save")
    def rank_save() -> Response:
        body = _json_object()
        raw_name = body.get("name")
        name = raw_name if isinstance(raw_name, str) else None
        return jsonify(ranker.save_list(repo, RANK_SOURCE, name, today(), lists_dir))

    @app.get("/api/rank/order")
    def rank_order_state() -> Response:
        raw_tier = request.args.get("tier")
        if raw_tier is None:
            raise RankError(400, "tier query parameter must be 1 to 5")
        try:
            tier = int(raw_tier)
        except ValueError:
            raise RankError(400, "tier query parameter must be 1 to 5") from None
        return jsonify(ranker.order_state(repo, RANK_SOURCE, tier, today()))

    @app.post("/api/rank/order/verdict")
    def rank_order_verdict() -> Response:
        body = _json_object()
        tier, film_id, other_film_id = body.get("tier"), body.get("film_id"), body.get("other_film_id")
        if not isinstance(tier, int) or not isinstance(film_id, int) or not isinstance(other_film_id, int):
            raise RankError(
                400,
                'body must be JSON {"tier": int, "film_id": int, "other_film_id": int, "verdict": "better"|"worse"}',
            )
        return jsonify(
            ranker.order_verdict(repo, RANK_SOURCE, tier, film_id, other_film_id, str(body.get("verdict")), today())
        )

    @app.post("/api/rank/order/pass")
    def rank_order_pass() -> Response:
        body = _json_object()
        tier, film_id = body.get("tier"), body.get("film_id")
        if not isinstance(tier, int) or not isinstance(film_id, int):
            raise RankError(400, 'body must be JSON {"tier": int, "film_id": int}')
        return jsonify(ranker.order_pass(repo, RANK_SOURCE, tier, film_id, today()))

    @app.put("/api/films/<int:film_id>/unseen")
    def put_unseen(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("unseen"), bool):
            return jsonify({"error": 'body must be JSON {"unseen": bool, "note"?: str}'}), 400
        note = body.get("note") if isinstance(body.get("note"), str) else None
        result = repo.set_unseen(film_id, body["unseen"], today(), note=note)
        if result is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({"unseen": result}), 200

    @app.put("/api/films/<int:film_id>/rank-mark")
    def put_rank_mark(film_id: int) -> tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("marked"), bool):
            return jsonify({"error": 'body must be JSON {"marked": bool}'}), 400
        result = repo.set_rank_mark(film_id, body["marked"], today())
        if result is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({"marked": result}), 200

    return app

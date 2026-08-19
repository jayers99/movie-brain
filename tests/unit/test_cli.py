import json

from typer.testing import CliRunner

from movie_brain.application.sync import SyncResult
from movie_brain.cli import app

runner = CliRunner()


def test_sync_flags_are_mutually_exclusive(config_dir):
    (config_dir / "omdb-api-key.txt").write_text("k")
    r = runner.invoke(app, ["sync", "--full", "--ratings-only"])
    assert r.exit_code == 2
    assert "mutually exclusive" in r.output


def test_sync_requires_api_key(config_dir):
    r = runner.invoke(app, ["sync"])
    assert r.exit_code == 2
    assert "OMDB_API_KEY" in r.output


def test_sync_propagates_exit_code(config_dir, monkeypatch):
    (config_dir / "omdb-api-key.txt").write_text("k")
    calls = {}

    def fake_sync(repo, api_key, today, **kw):
        calls.update(kw, api_key=api_key)
        return SyncResult(1, False, 0, 0, False, False)

    monkeypatch.setattr("movie_brain.cli.sync", fake_sync)
    r = runner.invoke(app, ["sync", "--full"])
    assert r.exit_code == 1
    assert calls["force_full"] is True and calls["ratings_only"] is False and calls["api_key"] == "k"


def test_import_legacy_and_status(config_dir, tmp_path):
    legacy = tmp_path / "legacy"
    (legacy / "payloads").mkdir(parents=True)
    (legacy / "catalog.json").write_text(
        json.dumps(
            {
                "films_fetched_at": "2026-08-10",
                "leaving": {},
                "films": [{"title": "Trio", "year": 1950, "director": "D", "url": "u"}],
            }
        )
    )
    r = runner.invoke(app, ["import-legacy", "--from", str(legacy)])
    assert r.exit_code == 0 and "films: 1" in r.output
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 0 and "1" in r.output


def test_export_csv(config_dir, tmp_path):
    out = tmp_path / "x.csv"
    r = runner.invoke(app, ["export", "csv", str(out)])
    assert r.exit_code == 0 and out.exists()

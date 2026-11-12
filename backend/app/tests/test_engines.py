import json
from pathlib import Path

import pytest

import app.db as db_mod
from app.engines.anomaly import evaluate_row_baseline
from app.engines.dependency import BLOCKED_BY_ANOMALY, dependency_readiness, topological_layers
from app.engines.job_runner import load_fixture, run_fixture_job
from app.repositories import jobs as jobs_repo
from app.repositories import orchestrations as orch_repo
from app.repositories import watermarks as wm_repo
from app.seed import init_db
from app.services import orchestrate_service


def test_ready_by_upstream_success():
    ok, _, _ = dependency_readiness(["a", "b"], {"a", "b"})
    assert ok
    ok, kind, reason = dependency_readiness(["a", "b"], {"a"})
    assert not ok
    assert kind == "upstream_not_success"
    assert "b" in reason


def test_dependency_anomaly_block_precedes_success():
    ok, kind, reason = dependency_readiness(["a"], {"a"}, {"a"})
    assert not ok
    assert kind == BLOCKED_BY_ANOMALY
    assert "a" in reason


def test_topological_layers():
    jobs = [
        {"name": "a", "depends_on": []},
        {"name": "b", "depends_on": []},
        {"name": "c", "depends_on": ["a", "b"]},
    ]
    layers = topological_layers(jobs)
    assert {j["name"] for j in layers[0]} == {"a", "b"}
    assert [j["name"] for j in layers[1]] == ["c"]


def test_run_fixture(tmp_path: Path):
    p = tmp_path / "x.json"
    p.write_text('{"watermark_ts":"2026-01-01T00:00:00Z","rows":[{"id":1}]}', encoding="utf-8")
    out = run_fixture_job(p)
    assert out["ok"] and out["artifact_rows"] == 1
    assert load_fixture(p)["watermark_ts"].startswith("2026")


@pytest.mark.parametrize(
    "rows,expected",
    [(2, None), (4, None), (3, None), (1, "below_min"), (6, "above_max")],
)
def test_evaluate_row_baseline(rows, expected):
    anomaly = evaluate_row_baseline(rows, 2, 4, "alert")
    if expected is None:
        assert anomaly is None
    else:
        assert anomaly is not None
        assert anomaly["direction"] == expected
        assert anomaly["baseline_min"] == 2
        assert anomaly["baseline_max"] == 4
        assert "outside baseline" in anomaly["reason"]


def test_evaluate_row_baseline_no_configured_interval():
    assert evaluate_row_baseline(999, None, None, "block") is None


def test_evaluate_row_baseline_defaults_to_alert():
    anomaly = evaluate_row_baseline(0, 2, 4, "nonsense")
    assert anomaly["policy"] == "alert"


# --------------------------- orchestration (SQLite) ---------------------------


@pytest.fixture()
def fresh_db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(orchestrate_service, "FIXTURES_DIR", Path(__file__).parents[1] / "fixtures")
    init_db()
    yield tmp_path
    db_mod.connect().close()


def _set_baseline(job_name: str, lo: int, hi: int, policy: str):
    conn = db_mod.connect()
    try:
        job = jobs_repo.get_job_by_name(conn, job_name)
        jobs_repo.update_baseline(conn, job["id"], lo, hi, policy)
        conn.commit()
    finally:
        conn.close()


def _attempts(orch_id: int):
    conn = db_mod.connect()
    try:
        return orch_repo.list_attempts(conn, orch_id)
    finally:
        conn.close()


def _watermarks() -> dict[str, dict]:
    conn = db_mod.connect()
    try:
        return {w["job_name"]: w for w in wm_repo.list_watermarks(conn)}
    finally:
        conn.close()


def test_normal_success_has_no_anomaly(fresh_db):
    res = orchestrate_service.run_orchestration()
    report = res["report"]
    assert res["status"] == "ok"
    assert report["succeeded"] == 3
    assert report["normal_success"] == 3
    assert report["anomaly_count"] == 0
    assert report["skipped_anomaly"] == 0
    attempts = _attempts(res["id"])
    assert report["attempt_count"] == len(attempts) == 3
    assert all(a["status"] == "success" and not a["is_anomaly"] for a in attempts)
    assert all(w["watermark_ts"] for w in _watermarks().values())


def test_alert_anomaly_advances_watermark_and_trusts_upstream(fresh_db):
    _set_baseline("ingest_orders", 5, 8, "alert")
    res = orchestrate_service.run_orchestration()
    report = res["report"]

    attempts = _attempts(res["id"])
    flagged = [a for a in attempts if a["is_anomaly"]]
    assert len(flagged) == 1
    a = flagged[0]
    assert a["job_name"] == "ingest_orders"
    assert a["status"] == "success"  # ran fine; anomaly carried as a flag
    assert a["anomaly_policy"] == "alert"
    assert a["consequence"] == "alerted_watermark_advanced"
    assert "outside baseline" in a["anomaly_reason"]
    assert a["detail"]["anomaly"]["observed_rows"] == 3

    # Downstream still ran, watermark advanced, report matches attempt rows.
    assert report["anomaly_count"] == 1
    assert report["anomaly_alert"] == 1
    assert report["anomaly_block"] == 0
    assert report["skipped_anomaly"] == 0
    assert report["succeeded"] == 3
    assert report["normal_success"] == 2
    assert report["attempt_count"] == len(attempts)
    assert _watermarks()["ingest_orders"]["watermark_ts"] == "2026-11-10T18:00:00Z"
    assert "fact_order_daily" in {x["job_name"] for x in attempts}


def test_block_anomaly_holds_watermark_and_skips_downstream(fresh_db):
    _set_baseline("dim_customer", 5, 8, "block")
    res = orchestrate_service.run_orchestration()
    report = res["report"]

    attempts = _attempts(res["id"])
    blocked = [a for a in attempts if a["is_anomaly"]][0]
    assert blocked["job_name"] == "dim_customer"
    assert blocked["anomaly_policy"] == "block"
    assert blocked["consequence"] == "watermark_held_downstream_blocked"

    skipped = [a for a in attempts if a["status"] == "skipped_anomaly"]
    assert [a["job_name"] for a in skipped] == ["fact_order_daily"]
    assert skipped[0]["consequence"] == "downstream_skipped"
    assert "dim_customer" in skipped[0]["detail"]["reason"]

    # Watermark held at its pre-run (empty) value; downstream produced nothing.
    assert _watermarks()["dim_customer"]["watermark_ts"] is None
    assert _watermarks()["fact_order_daily"]["watermark_ts"] is None
    assert res["status"] == "partial"

    assert report["anomaly_count"] == 1
    assert report["anomaly_block"] == 1
    assert report["anomaly_alert"] == 0
    assert report["skipped_anomaly"] == 1
    assert report["skipped_dep"] == 0
    assert report["skipped"] == 1
    # Two attempts ran to completion (ingest_orders normal, dim_customer
    # anomalous); only the normal one stays trustworthy.
    assert report["succeeded"] == 2
    assert report["normal_success"] == 1
    assert report["attempt_count"] == len(attempts) == 3


def test_attempt_filter_matches_report_counts(fresh_db):
    _set_baseline("ingest_orders", 5, 8, "alert")
    _set_baseline("dim_customer", 5, 8, "block")
    res = orchestrate_service.run_orchestration()
    report = res["report"]
    conn = db_mod.connect()
    try:
        flagged = orch_repo.list_attempts(conn, res["id"], anomaly=True)
    finally:
        conn.close()
    assert len(flagged) == report["anomaly_count"] == 2
    assert sum(1 for a in flagged if a["anomaly_policy"] == "alert") == report["anomaly_alert"]
    assert sum(1 for a in flagged if a["anomaly_policy"] == "block") == report["anomaly_block"]
    # Both successes are anomalous, so no normal success remains.
    assert report["normal_success"] == 0


def test_block_watermark_holds_prior_success_across_runs(fresh_db):
    """A block anomaly must preserve the last good watermark, not reset it."""
    # Run 1 with a healthy baseline writes a real watermark.
    orchestrate_service.run_orchestration()
    before = _watermarks()["dim_customer"]["watermark_ts"]
    assert before == "2026-11-10T17:30:00Z"

    # Run 2: dim_customer's count is now flagged and blocked.
    _set_baseline("dim_customer", 5, 8, "block")
    res = orchestrate_service.run_orchestration()
    after = _watermarks()["dim_customer"]
    assert after["watermark_ts"] == before  # held, timestamps unchanged
    assert after["updated_at"] is not None

    flagged = [a for a in _attempts(res["id"]) if a["is_anomaly"]][0]
    assert flagged["detail"]["watermark_action"] == "held"
    assert flagged["detail"]["watermark_before"] == before
    assert flagged["detail"]["watermark_after"] == before

    # A downstream skip is countable and report-consistent.
    assert res["report"]["skipped_anomaly"] == 1


def test_export_uses_attempt_time_baseline(fresh_db):
    from app.routers import attempts as attempts_router

    _set_baseline("ingest_orders", 5, 8, "alert")
    res = orchestrate_service.run_orchestration()
    # Simulate an operator retuning the baseline after the fact.
    _set_baseline("ingest_orders", 2, 4, "alert")

    body = attempts_router.export_attempts_ndjson(res["id"], anomaly=True)
    assert "artifact_rows=3 outside baseline [5, 8]" in body
    payload = json.loads(body.strip().splitlines()[0])
    assert payload["row_min"] == 5 and payload["row_max"] == 8
    assert payload["observed_rows"] == 3
    assert payload["anomaly_policy"] == "alert"

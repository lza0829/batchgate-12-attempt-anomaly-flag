from __future__ import annotations

from typing import Any

from app.config import FIXTURES_DIR
from app.db import connect
from app.engines.anomaly import POLICY_BLOCK, SKIPPED_ANOMALY, evaluate_row_baseline
from app.engines.dependency import BLOCKED_BY_ANOMALY, dependency_readiness, topological_layers
from app.engines.job_runner import run_fixture_job
from app.repositories import jobs as jobs_repo
from app.repositories import orchestrations as orch_repo
from app.repositories import watermarks as wm_repo


def dashboard_stats() -> dict[str, Any]:
    conn = connect()
    try:
        return {
            "job_count": conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"],
            "enabled_jobs": conn.execute(
                "SELECT COUNT(*) c FROM jobs WHERE enabled=1"
            ).fetchone()["c"],
            "orchestration_count": conn.execute(
                "SELECT COUNT(*) c FROM orchestrations"
            ).fetchone()["c"],
            "attempt_count": conn.execute(
                "SELECT COUNT(*) c FROM job_attempts"
            ).fetchone()["c"],
            "anomaly_attempt_count": conn.execute(
                "SELECT COUNT(*) c FROM job_attempts WHERE is_anomaly=1"
            ).fetchone()["c"],
            "watermarked_jobs": conn.execute(
                "SELECT COUNT(*) c FROM watermarks WHERE watermark_ts IS NOT NULL"
            ).fetchone()["c"],
        }
    finally:
        conn.close()


def _summarize_attempts(attempts: list[dict[str, Any]]) -> dict[str, int]:
    """Derive report counts from the persisted attempt rows.

    Everything the report claims is read back out of the same rows the attempt
    list shows, so the two can never drift apart.
    """
    succeeded = sum(1 for a in attempts if a["status"] == "success")
    failed = sum(1 for a in attempts if a["status"] == "failed")
    skipped = sum(1 for a in attempts if a["status"].startswith("skipped"))
    skipped_dep = sum(1 for a in attempts if a["status"] == "skipped_dep")
    skipped_anomaly = sum(1 for a in attempts if a["status"] == SKIPPED_ANOMALY)
    anomaly_count = sum(1 for a in attempts if a["is_anomaly"])
    anomaly_alert = sum(
        1 for a in attempts if a["is_anomaly"] and a["anomaly_policy"] == "alert"
    )
    anomaly_block = sum(
        1 for a in attempts if a["is_anomaly"] and a["anomaly_policy"] == "block"
    )
    return {
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "skipped_dep": skipped_dep,
        "skipped_anomaly": skipped_anomaly,
        "attempt_count": len(attempts),
        "anomaly_count": anomaly_count,
        "anomaly_alert": anomaly_alert,
        "anomaly_block": anomaly_block,
        # Successes that carried no anomaly flag — the trusted normal path.
        "normal_success": succeeded - anomaly_count,
    }


def run_orchestration() -> dict[str, Any]:
    conn = connect()
    try:
        jobs = [j for j in jobs_repo.list_jobs(conn) if j["enabled"]]
        orch_id = orch_repo.create_orchestration(conn)
        success_names: set[str] = set()
        anomaly_blocked_names: set[str] = set()
        layers = topological_layers(jobs)

        for layer in layers:
            for job in layer:
                ready, kind, reason = dependency_readiness(
                    job["depends_on"], success_names, anomaly_blocked_names
                )
                if not ready:
                    if kind == BLOCKED_BY_ANOMALY:
                        # This job never ran; mark it untrusted too so its own
                        # downstream reports the same root cause.
                        anomaly_blocked_names.add(job["name"])
                        orch_repo.insert_attempt(
                            conn,
                            orchestration_id=orch_id,
                            job_id=job["id"],
                            attempt_no=1,
                            status=SKIPPED_ANOMALY,
                            detail={"reason": reason, "cause": "upstream_anomaly"},
                            consequence="downstream_skipped",
                        )
                    else:
                        orch_repo.insert_attempt(
                            conn,
                            orchestration_id=orch_id,
                            job_id=job["id"],
                            attempt_no=1,
                            status="skipped_dep",
                            detail={"reason": reason},
                        )
                    continue

                try:
                    result = run_fixture_job(FIXTURES_DIR / job["fixture_path"])
                except Exception as exc:  # noqa: BLE001
                    orch_repo.insert_attempt(
                        conn,
                        orchestration_id=orch_id,
                        job_id=job["id"],
                        attempt_no=1,
                        status="failed",
                        detail={"error": str(exc)},
                    )
                    continue

                anomaly = evaluate_row_baseline(
                    result["artifact_rows"],
                    job["row_min"],
                    job["row_max"],
                    job["anomaly_policy"],
                )
                if anomaly is None:
                    orch_repo.insert_attempt(
                        conn,
                        orchestration_id=orch_id,
                        job_id=job["id"],
                        attempt_no=1,
                        status="success",
                        detail=result,
                    )
                    wm_repo.set_watermark(
                        conn, job["id"], result["watermark_ts"], result["artifact_rows"]
                    )
                    success_names.add(job["name"])
                    continue

                # Anomalous success: the job itself ran fine, but its row count
                # is outside the configured baseline. The flagged attempt keeps
                # status "success" and carries is_anomaly/consequence instead.
                policy = anomaly["policy"]
                prior = wm_repo.get_watermark(conn, job["id"]) or {}
                detail = {
                    **result,
                    "anomaly": anomaly,
                    "watermark_before": prior.get("watermark_ts"),
                }
                if policy == POLICY_BLOCK:
                    # Hold the watermark at its previous value and withhold the
                    # success flag so dependents skip with an anomaly cause.
                    consequence = "watermark_held_downstream_blocked"
                    detail["watermark_action"] = "held"
                    detail["watermark_after"] = prior.get("watermark_ts")
                    anomaly_blocked_names.add(job["name"])
                else:
                    consequence = "alerted_watermark_advanced"
                    wm_repo.set_watermark(
                        conn, job["id"], result["watermark_ts"], result["artifact_rows"]
                    )
                    detail["watermark_action"] = "advanced"
                    detail["watermark_after"] = result["watermark_ts"]
                    success_names.add(job["name"])
                orch_repo.insert_attempt(
                    conn,
                    orchestration_id=orch_id,
                    job_id=job["id"],
                    attempt_no=1,
                    status="success",
                    detail=detail,
                    is_anomaly=True,
                    anomaly_policy=policy,
                    anomaly_reason=anomaly["reason"],
                    consequence=consequence,
                )

        conn.commit()
        attempts = orch_repo.list_attempts(conn, orch_id)
        report = {
            "orchestration_id": orch_id,
            "job_total": len(jobs),
            "watermarked_jobs": conn.execute(
                "SELECT COUNT(*) c FROM watermarks WHERE watermark_ts IS NOT NULL"
            ).fetchone()["c"],
            "layer_count": len(layers),
            **_summarize_attempts(attempts),
        }
        status = "ok" if report["failed"] == 0 and report["anomaly_count"] == 0 else "partial"
        orch_repo.finish_orchestration(conn, orch_id, status, report)
        conn.commit()
        return orch_repo.get_orchestration(conn, orch_id) or report
    finally:
        conn.close()

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.db import connect
from app.repositories import orchestrations as orch_repo

router = APIRouter(tags=["attempts"])


@router.get("/attempts")
def list_attempts(orchestration_id: int | None = None, anomaly: bool | None = None):
    conn = connect()
    try:
        return orch_repo.list_attempts(conn, orchestration_id, anomaly)
    finally:
        conn.close()


def _export_payload(a: dict[str, Any]) -> dict[str, Any]:
    """One export record; baseline bounds come from attempt-time evidence.

    Reading the bounds from evidence rather than from the job's current row
    interval keeps the export truthful after later baseline edits.
    """
    evidence = a["detail"].get("anomaly", {}) if isinstance(a["detail"], dict) else {}
    return {
        "id": a["id"],
        "orchestration_id": a["orchestration_id"],
        "job_name": a["job_name"],
        "attempt_no": a["attempt_no"],
        "status": a["status"],
        "is_anomaly": a["is_anomaly"],
        "anomaly_policy": a["anomaly_policy"],
        "anomaly_reason": a["anomaly_reason"],
        "consequence": a["consequence"],
        "row_min": evidence.get("baseline_min"),
        "row_max": evidence.get("baseline_max"),
        "observed_rows": evidence.get("observed_rows"),
        "detail": a["detail"],
    }


def export_attempts_ndjson(
    orchestration_id: int | None = None, anomaly: bool | None = None
) -> str:
    conn = connect()
    try:
        rows = orch_repo.list_attempts(conn, orchestration_id, anomaly)
    finally:
        conn.close()
    lines = [json.dumps(_export_payload(a), ensure_ascii=False) for a in rows]
    return "\n".join(lines) + ("\n" if lines else "")


@router.get("/attempts/export")
def export_attempts(orchestration_id: int | None = None, anomaly: bool | None = None):
    body = export_attempts_ndjson(orchestration_id, anomaly)
    return StreamingResponse(
        iter([body]),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=attempts.jsonl"},
    )

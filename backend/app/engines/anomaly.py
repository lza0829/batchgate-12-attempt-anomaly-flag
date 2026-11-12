"""Row-count baseline calibration for successful job attempts.

The baseline strategy is an explicit per-job row interval (``row_min``/``row_max``),
not a threshold inferred from history.  An attempt is anomalous when its artifact
row count falls outside the inclusive interval.

Each job also carries a fixed consequence policy:

* ``alert``  — record the anomaly, advance the watermark, and let downstream
  jobs trust the upstream success.
* ``block``  — record the anomaly, hold the previous watermark, and skip
  downstream jobs that depend on this job.
"""

from __future__ import annotations

from typing import Any

POLICY_ALERT = "alert"
POLICY_BLOCK = "block"
POLICIES = (POLICY_ALERT, POLICY_BLOCK)

ANOMALY_KIND = "row_count_out_of_range"
SKIPPED_ANOMALY = "skipped_anomaly"


def evaluate_row_baseline(
    artifact_rows: int,
    row_min: int | None,
    row_max: int | None,
    policy: str | None,
) -> dict[str, Any] | None:
    """Return anomaly evidence when ``artifact_rows`` is outside the baseline.

    ``None`` is returned when no baseline is configured or the count is healthy.
    """
    if row_min is None or row_max is None:
        return None
    if row_min <= artifact_rows <= row_max:
        return None

    direction = "below_min" if artifact_rows < row_min else "above_max"
    selected_policy = policy if policy in POLICIES else POLICY_ALERT
    reason = (
        f"artifact_rows={artifact_rows} outside baseline "
        f"[{row_min}, {row_max}] ({direction})"
    )
    return {
        "kind": ANOMALY_KIND,
        "observed_rows": artifact_rows,
        "baseline_min": row_min,
        "baseline_max": row_max,
        "direction": direction,
        "policy": selected_policy,
        "reason": reason,
    }

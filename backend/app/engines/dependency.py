"""Dependency readiness from upstream success plus anomaly blocking."""

from __future__ import annotations

from typing import Any

READY = "ready"
BLOCKED_BY_ANOMALY = "blocked_by_anomaly"
UPSTREAM_NOT_SUCCESS = "upstream_not_success"


def ready_by_upstream_success(
    depends_on: list[str],
    success_job_names: set[str],
) -> tuple[bool, str]:
    missing = [name for name in depends_on if name not in success_job_names]
    if missing:
        return False, f"upstream not success: {', '.join(missing)}"
    return True, "ok"


def dependency_readiness(
    depends_on: list[str],
    success_job_names: set[str],
    anomaly_blocked_names: set[str] | None = None,
) -> tuple[bool, str, str]:
    """Return ``(ready, kind, reason)`` for a downstream job.

    An upstream whose own success was flagged anomalous and whose policy is
    ``block`` lands in ``anomaly_blocked_names``; it was not recorded as a
    trustworthy success.  Jobs skipped for that reason are propagated into the
    same set so transitive downstream jobs report the same cause.
    """
    blocked = anomaly_blocked_names or set()
    blocked_deps = [name for name in depends_on if name in blocked]
    if blocked_deps:
        return (
            False,
            BLOCKED_BY_ANOMALY,
            f"upstream anomaly blocked: {', '.join(blocked_deps)}",
        )
    missing = [name for name in depends_on if name not in success_job_names]
    if missing:
        return False, UPSTREAM_NOT_SUCCESS, f"upstream not success: {', '.join(missing)}"
    return True, READY, "ok"


def topological_layers(jobs: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group jobs into layers by declared depends_on names (best-effort for seed graphs)."""
    by_name = {j["name"]: j for j in jobs}
    remaining = set(by_name)
    done: set[str] = set()
    layers: list[list[dict[str, Any]]] = []
    while remaining:
        layer = []
        for name in sorted(remaining):
            deps = by_name[name]["depends_on"]
            if all(d in done for d in deps):
                layer.append(by_name[name])
        if not layer:
            # cycle or missing dep — dump rest as final layer for visibility
            layers.append([by_name[n] for n in sorted(remaining)])
            break
        layers.append(layer)
        for j in layer:
            remaining.remove(j["name"])
            done.add(j["name"])
    return layers

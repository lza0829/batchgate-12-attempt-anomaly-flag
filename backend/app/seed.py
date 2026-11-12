from app.db import connect


def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            fixture_path TEXT NOT NULL,
            depends_on_json TEXT NOT NULL,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            note TEXT,
            row_min INTEGER,
            row_max INTEGER,
            anomaly_policy TEXT NOT NULL DEFAULT 'alert'
        );
        CREATE TABLE IF NOT EXISTS orchestrations(
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            report_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_attempts(
            id INTEGER PRIMARY KEY,
            orchestration_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            attempt_no INTEGER NOT NULL,
            status TEXT NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_anomaly INTEGER NOT NULL DEFAULT 0,
            anomaly_policy TEXT,
            anomaly_reason TEXT,
            consequence TEXT
        );
        CREATE TABLE IF NOT EXISTS watermarks(
            job_id INTEGER PRIMARY KEY,
            watermark_ts TEXT,
            artifact_rows INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        );
        """
    )

    # Older local databases may predate the anomaly columns.
    _add_column_if_missing(conn, "jobs", "row_min", "INTEGER")
    _add_column_if_missing(conn, "jobs", "row_max", "INTEGER")
    _add_column_if_missing(conn, "jobs", "anomaly_policy", "TEXT NOT NULL DEFAULT 'alert'")
    _add_column_if_missing(conn, "job_attempts", "is_anomaly", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "job_attempts", "anomaly_policy", "TEXT")
    _add_column_if_missing(conn, "job_attempts", "anomaly_reason", "TEXT")
    _add_column_if_missing(conn, "job_attempts", "consequence", "TEXT")

    if conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 0:
        jobs = [
            (
                "ingest_orders",
                "ingest_orders.json",
                "[]",
                1,
                1,
                "无依赖：写出订单水位",
                2,
                4,
                "alert",
            ),
            (
                "dim_customer",
                "dim_customer.json",
                "[]",
                1,
                1,
                "无依赖：写出客户维表水位",
                1,
                3,
                "block",
            ),
            (
                "fact_order_daily",
                "fact_order_daily.json",
                '["ingest_orders","dim_customer"]',
                1,
                1,
                "依赖两路上游成功后才执行（底座仅查上游成功）",
                1,
                2,
                "alert",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO jobs(
                name, fixture_path, depends_on_json, max_attempts, enabled, note,
                row_min, row_max, anomaly_policy
            )
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            jobs,
        )
        for row in conn.execute("SELECT id FROM jobs").fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO watermarks(job_id, watermark_ts, artifact_rows, updated_at) VALUES (?,?,?,?)",
                (row["id"], None, 0, None),
            )
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            ("default_max_attempts", "1"),
        )
    conn.commit()
    conn.close()

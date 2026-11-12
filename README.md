# 02-batchgate（闸序）

Batchgate — 离线作业依赖编排：作业定义 → 依赖就绪检查 → 执行/失败重试 → 产出水位与对账。

与 Feedstitch（多源 Feed 归并）主链路不同，禁止做成 Feed 解析/冲突/回看换皮。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5200 |
| API | http://localhost:10200 |

## 主链

配置作业与依赖 → 触发一次编排 Run → 按依赖顺序执行夹具作业 → 写入尝试记录与产出水位 → 报告对账

## 种子说明

- **ingest_orders**：无依赖，写出订单水位；行数基线 `[2,4]`，异常动作 `alert`。
- **dim_customer**：无依赖，写出客户维表水位；行数基线 `[1,3]`，异常动作 `block`。
- **fact_order_daily**：依赖上两者成功且水位推进后才可执行（底座仅做“上游成功”检查，严格水位闸与重试预算留给 0-1 题）。

## 行数异常标定

基线策略为**每作业显式行数区间**（`row_min`/`row_max`），留空即不标定；
成功尝试的 `artifact_rows` 落在区间外即判为异常；区间为闭区间，`row_min`/`row_max` 需同时设置或同时清空。

| 异常动作 | 尝试记录 | 水位 | 下游 |
| --- | --- | --- | --- |
| `alert` | `success` + `is_anomaly=1` + `consequence=alerted_watermark_advanced` | 推进到本次水位 | 视为可信成功，照常执行 |
| `block` | `success` + `is_anomaly=1` + `consequence=watermark_held_downstream_blocked` | 保持上一次成功水位 | 记 `skipped_anomaly`（`consequence=downstream_skipped`），不再信任 |

- 异常原因写入 `job_attempts.anomaly_reason`（含观测行数、区间与越界方向），并在 `detail.anomaly`、`detail.watermark_action` / `watermark_before` / `watermark_after` 留证。
- 尝试记录接口支持 `?anomaly=true` 过滤；`/api/attempts/export` 导出 JSONL，历史尝试的区间取自当时证据，改基线后不回写历史。
- 编排报告由尝试行**回读汇总**：`anomaly_count` / `anomaly_alert` / `anomaly_block` / `skipped_anomaly` / `normal_success` 与尝试列表逐条一致。
- 水位保留上一次成功值，不做回补或按成本熔断。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 0-1 切口（未实现）

`dep_gate` / `retry_budget` / `sla_breach`（`watermark_reconcile` 的异常统计已随本功能落地）

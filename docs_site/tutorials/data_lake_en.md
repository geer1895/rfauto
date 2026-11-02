<!-- PR-10 文档站同步副本：源=docs/tutorials/data_lake_en.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# The Data Lake and Query Surface: run artifacts → datasets → DuckDB lake → queries

> Once `runs/` grows large, questions like "where are all those openEMS
> mline runs from last time, which ones have been judged, which campaign
> still has half-finished artifacts" can no longer be answered by browsing
> directories. This article shows how rfauto's three data-harvesting
> surfaces chain together: **datasets** (point-level data materialized into
> Parquet), the **lake** (a DuckDB index over the runs/ tree + tar.zst cold
> archiving and semantic compaction), and **db** (a SQLite transactional
> registry + DuckDB analytical direct-read + the engine league). All
> commands and outputs below were measured read-only in the current
> workspace (2026-10-11); a few sandbox demos were done in the system temp
> directory and deleted afterwards, and temporary absolute paths have been
> elided from the quoted text.
> Chinese original: docs/tutorials/data_lake.md. Commands and tool output
> below are preserved **verbatim from the measured runs** (the CLI's own
> messages stay in their original language); only the narrative is
> translated.

## 0. Prerequisites and three names

- Environment installed per docs/tutorials/getting-started.md, working
  directory at the repo root (`runs/`, `runs/.lake_index.duckdb`,
  `runs/registry.sqlite` all resolve relative to the cwd). Zero license,
  zero network throughout.
- Commands always go through `.venv/Scripts/rfauto.exe`.
- Three names not to be confused (one service module each, #222 audit
  caliber):

| Name | Command domain | Service module | In one sentence |
|---|---|---|---|
| Datasets | `rfauto datasets` | `service/dataset_service.py` et al. | run point-level data → Parquet + manifest, row-level SQL queries |
| Lake | `rfauto lake` | `service/lake_service.py`, `service/lake_compact_service.py` | full two-level runs/ tree into a DuckDB index; cold-tier pack/verify/restore; semantic compaction |
| Registry | `rfauto db` | `service/db_service.py` | SQLite transactional registry (runs table etc.) + DuckDB direct-read + the engine league |

## 1. Panorama: three harvest forms of one dataset

After a `rfauto run` finishes, artifacts land in `runs/<run_id>/`
(meta.json, S-parameters, trials, verdicts…). Three orthogonal roads lead
upward:

```text
runs/<run_id>/ （run 级目录，唯一事实源）
   │
   ├─① datasets 物化道：点级参数/指标 → runs/datasets/<名>/points.parquet
   │     消费：datasets query / coverage / warm-start / HF 导出
   │
   ├─② lake 索引道：runs/ 两层目录树 → runs/.lake_index.duckdb（runs_lake_index 表）
   │     消费：lake query / audit-stale / lineage / export-parquet
   │
   └─③ db 注册表道：runs/*/meta.json → runs/registry.sqlite（事务面）
         消费：db query / analytics-attach / league-rebuild+report
```

Division of labor intuition: querying **numbers by "design point"** goes
through ①; taking **inventory of the runs tree by "directory"** (which
runs are unjudged, which should be archived) goes through ②;
**transactional registration and the cross-engine league** go through ③.
Road ①'s materialization/query/health-gate judgment has its own article
(docs/tutorials/datasets_and_health_gates.md) — this article does not
repeat it and only covers its relationship with the lake in §7.

## 2. The lake index: `lake index` (idempotent rebuild)

```bash
.venv/Scripts/rfauto.exe lake index --help
```

Only three options: `--runs-dir` (scans first-level campaign directories +
second-level run points, **two levels**; default `runs`), `--db` (default
`runs/.lake_index.duckdb`), `--json`.

Rebuilding the index over the whole runs/ tree is a pure read scan
(thousands of directories, reading meta/verdict per directory for
precision) that drops one DuckDB file. The full chain demonstrated in a
temporary sandbox (two fake runs; deleted afterwards):

```bash
.venv/Scripts/rfauto.exe lake index --runs-dir <沙盒>/runs --db <沙盒>/lake.duckdb --json
```

```json
{
  "ok": true,
  "n_rows": 3,
  "n_meta_rows": 2,
  "n_verdict_rows": 0,
  "errors": [],
  "n_lineage_edges": 0,
  "db_path": "…（临时目录，略）",
  "table": "runs_lake_index"
}
```

How to read it:

- Both directory levels **enter the index** (3 rows here = 1 campaign
  directory + 2 run points); directory-level metadata with missing fields
  is NULL as-is, never invented.
- The index is a **rebuild-style snapshot**: it does not follow new runs
  automatically — measured evidence at the end of §3.
- DuckDB connections have defensive defaults: memory cap 2GB, thread cap 4
  (the lake index is a low-frequency batch surface; this prevents starving
  in-flight real-engine solves — `lake_service` constants).

## 3. Lake queries: `lake query` (read-only)

```bash
.venv/Scripts/rfauto.exe lake query --help
```

| Filter | Meaning |
|---|---|
| `--template` / `--adapter` / `--study` / `--campaign` | equality filters (meta fields / campaign directory name) |
| `--date-from` / `--date-to` | closed interval on created_date (YYYY-MM-DD) |
| `--limit` / `--order-by` / `--order` | row cap (default 200) / whitelisted sort column / asc·desc |

Sandbox query (same index as above):

```bash
.venv/Scripts/rfauto.exe lake query --db <沙盒>/lake.duckdb --template mline --order-by created_ts --order asc
```

```text
path  template  adapter  study  created_date  n_files
demo_campaign/20261001_000000_demo01  mline  fake  lake_tut  2026-10-01  2
demo_campaign/20261001_000100_demo02  mline  openems  lake_tut  2026-10-01  1
2 行
```

The repo's real index (built by an earlier batch) is queryable the same
way:

```bash
.venv/Scripts/rfauto.exe lake query --template mline --limit 3 --order-by created_ts --order desc
```

```text
path  template  adapter  study  created_date  n_files
20260922_014743_ccbb2894  mline  openems  datafactory_a2d  2026-09-21  4
20260922_014704_e82608e4  mline  openems  datafactory_a2d  2026-09-21  4
20260922_014626_82e51cb6  mline  openems  datafactory_a2d  2026-09-21  4
3 行
```

Measured evidence of the snapshot semantics: querying
`--date-from 2026-10-01 --date-to 2026-10-11` returns **0 rows** (the
index was built in an earlier batch; later runs are not in it) — **rebuild
with `lake index` before querying**; never treat an old snapshot as the
full set. The query surface is read-only parameterized SQL (values only
enter `?` bindings, never concatenated into SQL).

## 4. Three lake patrols: `sweep` / `audit-stale` / `lineage`

### 4.1 `lake sweep`: read-only half-artifact inventory

```bash
.venv/Scripts/rfauto.exe lake sweep --max-list 5
```

```text
✓ dirs=11223  complete=10  incomplete=383  empty=6279  unannotated=2506
  20260903_235147_cb982df7/calibration  files=227  markers=['samples.json']
  …（明细按 --max-list 截断）
```

Four-state caliber: `complete` = has meta; `empty` = zero files, an empty
shell; `incomplete` = no meta but artifact evidence exists (running or
interrupted — meta lands only when a run ends, #144; do not sweep
incomplete away as garbage); `unannotated` = no meta and no known
artifacts. The whole command performs zero writes.

### 4.2 `lake audit-stale`: the stale-run list

Scans the whole lake for runs whose judgments may have gone stale after
"code/params/engine/environment/budget changed", classified by cause. Exit
codes: 0 = no staleness, 1 = stale rows exist, 2 = procedural error —
wire it straight into a CI gate.

```bash
.venv/Scripts/rfauto.exe lake audit-stale --json
```

```json
{
  "ok": true,
  "n_dirs": 5310,
  "n_checked": 3051,
  "n_stale": 2983,
  "n_fresh": 68,
  "n_unknown_meta": 2259,
  "class_counts": { … }
}
```

A large n_stale is the norm (code grows, judgment anchors get
recalibrated); its purpose is **prioritizing re-runs**, not convicting
history; stale causes are bucketed in `class_counts`.

### 4.3 `lake lineage`: cross-run lineage

Dataset → upstream runs → render commit endpoints (`--up`, the default),
or the reverse blast radius (`--down`). It relies on the `run_lineage`
edge table in the index database (generated together with `lake index`
rebuilds):

```bash
.venv/Scripts/rfauto.exe lake lineage --run 20260920_002700_2bb07757 --hops 3
```

```text
20260920_002700_2bb07757  model=mline  git_sha=a6dcc7d  (起点)
n_nodes_total=1  children_count=0  hops=3  direction=up
```

This point has no upstream edges (a run_once shape), so n_nodes_total=1
as-is; data-factory batch artifacts are what unfold edge families.
`--expand` lists every node (the default is a capped summary to prevent
explosions).

## 5. Cold-tier archiving: `pack` / `verify` / `restore`

After a campaign ends, directories easily hold thousands of files; the
lake provides a content-addressed cold-tier trio (sandbox-measured, the
original directory untouched):

```bash
# ① 打包：确定性文件排序 + 归一化 tar 头 → 同内容重打包 sha256 逐位一致
.venv/Scripts/rfauto.exe lake pack <沙盒>/runs/demo_campaign --out <沙盒>/demo.tar.zst
```

```text
✓ files=3  total=243B
pack=<沙盒>/demo.tar.zst
  sha256=cd9967c654e08a7df5bcdef47531dfa70804ed461a2325288593438d6f07f410
manifest=<沙盒>/demo.tar.zst.manifest.json
```

```bash
# ② 校验：整包 sha256 快校验 + 逐文件 sha256 重算（如实逐文件报告）
.venv/Scripts/rfauto.exe lake verify <沙盒>/demo.tar.zst <沙盒>/demo.tar.zst.manifest.json
```

```text
pack_sha256_ok=True  ok=3  fail=0
  ok  20261001_000000_demo01/meta.json
  ok  20261001_000000_demo01/sparams.csv
  ok  20261001_000100_demo02/meta.json
```

```bash
# ③ 恢复：目标目录必须不存在（绝不覆盖），恢复后逐文件哈希复核
.venv/Scripts/rfauto.exe lake restore <沙盒>/demo.tar.zst <沙盒>/demo.tar.zst.manifest.json <沙盒>/restored
```

```text
✓ restored=3/3  bytes=243
target=<沙盒>/restored
```

The manifest records each file's relative path + offset + size + sha256;
`verify` can re-hash by offset without unpacking the whole archive —
integrity checks for thousand-file campaigns are second-scale actions. The
original directory is untouched by archiving; deleting it is **a human**
decision — the lake's job is to make that decision verifiable and
reversible.

## 6. Semantic compaction: `lake compact` (dry-run by default, --apply interlocked)

`lake compact` is the lake's "gc planning surface"
(`lake_compact_service`): h5 whitelist retention-policy derivation (anchor
registry / sim_ci golden baselines / directory-name heuristics — three
pointer sources) + et/ht content-addressed dedup + three-tier
(conservative/medium/aggressive) deletion statistics. **Pure-read planning
by default**:

```bash
.venv/Scripts/rfauto.exe lake compact --runs-root runs --json   # 纯读，三档统计
```

Real deletion requires `--apply` and has a prerequisite interlock: refused
while the XD-5 golden baseline is unpinned (pin it first with
`rfauto simci-pin-baseline`); the default path is reversible —
deleted-listed h5 files are first blob-ified into `runs/.blob_store`
(content-addressed + manifest audit), restorable within an observation
window (default 30 days), physically released only at window-end purge;
`--no-reversible` is the legacy straight-delete path. Two more conservative
valves: `--min-age-h` (default 24h; too-new meta is never touched) and
`--exempt-subtree` (user-exempted subtrees). In one sentence: **destructive
actions never run automatically**.

The companion retrieval accelerator: bounded VF summaries of sparams
(`sparams.vf.json`, with an L∞ error bound; summaries without an error
bound are never written) appear in the index as the `vf_summary` column
(lossless_equivalent / bounded_lossy / NULL), filterable by fidelity tier
without decompression.

## 7. The `datasets` command domain and its relationship to the lake

The eight `datasets` subcommands (materialize / query / discover-workdir /
import-workdir / coverage / annotate / visibility / export-hf) run road ①:
turning run point-level data into **rows**. Division of labor and joints
with the lake:

| Question | Which surface | Why |
|---|---|---|
| "which parameters belong to design points with cost < 0.1" | `datasets query` | row-level SQL + json_extract over params |
| "which parameter dimension was never swept" | `datasets coverage` | per-dimension occupancy / weakest dimension |
| "which of these run directories are unjudged / empty shells" | `lake sweep` | directory-level inventory, reads no numbers |
| "archive this batch of directories" | `lake pack` | content-addressed cold tier |
| "hand the lake index to an external engine" | `lake export-parquet` | DuckDB COPY into a hive-partitioned cold tier (partitioned by created_date by default; `--overwrite` required to overwrite) |

Joints: dataset materialization's fingerprint dedup keys on
run_id+parameter fingerprint (no cross-campaign folding), and the lake
index's `lineage` surface links dataset names back to upstream runs.
Materialization always passes the health gate (G11); `--dry-run` yields a
zero-write plan surface:

```bash
.venv/Scripts/rfauto.exe datasets materialize -n tut_demo \
  --runs 20260829_191826_da184d1d,20260829_191828_25c6b5d5 --dry-run
```

```text
物化计划（dry-run，零写入） name=tut_demo  格式: parquet
  将物化 2 个 run（健康门 not evaluated）
    20260829_191826_da184d1d
    20260829_191828_25c6b5d5
```

Two read-only queries against the repo's existing datasets (column pruning
+ coverage):

```bash
.venv/Scripts/rfauto.exe datasets query datafactory_m1_mline_20260919 \
  --limit 2 --columns run_id,model,cost
.venv/Scripts/rfauto.exe datasets coverage datafactory_m1_mline_20260919
```

```text
  数据集 datafactory_m1_mline_20260919（2 行，过滤后共 120 行）
┌──────────────────────────┬───────┬──────┐
│ run_id                   │ model │ cost │
├──────────────────────────┼───────┼──────┤
│ 20260920_002700_2bb07757 │ mline │      │
│ 20260920_002731_b1e97e8c │ mline │      │
└──────────────────────────┴───────┴──────┘

✓ datafactory_m1_mline_20260919（120 行）
  mean occupancy: 1.0  min: 1.0  最弱维: w_mm
```

(An empty cost column = that batch's cost is NULL — when cost has no
uniform semantics it is set NULL (nullable-column contract), to be
backfilled later by annotation/judgment surfaces; per-dimension occupancy
of 1.0 means the parameter space is a full grid. For judgment details see
docs/tutorials/datasets_and_health_gates.md.)

## 8. The `db` command domain: transactional registry + analytical direct-read

The `db` domain is a SQLite transactional registry (zero servers) + DuckDB
analytical direct-read:

```bash
.venv/Scripts/rfauto.exe db status
```

```text
runs\registry.sqlite  [存在]  schema_version=1
  runs: 1779
  jobs: 0
  approvals: 0
  datasets: 0
  owners: 0
```

Eight-subcommand quick reference (each `--help` measured):

| Command | Write/Read | When to use |
|---|---|---|
| `db init` | write | fresh-environment database creation + idempotent migration (replays applied=0) |
| `db migrate` | write | schema migration (`--dry-run` yields a zero-write plan surface) |
| `db status` | read | path/existence/schema version/per-table row counts (never creates a missing file) |
| `db reindex-runs` | write | scan `runs/*/meta.json` and rebuild the runs table (upsert idempotent; a single file's failure does not block) |
| `db query` | read | single whitelisted SELECT + `?` parameter binding (`-p` passes params; refusals land in the envelope) |
| `db analytics-attach` | read | DuckDB sqlite extension direct-read of the registry (zero-copy analytics; unavailable → ok=False as-is) |
| `db league-rebuild` | write | scan runs/ verdict shapes into a whitelist extraction → `runs/league.duckdb` (idempotent rebuild) |
| `db league-report` | read | per (template family, quantity), the \|delta\| median × wall_s median Pareto front (JSON+md dual output) |

Read-only query and analytical direct-read, measured:

```bash
.venv/Scripts/rfauto.exe db query "SELECT run_id, model, adapter FROM runs LIMIT 3"
```

```text
run_id  model  adapter
20260925_062950_1a6365e9  wilkinson_power_divider  fake
20260829_191826_da184d1d  wilkinson_power_divider  fake
20260829_191828_25c6b5d5  wilkinson_power_divider  fake
3 行
```

```bash
.venv/Scripts/rfauto.exe db analytics-attach
```

```text
✓ duckdb 1.5.5 attached runs\registry.sqlite as reg
  runs: 1779
  …（各表行数 + 最近 runs 示例查询）
```

The league surface (reading the board, F6 acceptance semantics) has its
own article, docs/tutorials/compose_and_league.md; here is the minimal
closed loop: `db league-rebuild` (rebuild, idempotent) →
`db league-report --json` (read the front; measured ok=true with groups
grouped by template_family×quantity, e.g. branchline_coupler ×
s11_db_max_in_band).

## 9. What next

- Health-gate judgment of point-level data (G11 three states × four-level
  factors): docs/tutorials/datasets_and_health_gates.md
- How to read the league table (Pareto fronts and F6 acceptance):
  docs/tutorials/compose_and_league.md
- Injecting dataset history into optimization as a prior:
  `rfauto warm-start --help`
- Same-source MCP client tools: list_datasets / query_dataset (the
  152-tool surface, docs/tutorials/mcp_in_practice.md)

## Appendix: verification checklist of this article

| Command/number | How it was checked | Result |
|---|---|---|
| `rfauto lake --help` ten subcommands (index/query/pack/verify/restore/sweep/export-parquet/audit-stale/lineage/compact) | real run | pass (flags checked one by one) |
| `rfauto db --help` eight subcommands (init/migrate/status/reindex-runs/query/analytics-attach/league-rebuild/league-report) | real run | pass |
| `rfauto datasets --help` eight subcommands | real run | pass |
| `lake index` sandbox (2 fake runs + 1 campaign dir → n_rows=3/n_meta_rows=2) | real run in temp dir, deleted afterwards | pass (§2 output quoted, db_path elided) |
| `lake query` sandbox 2 rows + repo `--template mline` 3 rows + date-window 0 rows | real run | pass (§3 output quoted) |
| `lake sweep` four-state counts (11223/10/383/6279/2506) | real run | pass (§4.1) |
| `lake audit-stale` counts (5310/3051/2983/68/2259) | real run --json | pass (§4.2) |
| `lake lineage` origin run n_nodes_total=1 | real run | pass (§4.3) |
| `lake pack/verify/restore` sandbox chain (sha256 → ok=3 fail=0 → restored=3/3) | real run in temp dir, deleted afterwards | pass (§5 output quoted, paths elided) |
| `datasets materialize --dry-run` 2-run plan surface | real run | pass (§7) |
| `datasets query/coverage` (120 rows, weakest dim w_mm) | real run | pass (§7 output quoted) |
| `db status` (runs: 1779) / `db query` 3 rows / `analytics-attach` (duckdb 1.5.5) / `league-report --json` | real run | pass (§8 output quoted) |
| DuckDB resource defaults (memory 2GB / 4 threads), `vf_summary` column, compact interlocks and observation window | `service/lake_service.py`, `service/lake_compact_service.py` source read | pass |
| Sensitive surface | repo-article grep: real IPs/hostnames/drive-letter paths/credentials zero hits | pass |

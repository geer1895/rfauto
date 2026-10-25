"""aurora_k K10 em sweep（DOE/矩阵编排器）测试（反馈 P16/F9）。

覆盖面（全离线，执行核/内存闸全部 mock——#139 钉通道口径）：
- 矩阵展开 2×2×4=16 形态钉（用户实战矩阵）：case_id 命名/轴序/参数
  合并/axis_key 映射/dict 轴值（label+params 组覆盖）；
- sweep 身份指纹：同 yaml 同根（resume 天然落同根）、改配置换根；
- plan 非法形态点名（缺文件/缺 base_recipe/缺 matrix/非法 adapter/
  非法 label/dup case_id）；
- resume 语义：账本 done + run 产物复核（meta 终态+Touchstone）才跳过；
  产物缺失如实降级 pending（P11"旧产物冒充新结果"防线）；
- 内存闸阻塞：低内存 → 该 case blocked_memory、串行链停跑、执行核零调用
  （不硬跑）；
- dry-run 零执行零副作用（执行核/内存闸/janitor 全零调用、零目录落盘）；
- 串行强制：max_aedt>1 显式拒绝；
- 逐 case 执行 + case 失败不连坐（后续 case 继续）+ case.json 账本；
- 汇总：mock 执行核造含产物 run 目录（metrics.json+Touchstone）→
  summary.csv/json 行数与指标（含 K8 面现场提取 em.c_series_f 逐位回收）、
  missing 如实点名；
- CLI 冒烟（CliRunner --json 成功/失败信封+退出码；dry-run）。

隔离（#144）：全程 monkeypatch.chdir(tmp_path)——runs_root() 双根收敛
把 sweep 根落 tmp/runs/em_sweep，绝不污染仓 runs/ 湖。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.service import em_sweep_service as svc

# ── 语料：用户实战形态（2 器件 × 2 版本 × 4 衬底厚度 = 16 组） ────────────────

_BASE_RECIPE = {
    "model": "oct_ind",
    "design_name": "IPD",
    "params": {"W_um": 15, "S_um": 15, "turns": 4, "sub_t_um": 200,
               "er": 12.85},
    "objectives": [{"metric": "L_nh", "op": "target", "value": 4.2,
                    "band": [2.0, 3.0]}],
}

_CASES_YAML = """
base_recipe: base.yaml
matrix:
  device: [ind, idc]
  version:
    - label: v5
      params: {metal_t_um: 5.0}
    - label: v6
      params: {metal_t_um: 3.0}
  thickness: [200, 150, 100, 50]
axis_key:
  thickness: sub_t_um
params:
  er: 12.9
"""


@pytest.fixture()
def cases_dir(tmp_path, monkeypatch):
    """chdir 隔离（#144）+ 写 base.yaml/cases.yaml 语料。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "base.yaml").write_text(
        yaml.safe_dump(_BASE_RECIPE), encoding="utf-8")
    (tmp_path / "cases.yaml").write_text(_CASES_YAML, encoding="utf-8")
    return tmp_path


def _gate_ok(min_free_gb: float) -> dict:
    return {"ok": True, "available_gb": 99.0, "threshold_gb": min_free_gb,
            "message": "闸放行", "channel": "test"}


def _gate_low(min_free_gb: float) -> dict:
    return {"ok": False, "available_gb": 1.0, "threshold_gb": min_free_gb,
            "message": "闸不放行", "channel": "test", "errors": []}


@pytest.fixture()
def gate_pass(monkeypatch):
    monkeypatch.setattr("rfauto.service.resource_janitor_service.memory_gate",
                        _gate_ok)


# ── mock 执行核：造含产物 run 目录（meta 终态+metrics.json+Touchstone） ──────

_C_DUT, _R_DUT = 173.5e-15, 1.4


def _make_touchstone(run_dir: Path) -> None:
    """合成 2 端口 T 型串联 RC 的 Touchstone（K8 面可逐位回收的已知量）。"""
    import skrf

    freq = skrf.Frequency.from_f(np.linspace(1e9, 5e9, 41), unit="hz")
    omega = 2 * np.pi * freq.f
    z12 = _R_DUT + 1 / (1j * omega * _C_DUT)
    z = np.zeros((len(freq.f), 2, 2), dtype=complex)
    z[:, 0, 0] = z[:, 1, 1] = z[:, 0, 1] = z[:, 1, 0] = z12
    net = skrf.Network(frequency=freq, s=skrf.network.z2s(z, z0=50), z0=50)
    out = run_dir / "results" / "params.s2p"
    out.parent.mkdir(parents=True, exist_ok=True)
    net.write_touchstone(str(out))


def _fake_executor_factory(fail_markers: tuple[str, ...] = (),
                           counter: dict | None = None,
                           touchstone: bool = True):
    """mock 执行核：读 case 配方 params 造产物 run 目录，返回 run_once 形态信封。

    fail_markers：case_id 含任一标记 → error 信封（solve_failed 语义）。
    """
    def _execute(recipe_path: Path, adapter_name: str) -> dict:
        recipe = yaml.safe_load(Path(recipe_path).read_text(encoding="utf-8"))
        case_id = Path(recipe_path).parent.name
        if counter is not None:
            counter["n"] = counter.get("n", 0) + 1
        if any(m in case_id for m in fail_markers):
            return {"ok": False, "errors": ["求解失败: mock"],
                    "run_id": f"fail-{case_id}", "run_dir": ""}
        run_dir = Path(recipe_path).parent / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "meta.json").write_text(
            json.dumps({"run_id": case_id, "status": "done",
                        "adapter": adapter_name}), encoding="utf-8")
        (run_dir / "results").mkdir(exist_ok=True)
        sub_t = (recipe.get("params") or {}).get("sub_t_um", 200)
        (run_dir / "results" / "metrics.json").write_text(
            json.dumps({"metrics": {"L_nh": 4.2 + sub_t / 1000.0,
                                    "Q": 12.0},
                        "cost": 0.1}), encoding="utf-8")
        if touchstone:
            _make_touchstone(run_dir)
        return {"ok": True, "run_id": case_id, "run_dir": str(run_dir)}
    return _execute


# ── plan：矩阵展开与身份指纹 ──────────────────────────────────────────────────


def test_plan_expands_2x2x4_matrix(cases_dir):
    plan = svc.plan_sweep(cases_dir / "cases.yaml")
    assert plan["ok"], plan.get("errors")
    assert plan["n_cases"] == 16
    ids = [c["case_id"] for c in plan["cases"]]
    assert len(set(ids)) == 16
    # 轴序=书写序（device × version × thickness），先 device 后 version
    assert ids[0] == "ind-v5-200" and ids[1] == "ind-v5-150"
    assert ids[2] == "ind-v5-100" and ids[3] == "ind-v5-50"
    assert ids[4] == "ind-v6-200"
    assert ids[-1] == "idc-v6-50"
    first = plan["cases"][0]
    assert first["axes"] == {"device": "ind", "version": "v5",
                             "thickness": "200"}
    # 参数合并：基配方 ∪ 全局 params（er 覆盖 12.9）∪ axis_key 映射
    # （thickness→sub_t_um=200）∪ dict 轴值 params（metal_t_um=5.0）
    assert first["params"]["sub_t_um"] == 200
    assert first["params"]["metal_t_um"] == 5.0
    assert first["params"]["er"] == 12.9
    assert first["params"]["W_um"] == 15  # 基配方未覆盖键保留
    v6 = next(c for c in plan["cases"] if c["case_id"] == "idc-v6-50")
    assert v6["params"]["metal_t_um"] == 3.0
    assert v6["params"]["sub_t_um"] == 50
    assert plan["adapter"] == "hfss"  # 缺省（P16 真机场景）
    assert all(c["status"] == "pending" for c in plan["cases"])


def test_plan_fingerprint_stable_and_content_addressed(cases_dir):
    p1 = svc.plan_sweep(cases_dir / "cases.yaml")
    p2 = svc.plan_sweep(cases_dir / "cases.yaml")
    assert p1["sweep_root"] == p2["sweep_root"]
    (cases_dir / "cases.yaml").write_text(
        _CASES_YAML.replace("thickness: [200, 150, 100, 50]",
                            "thickness: [200, 150, 100]"), encoding="utf-8")
    p3 = svc.plan_sweep(cases_dir / "cases.yaml")
    assert p3["sweep_root"] != p1["sweep_root"]
    assert p3["n_cases"] == 12


def test_plan_adapter_override_and_validation(cases_dir):
    assert svc.plan_sweep(cases_dir / "cases.yaml",
                          adapter_override="fake")["adapter"] == "fake"
    bad = svc.plan_sweep(cases_dir / "cases.yaml", adapter_override="qucs")
    assert not bad["ok"] and any("hfss|fake" in e for e in bad["errors"])


@pytest.mark.parametrize(("mangle", "needle"), [
    ("base_recipe: missing.yaml\nmatrix: {a: [1]}\n", "base_recipe"),
    ("matrix:\n  a: [1]\n", "base_recipe"),  # 缺 base_recipe 键
    ("base_recipe: base.yaml\n", "matrix"),  # 缺 matrix
    ("base_recipe: base.yaml\nmatrix: {a: []}\n", "矩阵展开失败"),
    ("base_recipe: base.yaml\nmatrix:\n  a:\n    - label: x/y\n      params: {}\n",
     "非法字符"),
    ("base_recipe: base.yaml\nmatrix:\n  a: [1]\n  b: [1]\nnaming: {sep: '/'}\n",
     "非法字符"),
    ("base_recipe: base.yaml\nmatrix:\n  a: [{params: {k: 1}}]\n", "label"),
])
def test_plan_rejects_invalid_schemas(tmp_path, monkeypatch, mangle, needle):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "base.yaml").write_text(yaml.safe_dump(_BASE_RECIPE),
                                        encoding="utf-8")
    (tmp_path / "cases.yaml").write_text(mangle, encoding="utf-8")
    result = svc.plan_sweep(tmp_path / "cases.yaml")
    assert not result["ok"]
    assert any(needle in str(e) for e in result["errors"]), result["errors"]


def test_plan_rejects_duplicate_case_ids_and_missing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing = svc.plan_sweep(tmp_path / "nope.yaml")
    assert not missing["ok"] and any("不存在" in e for e in missing["errors"])
    (tmp_path / "base.yaml").write_text(yaml.safe_dump(_BASE_RECIPE),
                                        encoding="utf-8")
    # dict 轴值两个同 label → case_id 重复（拼接歧义）
    (tmp_path / "cases.yaml").write_text(
        "base_recipe: base.yaml\nmatrix:\n"
        "  a: [{label: x, params: {}}, {label: x, params: {}}]\n",
        encoding="utf-8")
    dup = svc.plan_sweep(tmp_path / "cases.yaml")
    assert not dup["ok"] and any("重复" in e for e in dup["errors"])


# ── label Windows 文件名陷阱（aurora_l A2 席，K20/R4 P2） ────────────────────


def _plan_with_labels(tmp_path, monkeypatch, cases_text):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "base.yaml").write_text(yaml.safe_dump(_BASE_RECIPE),
                                        encoding="utf-8")
    (tmp_path / "cases.yaml").write_text(cases_text, encoding="utf-8")
    return svc.plan_sweep(tmp_path / "cases.yaml")


@pytest.mark.parametrize(("cases_text", "needle"), [
    # 尾点：Windows 剥尾点后 v5. 与 v5 同一物理目录 → case.json 相互覆盖串案
    ("base_recipe: base.yaml\nmatrix:\n  version:\n"
     "    - label: v5.\n      params: {k: 1}\n"
     "    - label: v5\n      params: {k: 2}\n", "Windows 文件名限制"),
    # 保留设备名（标量轴值）
    ("base_recipe: base.yaml\nmatrix: {device: [con, ind]}\n", "保留设备名"),
    # 保留设备名带扩展名形态 con.yaml（Windows 一律解析成设备）
    ("base_recipe: base.yaml\nmatrix:\n"
     "  a: [{label: con.yaml, params: {}}]\n", "保留设备名"),
    # aux（大写不豁免：不区分大小写）
    ("base_recipe: base.yaml\nmatrix: {device: [AUX]}\n", "保留设备名"),
    # 尾空格（YAML 双引号保尾空格）
    ("base_recipe: base.yaml\nmatrix:\n"
     "  a: [{label: \"a \", params: {}}]\n", "以点或空格结尾"),
    # 连续点
    ("base_recipe: base.yaml\nmatrix: {device: [\"a..b\"]}\n", "连续点"),
    # sep 拼接面终门：label 各自合法，sep 串点仍拼出连续点
    ("base_recipe: base.yaml\nmatrix: {a: [x], b: [y]}\n"
     "naming: {sep: '...'}\n", "连续点"),
])
def test_plan_rejects_windows_label_traps(tmp_path, monkeypatch, cases_text,
                                          needle):
    plan = _plan_with_labels(tmp_path, monkeypatch, cases_text)
    assert not plan["ok"]
    assert any(needle in str(e) and "Windows 文件名限制" in str(e)
               for e in plan["errors"]), plan["errors"]


def test_plan_allows_windows_safe_labels(tmp_path, monkeypatch):
    # 安全正例：内部点/保留名前缀/COM10（不在保留列）/连字符组合全放行
    plan = _plan_with_labels(
        tmp_path, monkeypatch,
        "base_recipe: base.yaml\nmatrix:\n"
        "  device: [con-x, aux2, COM10, a.b, ind]\n  t: [50]\n")
    assert plan["ok"], plan.get("errors")
    assert plan["n_cases"] == 5
    ids = {c["case_id"] for c in plan["cases"]}
    assert {"con-x-50", "aux2-50", "COM10-50", "a.b-50", "ind-50"} == ids


# ── resume：完成复核语义 ─────────────────────────────────────────────────────


def _fabricate_done_case(plan: dict, case_id: str, *, touchstone=True,
                         meta_status="done") -> Path:
    case = next(c for c in plan["cases"] if c["case_id"] == case_id)
    case_dir = Path(case["case_dir"])
    run_dir = case_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(
        json.dumps({"status": meta_status}), encoding="utf-8")
    if touchstone:
        _make_touchstone(run_dir)
    svc._write_case_record(case_dir, {
        "case_id": case_id, "status": "done", "run_dir": str(run_dir)})
    return run_dir


def test_resume_skips_only_verified_done_cases(cases_dir):
    plan = svc.plan_sweep(cases_dir / "cases.yaml")
    _fabricate_done_case(plan, "ind-v5-200")                       # 真完成
    _fabricate_done_case(plan, "ind-v5-150", touchstone=False)     # 缺产物
    _fabricate_done_case(plan, "ind-v5-100", meta_status="solve_failed")
    resumed = svc.plan_sweep(cases_dir / "cases.yaml", resume=True)
    by_id = {c["case_id"]: c["status"] for c in resumed["cases"]}
    assert by_id["ind-v5-200"] == "done"          # 复核通过 → 跳过清单
    assert by_id["ind-v5-150"] == "pending"       # 账本 done 但无 Touchstone
    assert by_id["ind-v5-100"] == "pending"       # meta 非 done 终态
    assert resumed["n_done"] == 1 and resumed["n_pending"] == 15
    fresh = svc.plan_sweep(cases_dir / "cases.yaml")  # 缺省 resume=False 全 pending
    assert all(c["status"] == "pending" for c in fresh["cases"])


# ── run：串行强制/dry-run/内存闸/逐 case 执行 ────────────────────────────────


def test_run_rejects_parallel_max_aedt(cases_dir):
    plan = svc.plan_sweep(cases_dir / "cases.yaml")
    result = svc.run_sweep(plan, max_aedt=2)
    assert not result["ok"]
    assert any("串行" in e for e in result["errors"])


def test_run_dry_run_zero_execution(cases_dir, monkeypatch):
    plan = svc.plan_sweep(cases_dir / "cases.yaml")
    calls = {"n": 0}
    monkeypatch.setattr(svc, "_default_case_executor",
                        _fake_executor_factory(counter=calls))
    monkeypatch.setattr("rfauto.service.resource_janitor_service.memory_gate",
                        _gate_ok)
    monkeypatch.setattr(svc, "_janitor_pre_clean",
                        lambda: pytest.fail("dry-run 不得触发 janitor"))
    result = svc.run_sweep(plan, dry_run=True, janitor=True)
    assert result["ok"] and result["verdict"] == "DRY_RUN"
    assert result["n_cases"] == 16
    assert calls["n"] == 0
    sweep_root = Path(plan["sweep_root"])
    assert not sweep_root.exists()  # 零副作用：目录都不建


def test_run_memory_gate_blocks_without_execution(cases_dir, monkeypatch):
    plan = svc.plan_sweep(cases_dir / "cases.yaml")
    calls = {"n": 0}
    monkeypatch.setattr(svc, "_default_case_executor",
                        _fake_executor_factory(counter=calls))
    monkeypatch.setattr("rfauto.service.resource_janitor_service.memory_gate",
                        _gate_low)
    result = svc.run_sweep(plan, min_free_gb=8.0)
    assert not result["ok"]
    assert result["n_blocked"] == 1
    assert result["n_failed"] == 0
    statuses = {c["case_id"]: c["status"] for c in result["cases"]}
    assert statuses["ind-v5-200"] == "blocked_memory"
    assert statuses["ind-v5-150"] == "not_run"  # 串行链停跑
    assert calls["n"] == 0                       # 不硬跑：执行核零调用
    record = json.loads((Path(plan["sweep_root"]) / "ind-v5-200"
                         / "case.json").read_text(encoding="utf-8"))
    assert record["status"] == "blocked_memory"
    assert record["memory_gate"]["available_gb"] == 1.0


def test_run_serial_all_cases_then_resume_skips(cases_dir, gate_pass):
    plan = svc.plan_sweep(cases_dir / "cases.yaml")
    calls = {"n": 0}
    executor = _fake_executor_factory(counter=calls)
    result = svc.run_sweep(plan, execute_fn=executor)
    assert result["ok"], result.get("errors")
    assert result["n_done"] == 16 and calls["n"] == 16
    assert result["n_failed"] == 0 and result["n_blocked"] == 0
    # case.json 账本：done + run_dir 指针 + 物化配方副本
    rec = json.loads((Path(plan["sweep_root"]) / "idc-v6-50" / "case.json")
                     .read_text(encoding="utf-8"))
    assert rec["status"] == "done" and Path(rec["run_dir"]).is_dir()
    recipe = yaml.safe_load((Path(plan["sweep_root"]) / "idc-v6-50"
                             / "case.recipe.yaml").read_text(encoding="utf-8"))
    assert recipe["params"]["sub_t_um"] == 50
    assert recipe["model"] == "oct_ind"
    # 第二轮 --resume：复核通过全跳过，执行核零调用
    resumed_plan = svc.plan_sweep(cases_dir / "cases.yaml", resume=True)
    assert resumed_plan["n_done"] == 16
    result2 = svc.run_sweep(resumed_plan, execute_fn=executor)
    assert result2["ok"] and result2["n_skipped_resume"] == 16
    assert calls["n"] == 16  # 未增加


def test_run_case_failure_continues(cases_dir, gate_pass):
    plan = svc.plan_sweep(cases_dir / "cases.yaml")
    calls = {"n": 0}
    result = svc.run_sweep(
        plan, execute_fn=_fake_executor_factory(fail_markers=("idc",),
                                                counter=calls))
    assert not result["ok"]  # 有失败 → 整体不绿（如实）
    assert result["n_failed"] == 8 and result["n_done"] == 8
    assert calls["n"] == 16  # 失败不连坐：后续 case 照跑
    statuses = {c["case_id"]: c["status"] for c in result["cases"]}
    assert statuses["ind-v5-200"] == "done"
    assert statuses["idc-v6-50"] == "failed"


def test_run_base_recipe_disappears_midway(tmp_path, monkeypatch, gate_pass):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "base.yaml").write_text(yaml.safe_dump(_BASE_RECIPE),
                                        encoding="utf-8")
    (tmp_path / "cases.yaml").write_text(
        "base_recipe: base.yaml\nmatrix: {t: [50]}\n", encoding="utf-8")
    plan = svc.plan_sweep(tmp_path / "cases.yaml")
    (tmp_path / "base.yaml").unlink()  # 计划后基配方被移走 → 如实失败
    result = svc.run_sweep(plan, execute_fn=_fake_executor_factory())
    assert not result["ok"]
    assert result["n_failed"] == 1
    assert any("基配方不可读" in e for e in result["cases"][0]["errors"])


def test_run_janitor_recorded_and_nonblocking(cases_dir, monkeypatch, gate_pass):
    plan = svc.plan_sweep(cases_dir / "cases.yaml")
    monkeypatch.setattr(svc, "_janitor_pre_clean",
                        lambda: {"ok": True, "n_suspect_killed_candidates": 0,
                                 "n_lock_candidates": 0, "clean_summary": {},
                                 "clean_errors": []})
    result = svc.run_sweep(plan, janitor=True,
                           execute_fn=_fake_executor_factory())
    assert result["ok"]
    assert result["janitor"]["ok"] is True
    # janitor 自身失败也不阻塞主路径（#105）
    monkeypatch.setattr(svc, "_janitor_pre_clean",
                        lambda: {"ok": False, "errors": ["psutil 缺"]})
    result2 = svc.run_sweep(svc.plan_sweep(cases_dir / "cases.yaml"),
                            janitor=True, execute_fn=_fake_executor_factory())
    assert result2["ok"] and result2["janitor"]["ok"] is False


def test_janitor_pre_clean_gates_lock_removal_by_owner(cases_dir, monkeypatch):
    """K20/R4 P2：自动路径只清 owner_dead 锁；活属主/判不了锁保留（WARN 记账）。"""
    import rfauto.service.resource_janitor_service as rj_mod

    lock_entries = [
        {"path": "P:/dead.aedt.lock", "is_dir": False, "mtime": None,
         "paired_project": True},
        {"path": "P:/alive.aedt.lock", "is_dir": False, "mtime": None,
         "paired_project": True},
        {"path": "P:/mystery.lock", "is_dir": False, "mtime": None,
         "paired_project": False},
    ]
    monkeypatch.setattr(
        rj_mod, "janitor_scan",
        lambda **kw: {"ok": True, "processes": [], "locks": lock_entries,
                      "summary": {}})
    verdict_by_path = {
        "P:/dead.aedt.lock": "owner_dead",
        "P:/alive.aedt.lock": "owner_alive",
        "P:/mystery.lock": "undetermined",
    }
    monkeypatch.setattr(
        rj_mod, "lock_owner_verdict",
        lambda p, **kw: {"verdict": verdict_by_path[str(p)], "pid": 4242,
                         "process_path": "E:/x/ansysedt.exe", "reason": "r"})
    calls: list[dict] = []

    def fake_clean(*, kill_pids, locks, dry_run, scan_roots=None):
        calls.append({"kill_pids": list(kill_pids), "locks": list(locks),
                      "dry_run": dry_run})
        return {"ok": True, "summary": {"dry_run": dry_run, "n_actions": 0,
                                        "n_killed": 0, "n_lock_removed": 0,
                                        "n_already_gone": 0, "n_failed": 0},
                "errors": []}

    monkeypatch.setattr(rj_mod, "janitor_clean", fake_clean)
    report = svc._janitor_pre_clean()
    assert report["ok"] is True
    assert report["n_lock_candidates"] == 3
    assert report["n_lock_owner_alive_skipped"] == 1
    assert report["n_lock_undetermined_skipped"] == 1
    # 两段序：第一段只杀疑似孤儿（零锁），第二段只清 owner_dead 的锁
    assert calls[0] == {"kill_pids": [], "locks": [], "dry_run": False}
    assert calls[1] == {"kill_pids": [], "locks": ["P:/dead.aedt.lock"],
                        "dry_run": False}
    assert [s["path"] for s in report["skipped_owner_alive"]] == \
        ["P:/alive.aedt.lock"]
    assert report["skipped_undetermined"][0]["path"] == "P:/mystery.lock"
    assert report["skipped_undetermined"][0]["reason"]
    assert report["warnings"] and "保留" in report["warnings"][0]
    # 活会话锁的 WARN 记账随 run_sweep 信封透传（不翻转 ok）
    monkeypatch.setattr("rfauto.service.resource_janitor_service.memory_gate",
                        _gate_ok)
    monkeypatch.setattr(svc, "_janitor_pre_clean",
                        lambda: dict(report))
    result = svc.run_sweep(svc.plan_sweep(cases_dir / "cases.yaml"), janitor=True,
                           execute_fn=_fake_executor_factory())
    assert result["ok"] and result["janitor"]["n_lock_owner_alive_skipped"] == 1


# ── summarize：行数/指标/missing/落盘 ───────────────────────────────────────


def test_summarize_rows_metrics_and_missing(cases_dir, gate_pass):
    plan = svc.plan_sweep(cases_dir / "cases.yaml")
    result = svc.run_sweep(plan, execute_fn=_fake_executor_factory())
    assert result["ok"]
    summary = svc.summarize_sweep(plan)
    assert summary["ok"], summary.get("errors")
    assert summary["n_rows"] == 16 and summary["n_done_rows"] == 16
    by_id = {r["case_id"]: r for r in summary["rows"]}
    row = by_id["ind-v5-200"]
    assert row["status"] == "done"
    assert row["device"] == "ind" and row["thickness"] == "200"
    assert row["L_nh"] == pytest.approx(4.2 + 200 / 1000.0)
    assert row["cost"] == pytest.approx(0.1)
    # K8 面现场提取：合成已知量逐位回收（#340 家法；c_series_f 单位=fF）
    assert row["em.c_series_f"] == pytest.approx(_C_DUT * 1e15, rel=1e-6)
    assert row["em.r_series_ohm"] == pytest.approx(_R_DUT, rel=1e-6)
    assert summary["missing"] == []
    # 落盘产物
    csv_path = Path(summary["summary_csv"])
    json_path = Path(summary["summary_json"])
    assert csv_path.is_file() and json_path.is_file()
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 17  # 表头 + 16 行
    header = lines[0].split(",")
    assert header[0] == "case_id" and "status" in header
    assert "L_nh" in header and "em.c_series_f" in header
    assert header[-1] == "run_dir"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["n_rows"] == 16 and len(data["rows"]) == 16
    assert any("对比图暂未提供" in n for n in data["notes"])


def test_summarize_missing_honest_for_unexecuted(cases_dir):
    plan = svc.plan_sweep(cases_dir / "cases.yaml")
    summary = svc.summarize_sweep(plan)
    assert summary["ok"]
    assert summary["n_rows"] == 16 and summary["n_done_rows"] == 0
    assert len(summary["missing"]) == 16
    assert any("case.json 账本缺失" in m
               for m in summary["missing"][0]["missing"])


def test_summarize_touchstone_missing_listed(cases_dir, gate_pass):
    plan = svc.plan_sweep(cases_dir / "cases.yaml")
    result = svc.run_sweep(
        plan, execute_fn=_fake_executor_factory(touchstone=False))
    assert result["ok"]
    summary = svc.summarize_sweep(plan)
    flat = [m for entry in summary["missing"] for m in entry["missing"]]
    assert flat and all("Touchstone 补充提取" in m for m in flat)
    assert summary["rows"][0].get("em.c_series_f") is None
    assert summary["rows"][0]["L_nh"] == pytest.approx(
        4.2 + 200 / 1000.0)  # metrics.json 主口径不受影响


# ── CLI 冒烟（--json 信封+退出码；dry-run；失败面） ─────────────────────────


def _cli_invoke(argv: list[str]):
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    return CliRunner().invoke(app, argv)


def test_cli_sweep_json_success(cases_dir, monkeypatch, gate_pass):
    monkeypatch.setattr(svc, "_default_case_executor", _fake_executor_factory())
    cases_small = cases_dir / "small.yaml"
    cases_small.write_text(
        "base_recipe: base.yaml\nadapter: fake\nmatrix:\n"
        "  device: [ind, idc]\n  thickness: [200, 50]\n"
        "axis_key: {thickness: sub_t_um}\n", encoding="utf-8")
    proc = _cli_invoke(["em", "sweep", str(cases_small), "--json"])
    assert proc.exit_code == 0, proc.output
    payload = json.loads(proc.output)
    assert payload["ok"] and payload["n_cases"] == 4
    assert payload["n_done"] == 4 and payload["n_failed"] == 0
    assert payload["summary"]["ok"] and payload["summary"]["n_rows"] == 4


def test_cli_sweep_dry_run_and_resume_flags(cases_dir, monkeypatch):
    monkeypatch.setattr(svc, "_default_case_executor",
                        _fake_executor_factory(counter={"n": 0}))
    proc = _cli_invoke(["em", "sweep", str(cases_dir / "cases.yaml"),
                        "--dry-run", "--resume", "--janitor", "--json"])
    assert proc.exit_code == 0, proc.output
    payload = json.loads(proc.output)
    assert payload["ok"] and payload["verdict"] == "DRY_RUN"
    assert payload["n_cases"] == 16 and payload["janitor"] is True
    assert "summary" not in payload  # dry-run 不汇总


def test_cli_sweep_failures(cases_dir, monkeypatch, gate_pass):
    missing = _cli_invoke(["em", "sweep", "nope.yaml", "--json"])
    assert missing.exit_code == 1
    assert json.loads(missing.output)["ok"] is False
    parallel = _cli_invoke(["em", "sweep", str(cases_dir / "cases.yaml"),
                            "--max-aedt", "4", "--json"])
    assert parallel.exit_code == 1
    assert any("串行" in e for e in json.loads(parallel.output)["errors"])
    monkeypatch.setattr(svc, "_default_case_executor", _fake_executor_factory())
    (cases_dir / "bad.yaml").write_text(
        "base_recipe: base.yaml\nmatrix: {t: [1]}\nadapter: qucs\n",
        encoding="utf-8")
    bad = _cli_invoke(["em", "sweep", str(cases_dir / "bad.yaml"), "--json"])
    assert bad.exit_code == 1
    assert any("hfss|fake" in e for e in json.loads(bad.output)["errors"])


def test_cli_sweep_human_face(cases_dir, monkeypatch, gate_pass):
    monkeypatch.setattr(svc, "_default_case_executor", _fake_executor_factory())
    (cases_dir / "small.yaml").write_text(
        "base_recipe: base.yaml\nadapter: fake\nmatrix: {t: [50]}\n",
        encoding="utf-8")
    proc = _cli_invoke(["em", "sweep", str(cases_dir / "small.yaml")])
    assert proc.exit_code == 0, proc.output
    assert "done=1" in proc.output and "summary.csv" in proc.output

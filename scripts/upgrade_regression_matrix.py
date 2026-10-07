"""Z-16 升级回归矩阵（EC-12 前置锚快检）——openEMS 引擎升级回归的一键基线。

三段（全部离线/秒级，零真机零长跑，判据=时间盒 30min 内跑完）：
  A 锚段：openEMS 依赖锚（knowledge/anchors.yaml 中 engine_pair 含 openems
    的锚）注册表离线体检（状态/字段/消费者路径/常量值有限性）+ 锚消费
    测试（pytest 定向：锚存储面 + openems_templates 桥面）；
  B 模板冒烟段：openEMS 模板 CSXCAD 离线 exec 级测试（渲染→exec 几何段
    实测带宽/连通性，秒级零仿真，#212 制度化面）；
  C 内核段：确定性内核抽样对拍（内置 golden 值——计算器注册表两键在
    固定输入下的期望输出）+ 计算器注册表/物理不变量定向测试。
真机档：openEMS 依赖锚的数值复验需真机求解，逐锚列清单（tier=real-machine、
run_policy=manual、verify_entry=登记的 referee_script/消费者），缺省不执行、
不计退出码——EC-12 升级后由执行席按需发射并对照本基线。

EC-12 用法：升级前跑一遍基线（--out 落 JSON）；升级后重跑同命令，逐项
对照 pass/fail 漂移；红项即升级回归面。

用法（venv python，仓根执行）：
  python scripts/upgrade_regression_matrix.py --list
  python scripts/upgrade_regression_matrix.py
  python scripts/upgrade_regression_matrix.py --out runs/w2_phase2/z16_baseline.json \
      --log runs/w2_phase2/z16_baseline.log

退出码：0 全绿（skip 如实计数不红）；1 有红；2 装配错误（repo 根缺失/
锚注册表不可读）。
#242 门命令纪律：pytest 输出全部落日志文件，读日志文件取摘要，不走管道
tail（stdout 256KB cap 会把门变成链路异常）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

#: openEMS 锚注册表（单源：knowledge/anchors.yaml，core/anchors.py 计数面）。
ANCHORS_YAML = REPO_ROOT / "knowledge" / "anchors.yaml"

#: B 段：openEMS 模板 CSXCAD 离线 exec 冒烟集（conftest _CSXCAD_TEST_MODULES
#: 子集，跨族代表抽样：ratrace/hairpin 同向+交替/combline/interdigital/
#: gysel/slotline/siw/coupled_bpf/cps/msl_cpw/几何审计/桥面）。
TEMPLATE_SMOKE_FILES: tuple[str, ...] = (
    "tests/unit/test_ratrace_template.py",
    "tests/unit/test_template_geometry_audit.py",
    "tests/unit/test_hairpin_template.py",
    "tests/unit/test_hairpin_alt_template.py",
    "tests/unit/test_combline_template.py",
    "tests/unit/test_interdigital_template.py",
    "tests/unit/test_gysel_template.py",
    "tests/unit/test_slotline_template.py",
    "tests/unit/test_siw_template.py",
    "tests/unit/test_coupled_bpf_template.py",
    "tests/unit/test_cps_template.py",
    "tests/unit/test_msl_cpw_template.py",
    "tests/unit/test_openems_templates_bridge.py",
)

#: C 段：确定性内核定向测试（注册表一致性与逐键物理不变量）。
KERNEL_TEST_FILES: tuple[str, ...] = (
    "tests/unit/test_calculators.py",
    "tests/unit/test_physics_invariants.py",
)

#: A 段：锚消费测试（锚存储面 + openems_templates 锚修正消费面）。
ANCHOR_TEST_FILES: tuple[str, ...] = (
    "tests/unit/test_anchors_store_service.py",
    "tests/unit/test_openems_templates_bridge.py",
)

#: C 段抽样对拍 golden（当前 vendor 实测钉值；升级后漂移即红）。
_CALC_GOLDEN: tuple[dict[str, Any], ...] = (
    {
        "calculator": "attenuator_pi",
        "params": {"attenuation_db": 20.0, "z0_ohm": 50.0},
        "expect": {"r_series_mid_ohm": 247.5, "r_shunt_end_ohm": 61.111},
        "tol": {"r_series_mid_ohm": 1e-6, "r_shunt_end_ohm": 1e-3},
    },
    {
        "calculator": "chebyshev_prototype",
        "params": {"order": 3, "rl_db": 20.0},
        "expect": {"epsilon": 0.100503782,
                   "reflection_zeros": [-0.866025404, 0.0, 0.866025404]},
        "tol": {"epsilon": 1e-8, "reflection_zeros": 1e-8},
    },
)


def csxcad_available() -> bool:
    """CSXCAD 绑定在位性（B 段门；缺装 → 对应项如实 skip 不红）。"""
    return importlib.util.find_spec("CSXCAD") is not None


def openems_anchor_ids() -> list[str]:
    """engine_pair 含 openems 的锚 id 清单（读锚注册表；不可读 → 空表）。"""
    try:
        import yaml

        data = yaml.safe_load(ANCHORS_YAML.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    out: list[str] = []
    for a in data.get("anchors") or []:
        if not isinstance(a, dict):
            continue
        pair = a.get("engine_pair") or {}
        engines = f"{pair.get('calibrated') or ''} {pair.get('referee') or ''}"
        if "openems" in engines and a.get("anchor_id"):
            out.append(str(a["anchor_id"]))
    return out


def build_matrix() -> list[dict[str, Any]]:
    """矩阵清单（确定性；--list 与执行同源）。"""
    items: list[dict[str, Any]] = [
        {"id": "anchors.registry.offline", "section": "A", "tier": "offline",
         "kind": "inline",
         "desc": "openEMS 依赖锚注册表离线体检（状态/字段/消费者路径/值有限性）"},
    ]
    for f in ANCHOR_TEST_FILES:
        items.append({"id": f"anchors.tests.{Path(f).stem}", "section": "A",
                      "tier": "offline", "kind": "pytest", "target": f,
                      "requires_csxcad": "bridge" in Path(f).stem,
                      "desc": "锚消费测试（定向 pytest）"})
    for f in TEMPLATE_SMOKE_FILES:
        items.append({"id": f"templates.smoke.{Path(f).stem}", "section": "B",
                      "tier": "offline", "kind": "pytest", "target": f,
                      "requires_csxcad": True,
                      "desc": "openEMS 模板 CSXCAD 离线 exec 冒烟（零仿真）"})
    for f in KERNEL_TEST_FILES:
        items.append({"id": f"kernel.tests.{Path(f).stem}", "section": "C",
                      "tier": "offline", "kind": "pytest", "target": f,
                      "requires_csxcad": False,
                      "desc": "确定性内核定向测试"})
    items.append({"id": "kernel.sampling.golden", "section": "C",
                  "tier": "offline", "kind": "inline",
                  "desc": "计算器注册表抽样对拍（内置 golden 值）"})
    for anchor_id in openems_anchor_ids():
        items.append({"id": f"anchors.real-machine.{anchor_id}",
                      "section": "A", "tier": "real-machine",
                      "kind": "manual", "target": anchor_id,
                      "desc": "锚数值复验需真机求解（EC-12 执行席按需发射，"
                              "缺省不执行不计退出码）"})
    return items


def check_anchors_registry() -> dict[str, Any]:
    """A 段内联体检：openEMS 依赖锚注册表结构与指向面（离线秒级）。"""
    import math

    import yaml

    problems: list[str] = []
    data = yaml.safe_load(ANCHORS_YAML.read_text(encoding="utf-8")) or {}
    anchors = data.get("anchors") or []
    targets: list[dict[str, Any]] = []
    for a in anchors:
        if not isinstance(a, dict):
            continue
        pair = a.get("engine_pair") or {}
        engines = f"{pair.get('calibrated') or ''} {pair.get('referee') or ''}"
        if "openems" not in engines:
            continue
        aid = str(a.get("anchor_id") or "")
        targets.append({"anchor_id": aid, "status": a.get("status"),
                        "kind": a.get("kind")})
        if not aid:
            problems.append("锚缺 anchor_id")
            continue
        if a.get("status") == "retired":
            problems.append(f"{aid}: retired 锚混入现役集")
        q = a.get("quantity") or {}
        if not q.get("name"):
            problems.append(f"{aid}: 缺 quantity.name")
        for key in ("referee_script",):
            ref = (a.get("provenance") or {}).get(key)
            if ref and not (REPO_ROOT / ref).is_file():
                problems.append(f"{aid}: {key} 不存在: {ref}")
        for cons in a.get("consumers") or []:
            if not (REPO_ROOT / str(cons)).is_file():
                problems.append(f"{aid}: consumer 不存在: {cons}")
        if a.get("kind") == "constant":
            v = a.get("value")
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                problems.append(f"{aid}: constant 锚值非有限数值: {v!r}")
    return {"n_openems_anchors": len(targets), "targets": targets,
            "problems": problems, "ok": not problems and bool(targets)}


def check_calc_sampling() -> dict[str, Any]:
    """C 段内联抽样对拍：注册表计算器固定输入 vs 内置 golden。"""
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    problems: list[str] = []
    checked: list[dict[str, Any]] = []
    for case in _CALC_GOLDEN:
        name = case["calculator"]
        try:
            out = CALCULATOR_REGISTRY.get(name).func(**case["params"])
        except Exception as exc:
            problems.append(f"{name}: 调用失败 {type(exc).__name__}: {exc}")
            continue
        for key, want in case["expect"].items():
            got = out.get(key)
            tol = case["tol"].get(key, 1e-9)
            if isinstance(want, list):
                if (not isinstance(got, list) or len(got) != len(want)
                        or any(abs(float(g) - float(w)) > tol
                               for g, w in zip(got, want, strict=True))):
                    problems.append(f"{name}.{key}: 期望 {want} 实测 {got}")
                else:
                    checked.append({"key": f"{name}.{key}", "ok": True})
                continue
            if got is None or abs(float(got) - float(want)) > tol:
                problems.append(f"{name}.{key}: 期望 {want} 实测 {got}（tol {tol}）")
            else:
                checked.append({"key": f"{name}.{key}", "ok": True})
    return {"n_checked": len(checked), "problems": problems,
            "ok": not problems and bool(checked)}


def _run_pytest_item(
    item: dict[str, Any], log_fh: Any
) -> dict[str, Any]:
    """定向 pytest 一项：输出落日志文件，读日志尾部摘要（#242 纪律）。"""
    target = str(item["target"])
    log_fh.write(f"\n===== [{item['id']}] pytest {target} =====\n")
    log_fh.flush()
    cmd = [sys.executable, "-m", "pytest", target, "-q", "--tb=line",
           "-p", "no:warnings"]
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                          text=True, timeout=1500)
    wall = time.monotonic() - t0
    log_fh.write(proc.stdout or "")
    if proc.stderr:
        log_fh.write("\n[stderr]\n" + proc.stderr)
    log_fh.flush()
    tail = (proc.stdout or "")[-2000:]
    import re

    m = re.search(r"(\d+) passed(?:,\s*(\d+) skipped)?", tail)
    n_pass = int(m.group(1)) if m else 0
    n_skip = int(m.group(2)) if (m and m.group(2)) else 0
    n_skip += tail.count("skipped")
    if proc.returncode == 0 and n_pass == 0 and n_skip == 0:
        status = "fail"
        reason = "pytest 退出码 0 但无 passed/skipped 摘要（收集失败?）"
    elif proc.returncode != 0:
        status = "fail"
        reason = f"pytest 退出码 {proc.returncode}"
    elif n_pass == 0 and n_skip > 0:
        status = "skip"
        reason = "全 skip（前置不满足，如实计数）"
    else:
        status = "pass"
        reason = ""
    return {"id": item["id"], "tier": item["tier"], "kind": item["kind"],
            "status": status, "exit_code": proc.returncode,
            "n_passed": n_pass, "n_skipped": n_skip, "wall_s": round(wall, 1),
            "reason": reason}


def run_matrix(
    *,
    out_path: Path,
    log_path: Path,
) -> tuple[int, dict[str, Any]]:
    """跑离线档矩阵；返回 (exit_code, baseline_payload)。"""
    if not (REPO_ROOT / "pyproject.toml").is_file():
        print(f"repo 根不存在: {REPO_ROOT}", file=sys.stderr)
        return 2, {}
    matrix = build_matrix()
    has_csxcad = csxcad_available()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    overall = 0
    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"# Z-16 upgrade regression matrix — "
                     f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
                     f"# csxcad_available={has_csxcad}\n")
        for item in matrix:
            if item["tier"] != "offline":
                results.append({"id": item["id"], "tier": item["tier"],
                                "kind": item["kind"], "status": "deferred",
                                "reason": "real-machine 档缺省不执行（run_policy=manual）"})
                continue
            if item.get("requires_csxcad") and not has_csxcad:
                results.append({"id": item["id"], "tier": item["tier"],
                                "kind": item["kind"], "status": "skip",
                                "reason": "CSXCAD 绑定缺装（离线 exec 不可用）"})
                continue
            t0 = time.monotonic()
            if item["kind"] == "inline":
                detail = (check_anchors_registry()
                          if item["id"] == "anchors.registry.offline"
                          else check_calc_sampling())
                ok = bool(detail.get("ok"))
                results.append({
                    "id": item["id"], "tier": item["tier"],
                    "kind": item["kind"],
                    "status": "pass" if ok else "fail",
                    "n_checked": detail.get("n_openems_anchors",
                                            detail.get("n_checked")),
                    "problems": detail.get("problems"),
                    "wall_s": round(time.monotonic() - t0, 2),
                    "reason": "" if ok else "; ".join(
                        detail.get("problems") or ["unknown"])})
                log_fh.write(f"\n===== [{item['id']}] inline =====\n"
                             f"{json.dumps(detail, ensure_ascii=False, default=str)}\n")
            else:
                try:
                    results.append(_run_pytest_item(item, log_fh))
                except subprocess.TimeoutExpired:
                    results.append({"id": item["id"], "tier": item["tier"],
                                    "kind": item["kind"], "status": "fail",
                                    "reason": "pytest 超时（1500s）"})
            if results[-1]["status"] == "fail":
                overall = 1
    summary = {
        "n_pass": sum(1 for r in results if r["status"] == "pass"),
        "n_fail": sum(1 for r in results if r["status"] == "fail"),
        "n_skip": sum(1 for r in results if r["status"] == "skip"),
        "n_deferred": sum(1 for r in results if r["status"] == "deferred"),
    }
    verdict = "red" if summary["n_fail"] else (
        "green_with_skips" if summary["n_skip"] else "green")
    payload = {
        "schema": "z16_upgrade_regression_matrix/v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_head": _git_head(),
        "csxcad_available": has_csxcad,
        "matrix": matrix,
        "results": results,
        "summary": summary,
        "verdict": verdict,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                                   default=str), encoding="utf-8")
    return overall, payload


def _git_head() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=30,
                             cwd=str(REPO_ROOT))
        sha = (out.stdout or "").strip()
        return sha if out.returncode == 0 else ""
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Z-16 升级回归矩阵（EC-12 前置锚快检，离线档一键 runner）")
    parser.add_argument("--list", action="store_true",
                        help="只打印矩阵清单 JSON（不执行）")
    parser.add_argument("--out", default=str(
        REPO_ROOT / "runs" / "w2_phase2" / "z16_baseline.json"),
        help="基线 JSON 落点")
    parser.add_argument("--log", default=str(
        REPO_ROOT / "runs" / "w2_phase2" / "z16_baseline.log"),
        help="门日志落点（#242：pytest 输出全落文件）")
    args = parser.parse_args(argv)

    if args.list:
        print(json.dumps(build_matrix(), ensure_ascii=False, indent=1))
        return 0
    code, payload = run_matrix(out_path=Path(args.out), log_path=Path(args.log))
    if code == 0:
        s = payload.get("summary", {})
        print(f"Z-16 matrix verdict={payload.get('verdict')}  "
              f"pass={s.get('n_pass')} skip={s.get('n_skip')} "
              f"deferred={s.get('n_deferred')}")
        print(f"baseline: {args.out}")
        print(f"log:      {args.log}")
    else:
        print(f"Z-16 matrix exit={code}（1=有红 2=装配错误；详情见 "
              f"{args.log} / {args.out}）", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

"""WP3.5 M4 自验证环真机联调薄驱动（openems-real-smoke-bundle ⑥）。

等价 `rfauto autotune runs/kicad_b6_stage2/b6_autotune_recipe.yaml --self-verify
--budget 3 --mesh 1.0 --mesh-fine 0.5 --json`：直调
service.autotune_service.self_verify_loop（缺省粗→细双采样器
autotune_service.py:617-626，均为 openEMS 真机），零源码改动。0bq③ 自述此前
仅 fake sampler 验证，本脚本补真机联调。

验收（如实）：M1..M5 状态原样（passed/failed/skipped）；M4 detail 含粗/细 cost
且判据 fine ≤ coarse_best×(1+fine_epsilon)（:857）——脚本按 history 独立复算并与
M4 status 对账；runs/loop_boards/<board_id>.json 与 runs/<run_id>/autotune.json
落盘；M5 仅沙箱草稿（runs/recipe_sandbox/）不 promote——配方文件哈希前后不变
（采样纪律）；活跑检测（采样器工作目录 pt_*/fdtd/），全为缓存回放则 PARTIAL。

产物 runs/<run_id>/autotune.json（服务落盘）+ runs/selfverify_m4_real/_smoke_result.json。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from rfauto.service.autotune_service import self_verify_loop

RECIPE = "runs/kicad_b6_stage2/b6_autotune_recipe.yaml"
OUT = Path("runs/selfverify_m4_real")
_RE_M4 = re.compile(r"fine cost ([0-9.eE+-]+) vs coarse best ([0-9.eE+-]+)")


def m4_consistency(history: list[dict], milestones: list[dict],
                   fine_epsilon: float) -> dict[str, object]:
    """按 history 独立复算 M4 判据并与里程碑状态对账（纯数学，离线可测）。"""
    coarse = [h for h in history if h.get("phase") == "coarse" and h.get("metrics") is not None
              and isinstance(h.get("cost"), (int, float))]
    fine = [h for h in history if h.get("phase") == "fine" and isinstance(h.get("cost"), (int, float))]
    m4 = next((m for m in milestones if m.get("id") == "M4"), None)
    out: dict[str, object] = {"m4_status": m4.get("status") if m4 else None,
                              "m4_detail": m4.get("detail") if m4 else None}
    if not coarse or not fine or m4 is None:
        out["consistent"] = None
        out["note"] = "缺粗/细评估记录或 M4 里程碑，无法复算"
        return out
    coarse_best = min(float(h["cost"]) for h in coarse)
    fine_cost = float(fine[-1]["cost"])
    expect_pass = fine_cost <= coarse_best * (1 + fine_epsilon) + 1e-9
    out.update({"coarse_best_cost": coarse_best, "fine_cost": fine_cost,
                "fine_epsilon": fine_epsilon, "expect_pass": expect_pass})
    detail_ok = None
    if m4.get("detail"):
        mm = _RE_M4.search(str(m4["detail"]))
        if mm:
            detail_ok = (abs(float(mm.group(1)) - fine_cost) <= 1e-6 * max(1.0, abs(fine_cost))
                         and abs(float(mm.group(2)) - coarse_best) <= 1e-6 * max(1.0, abs(coarse_best)))
    out["detail_numbers_match"] = detail_ok
    out["consistent"] = bool((m4["status"] == "passed") == expect_pass and detail_ok is not False)
    return out


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", default=RECIPE)
    parser.add_argument("--budget", type=int, default=3)
    parser.add_argument("--mesh", type=float, default=1.0)
    parser.add_argument("--mesh-fine", type=float, default=0.5)
    parser.add_argument("--fine-epsilon", type=float, default=0.2)
    args = parser.parse_args(argv)

    recipe_path = Path(args.recipe)
    sha_before = _sha(recipe_path)
    before = set(glob.glob("runs/autotune_work_*"))
    t0 = time.time()
    sv = self_verify_loop(args.recipe, budget_coarse=args.budget,
                          mesh_coarse_mm=args.mesh, mesh_fine_mm=args.mesh_fine,
                          fine_epsilon=args.fine_epsilon, sandbox=True, board=True)
    wall = time.time() - t0
    assert sv.get("ok"), sv.get("errors")
    sha_after = _sha(recipe_path)

    history = list(sv.get("history") or [])
    milestones = list(sv.get("milestones") or [])
    status = {m["id"]: m["status"] for m in milestones}
    work_dirs = sorted(set(glob.glob("runs/autotune_work_*")) - before)
    pt_dirs = sorted(p for w in work_dirs for p in glob.glob(f"{w}/pt_*"))
    live = [p for p in pt_dirs if Path(p, "fdtd").is_dir()]
    m4c = m4_consistency(history, milestones, args.fine_epsilon)

    run_dir = Path(str(sv.get("run_dir") or ""))
    autotune_json = run_dir / "autotune.json"
    board_id = sv.get("board_id")
    board_json = Path("runs") / "loop_boards" / f"{board_id}.json" if board_id else None
    sandbox = sv.get("sandbox") or {}
    draft = str(sandbox.get("draft") or "")

    gates = {
        "loop_verdict": {"value": sv.get("verdict"), "ok": sv.get("verdict") == "PASS"},
        "milestones": {"value": status,
                       "ok": all(v in ("passed", "skipped") for v in status.values())},
        "m4_passed": {"value": status.get("M4"), "ok": status.get("M4") == "passed"},
        "m4_consistency": {"value": m4c, "ok": bool(m4c.get("consistent"))},
        "autotune_json": {"value": str(autotune_json), "ok": autotune_json.exists()},
        "loop_board_json": {"value": str(board_json), "ok": bool(board_json and board_json.exists())},
        "m5_sandbox_only": {"value": {"draft": draft, "sandbox_ok": sandbox.get("ok")},
                            "ok": bool(sandbox.get("ok")) and "recipe_sandbox" in draft.replace("\\", "/")
                            and sha_before == sha_after},
        "live_engine_runs": {"value": len(live), "of": len(pt_dirs), "ok": len(live) >= 2},
    }
    core = all(gates[k]["ok"] for k in ("loop_verdict", "milestones", "m4_passed", "m4_consistency",
                                        "autotune_json", "loop_board_json", "m5_sandbox_only"))
    verdict = "PASS" if core and gates["live_engine_runs"]["ok"] else ("PARTIAL" if core else "FAIL")

    print(f"self_verify verdict={sv.get('verdict')} rounds={sv.get('rounds_used')} run_id={sv.get('run_id')} "
          f"board={board_id} wall={wall:.0f}s live={len(live)}/{len(pt_dirs)}")
    for m in milestones:
        print(f"  {m['id']} {m['status']:<8} {m['name']}：{m.get('detail')}")
    print("M4 复算:", json.dumps(m4c, ensure_ascii=False))
    print(f"SELFVERIFY_M4_REAL_{verdict}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    result = {
        "item": "openems-real-smoke-bundle/⑥selfverify_m4_real", "verdict": verdict,
        "equivalent_cli": (f"rfauto autotune {args.recipe} --self-verify --budget {args.budget} "
                           f"--mesh {args.mesh} --mesh-fine {args.mesh_fine} --json"),
        "self_verify": {k: sv.get(k) for k in ("run_id", "run_dir", "board_id", "verdict", "loop",
                                               "proposer_note", "budget_coarse", "rounds_used",
                                               "best", "final_params", "elapsed_s")},
        "milestones": milestones, "history": history, "sandbox": sandbox,
        "wall_s": round(wall, 1), "work_dirs": work_dirs, "live_engine_pt_dirs": live,
        "recipe_sha256_before": sha_before, "recipe_sha256_after": sha_after,
        "gates": gates,
    }
    (OUT / "_smoke_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

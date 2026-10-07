"""EC-20 #300 合法化：ms_cross/ms_jcross PSSFSS 仓内可复跑裁判（W2-F）。

背景（#300）：metasurface 模板 meta 的判读口径「J3 vs PSSFSS Δf≤0.3GHz 或
≤5%」（render_metasurface.py:1122/:1156）此前依赖**外部文献值**；本脚本把
PSSFSS 侧判读升级为仓内可复跑——adapter 面（adapters/pssfss_adapter.py）
真跑单胞 Floquet S 参数 → 纯函数估计器取谷/峰位 → 预声明门判读 → verdict
落盘。几何/读出口径与归档参考链逐构造参数同源（runs/dp10_j2j3/
judge_pssfss.jl，ge6 锚 ms_cross.wg_resonance.openems-hfss-v1；Floquet
无限阵裁判参考值 2026-10-07 真形重锚为 11.4265GHz——旧 10.152 系哨兵形
读数证伪作废，见 pssfss_adapter.MS_CROSS_PSSFSS_REF_GHZ 注记）。

判据（预声明，SPECS §3.3；发射前冻结于 runs/w2_phase2/criteria.md W2-F）：
1. ms_cross：pypssfss 复算谷位 vs PSSFSS 参考值 11.4265GHz，|Δf| ≤1%
   （文献回收钉，#118 家法）；旁证=双极化谷位同频 + EC 设计值
   （半波口径 ms_cross_arm_len_mm）量级互证。
2. ms_jcross：pypssfss 复算峰位 vs 设计带心 f0=10GHz：Δf ≤0.3GHz **或**
   ≤5%（render_metasurface.py:1156 原门，首次仓内可复跑）；MoM 确定性
   ⇒ 同几何两次跑逐位一致（判分一致性自检）。
3. HFSS Floquet 终裁（|Δ|≤2-3%）归 scripts/hfss_floquet_anchor.py 通道
   （真机另计窗），不在本脚本。

用法（工作区根目录）::

    .venv/Scripts/python.exe scripts/pssfss_ms_judge.py --template ms_cross
    .venv/Scripts/python.exe scripts/pssfss_ms_judge.py --template ms_jcross
    .venv/Scripts/python.exe scripts/pssfss_ms_judge.py --judge-only <dir>
    .venv/Scripts/python.exe scripts/pssfss_ms_judge.py --template ms_cross \
        --params-json "{\"arm_len_mm\": 5.2}"

退出码：0=执行完成且 verdict 落盘（verdict 是裁决数据，判读 FAIL 不算
执行失败，#225 口径）；1=执行 FAIL（fail-closed）；2=SKIP（缺 pypssfss）。
依赖：pypssfss（pip install rfauto[pssfss]；首次 use 自动装 Julia，depot
钉 E:\\julia_depot 由 adapter 面 ensure_julia_depot_env 显式设）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from rfauto.adapters.em_solver_base import (  # noqa: E402
    EMSolverConfig,
    EMSolverType,
    get_global_registry,
)
from rfauto.adapters.pssfss_adapter import (  # noqa: E402
    MS_CROSS_GATE_REL,
    MS_CROSS_PSSFSS_REF_GHZ,
    MS_JCROSS_GATE_ABS_GHZ,
    MS_JCROSS_GATE_REL,
    PssfssAdapter,
    is_pypssfss_installed,
    judge_ms_cross,
    judge_ms_jcross,
    valley_f_ghz,
)

#: EC 设计值互证（#118 双源第二源；量级口径，非绝对门）——闭式单源在
#: core/metasurface_lut（禁手抄毫米数 #1c）。
_MS_TEMPLATES = ("ms_cross", "ms_jcross")


def _ec_design_f0_ghz(template: str, params: dict[str, Any]) -> float | None:
    """模板设计带心（EC 初值口径；meta f0_ghz 同源）。"""
    from rfauto.adapters.oe_templates.registry import TEMPLATE_META

    meta = TEMPLATE_META.get(template) or {}
    f0 = meta.get("f0_ghz")
    return float(f0) if f0 is not None else None


def run_solve(template: str, params_json: str | None, out_dir: Path,
              n_freq: int, fast_sweep: bool) -> dict[str, Any]:
    """adapter 面真跑单胞 → 产物落 out_dir → 返回 meta。"""
    reg = get_global_registry()
    if not reg.is_registered(EMSolverType.PSSFSS):
        reg.register(EMSolverType.PSSFSS, PssfssAdapter)
    geometry: dict[str, Any] = {"template": template,
                                "freq_start_ghz": 7.0, "freq_stop_ghz": 12.0,
                                "n_freq": n_freq, "fast_sweep": fast_sweep}
    if params_json:
        geometry["params"] = json.loads(params_json)
    config = EMSolverConfig(solver_type=EMSolverType.PSSFSS,
                            working_dir=str(out_dir))
    adapter = reg.create(EMSolverType.PSSFSS, config)
    if not isinstance(adapter, PssfssAdapter):
        adapter = PssfssAdapter(config)
    if not adapter.is_available():
        raise RuntimeError("pypssfss 缺装（pip install rfauto[pssfss]）")
    if not adapter.connect():
        raise RuntimeError("pypssfss connect 失败（见日志）")
    if not adapter.build_geometry(geometry):
        raise RuntimeError(f"geometry 拒绝：{adapter._last_error}")
    result = adapter.solve()
    if not result.success:
        raise RuntimeError(f"solve 失败：{result.message}")
    meta = adapter.get_meta()
    assert meta is not None
    adapter.close()
    return meta


def judge_from_products(meta_path: Path) -> dict[str, Any]:
    """从 pssfss_meta.json 离线判读（--judge-only；确定性纯函数面）。"""
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return build_verdict(meta)


def build_verdict(meta: dict[str, Any]) -> dict[str, Any]:
    """meta → verdict（判读面；谷/峰估计器与门=adapter 纯函数单源）。"""
    template = meta["template"]
    extremum = meta["extremum"]
    f_res = float(extremum["f_ghz_refined"]
                  or extremum["f_ghz"])
    verdict: dict[str, Any] = {
        "schema": "rfauto-pssfss-judge/v1",
        "template": template,
        "f_res_ghz": f_res,
        "extremum": extremum,
        "gates": {"ms_cross": {"ref_f_ghz": MS_CROSS_PSSFSS_REF_GHZ,
                               "gate_rel": MS_CROSS_GATE_REL},
                  "ms_jcross": {"gate_abs_ghz": MS_JCROSS_GATE_ABS_GHZ,
                                "gate_rel": MS_JCROSS_GATE_REL,
                                "source": "render_metasurface.py:1156 原门"}},
        "engine": meta.get("engine"),
        "params_echo": meta.get("params_echo"),
        "fast_sweep_effective": meta.get("fast_sweep_effective"),
        "judge_script": "scripts/pssfss_ms_judge.py",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    # 双极化谷位同频旁证（ms_cross：judge :40-41 判读极化不敏感）
    s21_ortho = meta.get("polarizations", {}).get("s21_db_ortho")
    if s21_ortho:
        f_ghz = np.asarray(meta["freqs_ghz"], dtype=float)
        ortho = valley_f_ghz(f_ghz, np.asarray(s21_db_to_arr(s21_ortho)))
        verdict["ortho_pol_crosscheck"] = ortho
        verdict["ortho_valley_shift_ghz"] = abs(
            float(ortho["f_ghz_refined"] or ortho["f_ghz"]) - f_res)
    if template == "ms_cross":
        verdict["gate_verdict"] = judge_ms_cross(f_res)
    elif template == "ms_jcross":
        f0 = _ec_design_f0_ghz(template, meta.get("params_echo") or {})
        verdict["gate_verdict"] = judge_ms_jcross(
            f_res, f0_ghz=f0 if f0 is not None else 10.0)
    else:
        verdict["gate_verdict"] = {"verdict": "N/A",
                                   "note": f"{template} 无预声明判读门"}
    return verdict


def s21_db_to_arr(s21_db: list[float]) -> np.ndarray:
    return np.asarray(s21_db, dtype=float)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--template", choices=_MS_TEMPLATES, default=None,
                    help="真跑模板（与 --judge-only 二选一）")
    ap.add_argument("--params-json", default=None,
                    help="可选参数覆盖（mm 口径 JSON，缺省模板名义）")
    ap.add_argument("--judge-only", default=None,
                    help="离线判读既有产物目录（读 pssfss_meta.json）")
    ap.add_argument("--out", default=None,
                    help="产物目录（缺省 runs/w2_phase2/w2f/judge_<t>_<ts>）")
    ap.add_argument("--n-freq", type=int, default=101)
    ap.add_argument("--no-fast-sweep", action="store_true",
                    help="关快扫档（密频点直算对照）")
    args = ap.parse_args(argv)

    if args.judge_only:
        meta_path = Path(args.judge_only) / "pssfss_meta.json"
        if not meta_path.is_file():
            print(f"JUDGE_SKIP: {meta_path} 不存在", file=sys.stderr)
            return 2
        verdict = judge_from_products(meta_path)
        out = Path(args.judge_only) / "verdict.json"
        out.write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print("VERDICT", json.dumps(verdict["gate_verdict"],
                                    ensure_ascii=False))
        print("verdict ->", out)
        return 0

    if args.template is None:
        ap.error("需要 --template 或 --judge-only")
    if not is_pypssfss_installed():
        print("JUDGE_SKIP: pypssfss 缺装（pip install rfauto[pssfss]）",
              file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else (
        REPO / "runs" / "w2_phase2" / "w2f"
        / f"judge_{args.template}_{time.strftime('%Y%m%d_%H%M%S')}")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        meta = run_solve(args.template, args.params_json, out_dir,
                         args.n_freq, not args.no_fast_sweep)
    except RuntimeError as exc:
        print(f"JUDGE_FAIL: {exc}", file=sys.stderr)
        return 1
    verdict = build_verdict(meta)
    (out_dir / "verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
    print("VERDICT", json.dumps(verdict["gate_verdict"], ensure_ascii=False))
    print("products ->", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

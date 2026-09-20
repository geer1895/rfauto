"""D13：S 参数宏模型全链 demo（真实归档 → VF 拟合 → 无源性 → SPICE → FSV → 第三方 xval）。

用法（工作区根目录）：
    .venv/Scripts/python.exe scripts/macromodel_demo.py

真实归档（运行期先核查存在性，缺失即硬失败并给出路径）：
- runs/ratrace_arbitration/hfss_ratrace.s4p（HFSS 四端口环形电桥）
- runs/patch_hfss_probe/probe.s1p（HFSS patch 单端口探针）

产物：runs/macromodel/<stem>.json（完整宏模型结果，JSON 原生，含 spice_xval
段）+ runs/macromodel/<stem>.sp（SPICE 子电路）+ runs/macromodel/<stem>_xval/
（ngspice deck/wrdata 工件），stdout 打印 RMS/无源性/FSV 等级/对拍结果。

两条验证证据链（措辞必须区分，同 src/rfauto/core/macromodel.py 模块 docstring）：
- **回放自检（replay-selfcheck）**：``spice_replay`` 段由本仓纯 Python 复数
  MNA（AC）求解导出网表——它验证"导出网表在标准 SPICE 元素语义下重现模型/
  原始 S 参数"，**不是**第三方 SPICE 仿真器的等价验证；
- **第三方对拍（third-party xval）**：``spice_xval`` 段把同一子电路经
  adapters 层的 ngspice .AC 通道真跑重建 S 矩阵，与原始 S 参数做 D12 FSV
  评级（验收判据：GDM ≥ Good）。ngspice 缺席时 best-effort 跳过（status=
  "skipped"，不炸 demo，#105）；本机 ngspice-47 已装（tools/ngspice）会真跑；
- 保真裁判 = 拟合模型响应 vs 原始 S 参数的 FSV 等级（D12 内核，独立实现）；
- 无源性结论取"数据频带内密集 SVD 直判"（skrf 半尺寸测试的外推段伪违规
  另存 skrf_* 字段），带内违规才触发 passivity_enforce，并如实记录前后 RMS。

数值口径：RMS = 逐响应+逐频点归一化 sqrt(mean|ΔS|²)，dB=20log10；阈值 -40 dB。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.adapters import spice_netlist as sn  # noqa: E402
from rfauto.core.macromodel import fit_macromodel, request_from_touchstone  # noqa: E402

OUT_DIR = REPO / "runs" / "macromodel"

CASES: tuple[tuple[str, Path], ...] = (
    ("ratrace", REPO / "runs" / "ratrace_arbitration" / "hfss_ratrace.s4p"),
    ("patch", REPO / "runs" / "patch_hfss_probe" / "probe.s1p"),
)


def _fmt_bands(bands: list | None) -> str:
    if bands is None:
        return "n/a(skrf 测试失败)"
    if not bands:
        return "none"
    return ",".join(f"[{b[0]:.3e},{'inf' if b[1] is None else format(b[1], '.3e')}]" for b in bands)


def _complex_s_from_request(req: dict) -> np.ndarray:
    """request['s']（[re, im] 对）→ 复数 ndarray [nf, n, n]（原始 S，xval 参考）。"""
    arr = np.asarray(req["s"], dtype=float)
    return arr[..., 0] + 1j * arr[..., 1]


def run_spice_xval(req: dict, spice_path: Path, work_dir: Path) -> dict:
    """第三方 ngspice .AC 对拍（best-effort：缺工具跳过、失败如实记 error，永不抛）。

    与 spice_replay（回放自检）是两条独立证据链；判据 = FSV GDM ≥ Good（方案
    冻结行 D13 验收列）。任何异常都收敛为 status="error"（#105）。
    """
    if not sn.ngspice_available():
        return {
            "status": "skipped",
            "verifier": sn.XVAL_VERIFIER_NGSPICE_AC,
            "reason": "ngspice 不可用（RFAUTO_NGSPICE_BIN / tools/ngspice/Spice64/bin），第三方对拍跳过",
            "gdm_at_least_good": None,
        }
    try:
        return sn.xval_macromodel_spice(
            _complex_s_from_request(req), req["freq_hz"], spice_path, z0=req.get("z0"), work_dir=work_dir
        )
    except Exception as exc:  # xval 本身已 best-effort；此处兜底防 demo 炸
        return {
            "status": "error",
            "verifier": sn.XVAL_VERIFIER_NGSPICE_AC,
            "error": f"{type(exc).__name__}: {exc}",
            "gdm_at_least_good": False,
        }


def _fmt_xval(xval: dict) -> str:
    if xval["status"] == "ok":
        err = xval["xval_vs_reference"]
        rw = xval.get("resistor_rewrite", {})
        return (
            f"status=ok tool={xval['tool'].get('version')} worst GDM={xval['worst_gdm_grade']} "
            f"(response={xval['worst_response']}) >=Good:{xval['gdm_at_least_good']} "
            f"max|dS|={err['max_abs']:.3e} rms={err['rms_db']:.1f}dB "
            f"R<{rw.get('floor_ohm', 0):g}Ω 改写={rw.get('n_rewritten', 0)}"
        )
    if xval["status"] == "skipped":
        return f"status=skipped ({xval['reason']})"
    return f"status=error ({xval.get('error')})"


def main() -> int:
    missing = [str(p) for _, p in CASES if not p.is_file()]
    if missing:
        print("[FAIL] 归档缺失，无法跑 demo：")
        for m in missing:
            print(f"  - {m}")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    for stem, src in CASES:
        req = request_from_touchstone(src)
        spice_path = OUT_DIR / f"{stem}.sp"
        req["spice_path"] = str(spice_path)
        req["subckt_name"] = f"rfauto_{stem}"
        result = fit_macromodel(req)
        # 第三方 ngspice .AC 对拍（best-effort；与回放自检两条证据链并列写进 JSON）
        result["spice_xval"] = run_spice_xval(req, spice_path, OUT_DIR / f"{stem}_xval")
        json_path = OUT_DIR / f"{stem}.json"
        json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

        fit = result["fit"]
        before = result["passivity"]["before"]
        after = result["passivity"]["after"]
        fsv = result["fsv"]
        spice = result["spice"]
        replay = result["spice_replay"] or {}
        xval = result["spice_xval"]
        summaries.append({
            "stem": stem,
            "source": str(src),
            "n_ports": result["n_ports"],
            "n_points": result["n_points"],
            "order": result["order"]["used"],
            "n_poles": result["order"]["n_poles_total"],
            "rms_db": fit["rms_db"],
            "rms_db_final": fit["rms_db_final"],
            "passive_in_band_before": before["passive_in_band"],
            "passive_in_band_after": after["passive_in_band"],
            "sigma_max_in_band_after": after["sigma_max_in_band"],
            "enforced": result["passivity"]["enforced"],
            "spice_valid": spice["valid"],
            "element_counts": spice["element_counts"],
            "worst_gdm_grade": fsv["worst_gdm_grade"],
            "gdm_at_least_good": fsv["gdm_at_least_good"],
            "replay_consistent": replay.get("consistent"),
            "xval_status": xval["status"],
            "xval_gdm": xval.get("worst_gdm_grade"),
            "xval_at_least_good": xval.get("gdm_at_least_good"),
            "ok": result["ok"],
            "json": str(json_path),
            "spice": str(spice_path),
        })

        print(f"=== {stem}  ({src.relative_to(REPO)}) ===")
        print(f"  端口/频点     : {result['n_ports']} / {result['n_points']}")
        print(f"  阶数          : real={result['order']['used']['n_poles_real']} "
              f"cmplx={result['order']['used']['n_poles_cmplx']} (实际极点 {result['order']['n_poles_total']})")
        print(f"  拟合 RMS      : {fit['rms_db']:.1f} dB (阈值 {fit['threshold_db']:.1f}, "
              f"passed={fit['passed']}); 无源化后 {fit['rms_db_final']:.1f} dB (passed={fit['passed_final']})")
        print(f"  无源性(带内)  : before={before['passive_in_band']} (smax={before['sigma_max_in_band']:.6f}) "
              f"-> after={after['passive_in_band']} (smax={after['sigma_max_in_band']:.6f}); "
              f"enforced={result['passivity']['enforced']}")
        print(f"  带内违规频段  : {_fmt_bands(after['violation_bands_in_band_hz'])}")
        print(f"  全轴(skrf)    : passive={after['skrf_passive_full_band']} bands={_fmt_bands(after['skrf_violation_bands_hz'])}")
        print(f"  SPICE         : valid={spice['valid']} elements={spice['element_counts']} -> {spice_path.name}")
        print(f"  FSV 最差 GDM  : {fsv['worst_gdm_grade']} (response={fsv['worst_response']}) "
              f">=Good:{fsv['gdm_at_least_good']}")
        if replay:
            print(f"  回放自检      : status={replay.get('status')} consistent={replay.get('consistent')} "
                  f"(纯 Python MNA，不是第三方仿真)")
        print(f"  第三方对拍    : {_fmt_xval(xval)}")
        print(f"  总判定 ok     : {result['ok']}（不含第三方对拍；对拍结论见 spice_xval 段）")
        print()

    print("---- 汇总 ----")
    for s in summaries:
        print(f"{s['stem']:<8} N={s['n_ports']} rms={s['rms_db']:.1f}dB "
              f"passive={s['passive_in_band_after']} fsv={s['worst_gdm_grade']} ok={s['ok']} "
              f"replay={s['replay_consistent']} xval={s['xval_status']}/{s['xval_gdm']} "
              f"-> {Path(s['json']).name}, {Path(s['spice']).name}")
    print(f"\n产物目录: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

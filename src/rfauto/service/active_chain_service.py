"""有源链路 service（JSON 进出）: LNA 匹配链协同 + PA load-pull 口径。

方案依据: "LNA/PA 匹配网络 EM 提取+ADS
非线性/噪声协同; PA 验收含 ADS 负载牵引仿真口径（谐波平衡 load-pull）"。
验收列: "匹配网络 EM↔ADS 联合 vs 手工口径; load-pull 等增益/等功率圈合理性"。

两个入口（CLI/MCP 薄壳归后续 WP3.3, 本轮只落 service）:
- run_lna_chain: 匹配网络 Touchstone（真机 = HFSS/openEMS EM 导出产物）
  × 器件 S2P → ADS 联合链（ads_runner 可注入, 离线只验管线） vs 手工口径
  （skrf 级联 + core.active_chain 闭式）+ 稳定性 + 噪声口径;
- run_pa_loadpull: Cripps 等功率圈全口径（网格面 + 解析线 + 合理性裁判,
  零仿真离线）, 可选器件 S2P 作恒增益面叠加; ADS HB 逐点通道由
  linkage.render_loadpull_netlist / run_ads_loadpull_point 承载（HB 语法真机实证, 见 linkage.ads_active_chain 模块 docstring）。

数值只在确定性内核（core.active_chain / skrf）; LLM 不产生物理数字。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.active_chain import (
    DEFAULT_Z0,
    HybridPiModel,
    LoadPullDevice,
    gamma_to_z,
    load_pull_plausibility,
    load_pull_scan,
    noise_figure_db,
    simultaneous_conjugate_match,
    stability_margins,
    transducer_gain_db,
)
from rfauto.linkage import ads_active_chain

logger = logging.getLogger(__name__)


def _jsonable(obj: Any) -> Any:
    """dict/ndarray/复数 → 严格 JSON 结构（inf→None, ndarray→list）。

    注意 bool 须先于 int 判定（bool 是 int 子类, 不然 True→1 污染判定段）。
    """
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    if isinstance(obj, (complex, np.complexfloating)):
        return {"re": round(float(obj.real), 9), "im": round(float(obj.imag), 9)}
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if not np.isfinite(f) else round(f, 9)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _sparams_at_f0(snp_path: str | Path, f0_hz: float) -> np.ndarray:
    """读 Touchstone 取最接近 f0 的 2x2 S 矩阵（非 2 端口 ValueError）。"""
    import skrf

    net = skrf.Network(str(snp_path))
    if net.nports != 2:
        raise ValueError(f"期望 2 端口 Touchstone, 得到 {net.nports}: {snp_path}")
    idx = int(np.argmin(np.abs(net.f - f0_hz)))
    return net.s[idx]


def run_lna_chain(
    match_snp: str | Path,
    device_snp: str | Path,
    f0_ghz: float,
    *,
    noise_params: dict[str, float] | None = None,
    ads_dir: str | Path | None = None,
    ads_runner: Any = None,
    tol_db: float = 0.1,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """LNA 匹配链端到端: ADS 联合 vs 手工口径 + 稳定性 + 噪声。

    Args:
        match_snp: 匹配网络 Touchstone（真机 = EM 引擎导出; 2 端口）。
        device_snp: 器件 S2P（2 端口, 与匹配网络频段有交集）。
        f0_ghz: 中心频率（GHz）, 稳定性/增益/噪声的报告点。
        noise_params: 可选 {"fmin_db", "gamma_opt_re", "gamma_opt_im", "rn_norm"}
            （器件噪声参数, 手工口径按 ΓS=Γopt 与 ΓS=0 两点给 NF）。
        ads_runner: 可注入 ADS 仿真 (netlist_path)->payload; 缺省真机链。
        tol_db: ADS vs 手工口径判定门（|ΔSij| dB 最大值）。
        out_dir: 网表/报告落盘目录（缺省不落盘）。

    Returns:
        JSON-able summary（含 stability/manual/ads/noise/verdict 五段）。
    """
    f0_hz = f0_ghz * 1e9
    _match_net, device_net, cascade_net = ads_active_chain.chain_manual_reference(
        match_snp, device_snp,
    )
    idx_f0 = int(np.argmin(np.abs(cascade_net.f - f0_hz)))
    s_dev = device_net.s[int(np.argmin(np.abs(device_net.f - f0_hz)))]
    s_chain = cascade_net.s[idx_f0]

    dev_margins = stability_margins(s_dev)
    chain_margins = stability_margins(s_chain)
    manual_section: dict[str, Any] = {
        "f0_hz": round(float(cascade_net.f[idx_f0]), 3),
        "device_stability": dev_margins.to_dict(),
        "chain_stability": chain_margins.to_dict(),
        "chain_s21_db": round(20.0 * float(np.log10(abs(s_chain[1, 0]) + 1e-30)), 6),
        "chain_gt_50ohm_db": round(transducer_gain_db(s_chain, 0.0, 0.0), 6),
    }
    if dev_margins.unconditionally_stable:
        cm = simultaneous_conjugate_match(s_dev)
        manual_section["device_conjugate_match"] = cm.to_dict()
        manual_section["chain_gt_at_conj_load_db"] = round(
            transducer_gain_db(s_chain, 0.0, cm.gamma_l), 6,
        )
    else:
        manual_section["device_conjugate_match"] = {
            "status": "unavailable",
            "reason": f"器件非无条件稳定 (K={dev_margins.k_factor:.3f})",
        }

    ads_section: dict[str, Any]
    import tempfile

    if out_dir is not None:
        result = ads_active_chain.run_ads_chain(
            match_snp, device_snp, Path(out_dir),
            ads_dir=ads_dir, ads_runner=ads_runner, z0=DEFAULT_Z0,
        )
    else:
        with tempfile.TemporaryDirectory() as td:
            result = ads_active_chain.run_ads_chain(
                match_snp, device_snp, td,
                ads_dir=ads_dir, ads_runner=ads_runner, z0=DEFAULT_Z0,
            )
    if result["status"] == "ok":
        ads_net = ads_active_chain.payload_to_network(result["payload"])
        cmp_res = ads_active_chain.compare_chain_with_manual(ads_net, cascade_net, tol_db=tol_db)
        ads_section = {
            "status": "ok", "netlist": result.get("netlist"),
            "sim_time_s": result.get("sim_time_s"),
            "vs_manual": cmp_res,
        }
    else:
        ads_section = {"status": "error", "error": result.get("error"),
                       "netlist": result.get("netlist")}

    noise_section: dict[str, Any] = {"status": "skipped", "reason": "未提供噪声参数"}
    if noise_params:
        gamma_opt = complex(
            noise_params.get("gamma_opt_re", 0.0), noise_params.get("gamma_opt_im", 0.0),
        )
        fmin_db = float(noise_params.get("fmin_db", 1.0))
        rn = float(noise_params.get("rn_norm", 0.5))
        noise_section = {
            "status": "ok",
            "fmin_db": fmin_db,
            "f_at_gamma_opt_db": round(noise_figure_db(fmin_db, gamma_opt, rn, gamma_opt), 6),
            "f_at_50ohm_db": round(noise_figure_db(fmin_db, gamma_opt, rn, 0.0), 6),
            "note": "NF 为器件噪声参数口径的手工评价值; ADS CalcNoise 通道随真机链恢复",
        }

    verdict = {
        "ads_vs_manual": ads_section.get("vs_manual", {}).get("consistent"),
        "device_unconditionally_stable": dev_margins.unconditionally_stable,
        "chain_unconditionally_stable": chain_margins.unconditionally_stable,
    }
    summary = {
        "status": "ok",
        "inputs": {
            "match_snp": str(match_snp), "device_snp": str(device_snp),
            "f0_ghz": f0_ghz,
        },
        "manual": manual_section,
        "ads": ads_section,
        "noise": noise_section,
        "verdict": verdict,
    }
    if out_dir is not None:
        path = Path(out_dir) / "active_chain_summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_jsonable(summary), ensure_ascii=False, indent=2), encoding="utf-8",
        )
        summary["summary_path"] = str(path)
    return _jsonable(summary)


def run_pa_loadpull(
    vdd_v: float,
    imax_a: float,
    cout_pf: float,
    f0_ghz: float,
    *,
    vknee_v: float = 0.3,
    backoff_db: tuple[float, ...] = (1.0, 2.0, 3.0),
    n_grid: int = 81,
    r_max: float = 0.9,
    z0: float = DEFAULT_Z0,
    device_snp: str | Path | None = None,
    out_dir: str | Path | None = None,
    render_ads_points: bool = False,
) -> dict[str, Any]:
    """PA load-pull 口径: Cripps 等功率圈全离线分析（零仿真）。

    Args:
        vdd_v/imax_a/cout_pf/vknee_v: 器件物理参数（漏压/最大电流/输出电容/膝点）。
        f0_ghz: 基波频率。
        backoff_db: 等功率线回退电平族。
        n_grid/r_max: ΓL 极坐标网格分辨率。
        z0: 系统阻抗。
        device_snp: 可选器件 S2P → 叠加恒增益面 + GT,max 自洽检查。
        out_dir: 摘要 JSON 落盘目录（缺省不落盘）。
        render_ads_points: 可选, 在解析等功率线采样点渲染 ADS HB 网表
            （B 档逐点通道, 语法已真机实证, 仅产出网表文件不仿真）。

    Returns:
        JSON-able: optimum/contours/plausibility/gain(可选)/verdict。
    """
    f0_hz = f0_ghz * 1e9
    device = LoadPullDevice(vdd_v=vdd_v, imax_a=imax_a, cout_f=cout_pf * 1e-12,
                            vknee_v=vknee_v)
    sparams = None
    if device_snp is not None:
        sparams = _sparams_at_f0(device_snp, f0_hz)
    scan = load_pull_scan(
        device, f0_hz, n_grid=n_grid, r_max=r_max,
        backoff_db=tuple(backoff_db), sparams=sparams, z0=z0,
    )
    plausibility = load_pull_plausibility(scan, sparams=sparams)
    summary: dict[str, Any] = {
        "status": "ok",
        "device": {
            "vdd_v": vdd_v, "imax_a": imax_a, "cout_pf": cout_pf,
            "vknee_v": vknee_v,
            "gopt_s": round(device.gopt_s, 6),
            "max_power_dbm": round(device.max_power_dbm(), 4),
        },
        "f0_ghz": f0_ghz,
        "z0": z0,
        "optimum": scan.optimum_dict(),
        "contours": scan.contours,
        "plausibility": plausibility,
        "verdict": {
            "loadpull_plausible": plausibility["plausible"],
            "n_contours": len(scan.contours),
        },
    }
    if sparams is not None:
        m = stability_margins(sparams)
        summary["gain"] = {
            "device_stability": m.to_dict(),
        }
        if m.unconditionally_stable:
            cm = simultaneous_conjugate_match(sparams)
            summary["gain"]["gt_max_db"] = round(cm.gt_max_db, 4)
            summary["gain"]["gamma_ml"] = _jsonable(cm.gamma_l)

    if out_dir is not None and render_ads_points:
        netlists: list[str] = []
        for c in scan.contours:
            for pt in c["locus"]["gamma_polyline"][::4]:
                gamma = complex(pt["re"], pt["im"])
                z_load = gamma_to_z(gamma, z0)
                out = Path(out_dir) / "loadpull_netlists" / (
                    f"lp_bo{c['backoff_db']:g}_{pt['re']:+.4f}{pt['im']:+.4f}j.net"
                )
                try:
                    if device_snp is not None:
                        ads_active_chain.render_loadpull_netlist(
                            device_snp, out, f0_hz=f0_hz,
                            power_dbm=c["level_dbm"], z_load=z_load, z0=z0,
                        )
                        netlists.append(str(out))
                except (OSError, ValueError) as exc:
                    logger.warning("load-pull 网表渲染跳过一点: %s", exc)
        summary["ads_point_netlists"] = netlists
    if out_dir is not None:
        path = Path(out_dir) / "loadpull_summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_jsonable(summary), ensure_ascii=False, indent=2), encoding="utf-8",
        )
        summary["summary_path"] = str(path)
    return _jsonable(summary)


def synthetic_device_sparams(
    gm_ms: float, rds_ohm: float, cgs_pf: float, cds_pf: float,
    f0_ghz: float, cgd_pf: float = 0.002, rg_ohm: float = 5.0,
) -> dict[str, Any]:
    """混合π合成器件 2x2 S 参数（测试/示例脚手架, JSON 进出）。"""
    model = HybridPiModel(
        gm_s=gm_ms * 1e-3, rds_ohm=rds_ohm,
        cgs_f=cgs_pf * 1e-12, cds_f=cds_pf * 1e-12,
        cgd_f=cgd_pf * 1e-12, rg_ohm=rg_ohm,
    )
    s = model.to_sparams(f0_ghz * 1e9)
    return {
        "f0_ghz": f0_ghz,
        "s": [[{"re": round(s[i, j].real, 8), "im": round(s[i, j].imag, 8)}
               for j in range(2)] for i in range(2)],
        "stability": stability_margins(s).to_dict(),
    }

"""D12：用 FSV 内核对照仓库归档的 HFSS vs openEMS 曲线（只读归档，落 JSON）。

用法（工作区根目录）：
    .venv/Scripts/python.exe scripts/fsv_patch_compare.py

产物：runs/fsv/pair_probe.json（配对存在性核查）+ runs/fsv/ratrace_fsv.json
（GDM 等级等），stdout 打印摘要。

配对优先级：patch 同几何对 > wilkinson 同几何对 > ratrace。
每个候选都做**文件存在性 + 几何一致性**核查，缺失/不同几何一律如实记录，
不做跨几何拼接（模型不对齐的比较没有意义）。

候选归档说明（脚本运行时重新核查，结论落 pair_probe.json）：
1. patch：HFSS 与 openEMS 侧曲线几何不同（HFSS patch_w=45mm / 基板
   80x80mm；openEMS 分别 50mm/60mm 板 与 34.9mm/50mm/120x120mm）
   -> 无同几何对。
2. wilkinson：HFSS 曲线存在，但 openEMS 侧只归档了时域端口文件
   （port_ut_*、port_it_*），**无频域 S 参数曲线 / sparams.csv**
   -> 无法做频率分辨对照。
3. ratrace：HFSS 全 4 端口 s4p + openEMS sparams.csv（端口 1 激励）
   -> **本仓唯一真实可用的频域配对**，本脚本采用。

已知非严格同几何声明：ratrace 的
openEMS 渲染层用了 k=1.0975 标定，HFSS 为物理 R=17.344mm，故两者是"同标称
设计、非严格同尺寸"。该偏差本身就是本对照要量化的对象。

已知非严格同几何声明（沿用 scripts/koh_calibrate.py 的 caveat）：ratrace 的
openEMS 渲染层用了 k=1.0975 标定，HFSS 为物理 R=17.344mm，故两者是"同标称
设计、非严格同尺寸"。该偏差本身就是本对照要量化的对象。

touchstone / openEMS CSV 解析口径沿用 scripts/koh_calibrate.py 的既有实现
（同仓已验路径），本脚本自带一份以免跨脚本私有导入。

数值口径：S 参数幅度取 dB（20log10|S|，下限 -300dB），相位取解卷绕后的
角度（deg）；两者都直接喂给 rfauto.core.fsv（core 层零依赖）。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.core.fsv import fsv, to_jsonable  # noqa: E402

OUT_DIR = REPO / "runs" / "fsv"

# ── 候选归档路径（存在性运行期核查；默认指向 runs/ 下的同名归档，缺失时如实记录）─
PATCH_HFSS = REPO / "runs" / "patch_hfss_probe" / "probe.s1p"
PATCH_OEMS = [
    REPO / "runs" / "audit_freq_scale" / "smoke_patch_auto" / "sparams.csv",
    REPO / "runs" / "template_deviation" / "patch" / "fdtd" / "fdtd" / "sparams.csv",
]
E4_HFSS = REPO / "runs" / "audit_freq_scale" / "hfss_arbitration" / "hfss_arb.s3p"
E4_OEMS_DIR = REPO / "runs" / "audit_freq_scale"
RATRACE_HFSS = REPO / "runs" / "ratrace_arbitration" / "hfss_ratrace.s4p"
RATRACE_OEMS = REPO / "runs" / "ratrace_arbitration" / "mesh_0p2mm" / "p1" / "sparams.csv"

# 几何对照（脚本注释中的实测参数，写进 JSON 供复核）
PATCH_GEOMETRY = {
    "hfss_probe": {"patch_len_mm": 40.0, "patch_w_mm": 45.0, "feed_offset_mm": 7.8,
                   "sub_mm": [80.0, 80.0], "sub_h_mm": 0.508,
                   "source": "HFSS 工程变量（probe.aedt VariableProp）"},
    "openems_smoke_patch_auto": {"patch_len_mm": 40.0, "patch_w_mm": 50.0,
                                 "feed_offset_mm": 7.8, "board_mm": 60.0,
                                 "sub_h_mm": 0.508,
                                 "source": "openEMS 冒烟渲染脚本 simulation.py"},
    "openems_template_deviation": {"patch_len_mm": 34.9, "patch_w_mm": 50.0,
                                   "sub_mm": [120.0, 120.0], "sub_h_mm": 0.508,
                                   "source": "openEMS 模板偏差轮渲染脚本 simulation.py"},
}


# --------------------------------------------------------------------------- #
# 归档读取
# --------------------------------------------------------------------------- #

def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def read_touchstone(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """解析 MA/RI/DB 格式 touchstone，返回 (freq_ghz, S[nf, np, np])。"""
    stem = path.name.lower()
    if ".s" not in stem or not stem.endswith("p"):
        raise ValueError(f"无法从文件名推断端口数: {path.name}")
    nports = int(stem[stem.rfind(".s") + 2:-1])
    fmt, funit = "MA", "ghz"
    tokens: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("#"):
            parts = [p.upper() for p in line[1:].split()]
            funit = parts[0].lower() if parts else "ghz"
            if "S" in parts and parts.index("S") + 1 < len(parts):
                fmt = parts[parts.index("S") + 1]
            continue
        tokens.extend(line.split())
    per_point = 1 + 2 * nports * nports
    if per_point <= 1 or len(tokens) % per_point:
        raise ValueError(f"{path.name}: 令牌数 {len(tokens)} 与端口数 {nports} 不匹配")
    arr = np.asarray(tokens, dtype=float).reshape(-1, per_point)
    scale = {"hz": 1e-9, "khz": 1e-6, "mhz": 1e-3, "ghz": 1.0}[funit]
    freqs = arr[:, 0] * scale
    s = np.zeros((arr.shape[0], nports, nports), dtype=complex)
    for k in range(nports * nports):
        a, b = arr[:, 1 + 2 * k], arr[:, 2 + 2 * k]
        i, j = divmod(k, nports)
        if fmt == "RI":
            s[:, i, j] = a + 1j * b
        elif fmt == "DB":
            s[:, i, j] = 10.0 ** (a / 20.0) * np.exp(1j * np.deg2rad(b))
        else:
            s[:, i, j] = a * np.exp(1j * np.deg2rad(b))
    return freqs, s


def read_openems_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """解析 openEMS sparams.csv（freq_hz, re/im 逐端口），只存端口 1 激励列。"""
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    header, body = rows[0], [r for r in rows[1:] if r]
    nports = (len(header) - 1) // 2
    data = np.asarray(body, dtype=float)
    s = np.zeros((data.shape[0], nports, nports), dtype=complex)
    for k in range(nports):
        s[:, k, 0] = data[:, 1 + 2 * k] + 1j * data[:, 2 + 2 * k]
    return data[:, 0] / 1e9, s


def _db(mag: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(np.abs(mag), 1e-15))


def _deg(mag: np.ndarray) -> np.ndarray:
    return np.rad2deg(np.unwrap(np.angle(mag)))


# --------------------------------------------------------------------------- #
# 配对存在性核查
# --------------------------------------------------------------------------- #

def probe_pairs() -> dict[str, object]:
    """逐个核查候选配对的存在性与几何一致性（不拼接不同几何）。"""
    e4_oems_freq = sorted(
        p.as_posix().replace(REPO.as_posix() + "/", "")
        for pat in ("**/*.s*p", "**/sparams.csv")
        for p in E4_OEMS_DIR.glob(pat)
        if p.is_file() and "hfss_arbitration" not in p.as_posix()
    )
    return {
        "patch": {
            "hfss_curve": {"path": _rel(PATCH_HFSS), "exists": PATCH_HFSS.exists()},
            "openems_curves": [
                {"path": _rel(p), "exists": p.exists()} for p in PATCH_OEMS
            ],
            "geometry": PATCH_GEOMETRY,
            "same_geometry_pair": False,
            "reason": (
                "HFSS patch_w=45mm/基板 80x80mm；openEMS 侧为 50mm/60mm 板"
                "（smoke_patch_auto，PL=40mm）与 34.9mm/50mm/120x120mm"
                "（template_deviation）——逐参数不一致，不构成同几何对；"
                "runs/wp39_mvp/_work_patch__* 的 eval_*.s1p 同为 HFSS 导出"
                "（WP3.9 该器件族只用 HFSS），无 openEMS 频域对。"
            ),
        },
        "e4_wilkinson": {
            "hfss_curve": {"path": _rel(E4_HFSS), "exists": E4_HFSS.exists()},
            "openems_freq_curves_found": e4_oems_freq,
            "same_geometry_pair": False,
            "reason": (
                "openEMS 侧仅归档时域端口文件（e4_wilk*/fdtd/port_ut_*, "
                "port_it_*），无频域 S 参数曲线或 sparams.csv；"
                "与 scripts/koh_calibrate.py 的核查结论一致。"
            ),
        },
        "ratrace": {
            "hfss_curve": {"path": _rel(RATRACE_HFSS), "exists": RATRACE_HFSS.exists()},
            "openems_curve": {"path": _rel(RATRACE_OEMS), "exists": RATRACE_OEMS.exists()},
            "same_geometry_pair": RATRACE_HFSS.exists() and RATRACE_OEMS.exists(),
            "reason": (
                "同标称 rat-race 设计与端口编号；openEMS 渲染层用 k=1.0975 "
                "标定、HFSS 为物理 R=17.344mm（非严格同尺寸，见 "
                "scripts/koh_calibrate.py caveat）——本仓唯一可用的频域配对。"
            ),
        },
    }


# --------------------------------------------------------------------------- #
# FSV 对照
# --------------------------------------------------------------------------- #

def compare(f_h: np.ndarray, s_h: np.ndarray, f_o: np.ndarray, s_o: np.ndarray,
            nports: int, ports: range) -> dict[str, object]:
    """对端口 1 激励列 S_i1（i in ports）的幅度(dB)与相位(deg)做 FSV。"""
    out: dict[str, object] = {}
    entries: list[tuple[str, np.ndarray, np.ndarray]] = []
    for port in ports:
        entries.append((f"s{port + 1}1_db", _db(s_h[:, port, 0]), _db(s_o[:, port, 0])))
        entries.append((f"s{port + 1}1_phase_deg",
                        _deg(s_h[:, port, 0]), _deg(s_o[:, port, 0])))
    for name, y_h, y_o in entries:
        res = fsv(f_h, y_h, f_o, y_o)
        item = to_jsonable(res)
        out[name] = {
            "adm_mean": round(float(item["adm_mean"]), 6),
            "fdm_mean_signed": round(float(item["fdm_mean"]), 6),
            "fdm_mean_abs": round(float(item["fdm_mean_abs"]), 6),
            "gdm_mean": round(float(item["gdm_mean"]), 6),
            "adm_grade": item["adm_grade"],
            "fdm_grade": item["fdm_grade"],
            "gdm_grade": item["gdm_grade"],
            "gdm_grade_level": item["gdm_grade_level"],
            "gdm_spread": item["gdm_spread"],
            "confidence_gdm": [round(float(v), 6) for v in np.asarray(item["confidence"])],
            "band": item["band"],
            "n_points": item["n_points"],
            "freq_ghz": [round(float(v), 6) for v in np.asarray(item["freq"])],
            "adm": [round(float(v), 6) for v in np.asarray(item["adm"])],
            "fdm": [round(float(v), 6) for v in np.asarray(item["fdm"])],
            "gdm": [round(float(v), 6) for v in np.asarray(item["gdm"])],
        }
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    probe = probe_pairs()
    (OUT_DIR / "pair_probe.json").write_text(
        json.dumps({"item": "fsv-d12", "pairs": probe}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[D12 FSV] 配对存在性核查")
    for key in ("patch", "e4_wilkinson", "ratrace"):
        info = probe[key]
        usable = bool(info.get("same_geometry_pair"))
        print(f"  - {key:14s} 同几何可用={usable}  {str(info['reason'])[:70]}...")

    if not (RATRACE_HFSS.exists() and RATRACE_OEMS.exists()):
        print("[D12 FSV] ratrace 归档缺失，未做对照（不伪造数据）")
        return 1

    f_h, s_h = read_touchstone(RATRACE_HFSS)
    f_o, s_o = read_openems_csv(RATRACE_OEMS)
    nports = min(s_h.shape[1], s_o.shape[1])
    f_lo = max(float(f_h.min()), float(f_o.min()))
    f_hi = min(float(f_h.max()), float(f_o.max()))
    print(f"[D12 FSV] 采用 ratrace 配对：HFSS {f_h.size} 点 "
          f"[{f_h.min():.3f},{f_h.max():.3f}]GHz vs openEMS {f_o.size} 点 "
          f"[{f_o.min():.3f},{f_o.max():.3f}]GHz；重叠 [{f_lo:.3f},{f_hi:.3f}]GHz，"
          f"{nports} 端口")

    metrics = compare(f_h, s_h, f_o, s_o, nports, ports=range(nports))
    payload = {
        "item": "fsv-d12",
        "generated_by": "scripts/fsv_patch_compare.py",
        "fsv_source": "rfauto.core.fsv（IEEE 1597.1 口径；公式来源见该模块 docstring）",
        "pair": {
            "hfss": _rel(RATRACE_HFSS),
            "openems": _rel(RATRACE_OEMS),
            "same_geometry": "nominal（openEMS k=1.0975 标定 vs HFSS 物理 R=17.344mm）",
            "overlap_ghz": [f_lo, f_hi],
            "n_ports": nports,
        },
        "caveats": [
            "patch 同几何对不存在（HFSS/openEMS patch 几何参数不一致）——见 pair_probe.json。",
            "0.1⑤ E4 wilkinson 的 openEMS 频域曲线未归档，无法做频域 FSV。",
            "ratrace 配对非严格同尺寸（k 标定差异），GDM 等级含该几何偏差。",
            "未复现公开文献带原始数据的 FSV 数值测例（未找到公开数据），"
            "本产物只给本仓归档上的 FSV 结果，未与文献数值对拍。",
        ],
        "metrics": metrics,
    }
    out_path = OUT_DIR / "ratrace_fsv.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[D12 FSV] 结果 -> {_rel(out_path)}")
    print("  metric              ADM     FDM|.|  GDM     等级(ADM/FDM/GDM)  n")
    for name, m in metrics.items():
        print(f"  {name:18s} {m['adm_mean']:7.4f} {m['fdm_mean_abs']:7.4f} "
              f"{m['gdm_mean']:7.4f}  {m['adm_grade']:>2s}/{m['fdm_grade']:>2s}/"
              f"{m['gdm_grade']:>2s}            {m['n_points']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

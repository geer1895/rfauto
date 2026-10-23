"""双引擎对照曲线服务（aurora_i R3 设计 M3；W3-S1 席 2026-10-19）。

用户痛点："加入一些使用的仿真软件中的图表来和我们的功能相对应，否则
很多人可能质疑你的结果有问题"。本模块把 runs/ 证据湖里**已在盘的双引擎
S 曲线对**（HFSS 仲裁基准 vs openEMS 主力引擎）按模板族组装成 JSON 曲线
族，供 /api/credibility/curves 数据面与前端叠加图消费——前端零文件读取
（runs 静态挂载默认关，R2-B-05）。

数据地基（R3 §1.2 实测，本席 2026-10-19 复核在盘）：
- 曲线级配对 5 族：wilkinson / stepped_impedance / coupled_line（b2a 批
  oe_nominal/sparams.csv 与 hfss_side/rung*.sNp 齐备）、ratrace
  （hfss_ratrace.s4p + mesh_0p2mm/p1）、slotline_transitions（hfss/ +
  trans/ 双侧）；R3 口径 6 族中 patch_array_2x2 的 oe_rerun_nrts 目录
  **无 sparams.csv 产物**（fdtd/ 仅 et/ht 时序）——运行时如实降级单引擎
  +note（诚实注记，不虚构第二根线）。
- 单引擎（HFSS 侧）3 族：gysel / marchand_balun / branchline（branchline
  的 oe_rerun_prep 同为时序无 csv）。R3 §1.2：OE 侧数据散在各自 smoke/
  真机 run，v1 先单曲线+如实 note。

解析红线（R3 §5 / 本席禁改清单）：**解析一律走既有链，不重写 S 参数
解析器**——
- HFSS Touchstone：rfauto.measurement.import_data.import_touchstone
  （skrf；#248 扩展名推秩、#309 多模改名兼容面）；
- openEMS sparams.csv：service.health_service._parse_sparams_csv_masked
  （#314 掩码载体优先：只对 measured_mask=True 元素出线，互易/对称补齐
  元素不冒充测量值；sidecar 在档即权威）。
- 唯一分叉：ratrace 4 端口单激励 csv（header 含 re_S41，写出契约
  adapters/oe_templates/render_ratrace_cyl.py:415）——既有 masked 解析器
  的 ≥9 列分支会把它按 3 端口 S23 语义误读（S41 数据错标 S23）。处置=
  按写出端 header 自描述分派：re_S41 头走 np.loadtxt 直读四元素
  （同 scripts/ratrace_k_finalize.py:174 既有消费先例），re_S23/5 列/7 列
  头一律走既有 masked 链。这是"既有链不覆盖的写出端 schema"按其自描述
  契约直读，不是解析器重写（原文证据零改写，纯只读）。

频轴对齐（#287/#294）：同栅判定用 ulp 级容差（max|Δf|≤1e-9 相对）；异栅
（如 OE 子窗 1.92–2.88 vs HFSS 1.5–3.5）用 argmin 最近邻 + 半细步容差
配对，n_matched 如实报告——不插值、不外推、不假装同栅。

偏差注记：dB 域（20·log10(|S|+1e-12)，与 sparams_series 同式）逐 S 名
算配对点 max|ΔdB| 及其频点；verdict 态从各族 verdict/仲裁 JSON 汇总
（AGREE/DISAGREE/UNKNOWN 如实，#122 不凑绿）。铁律 7 一致：本模块只
搬运盘上曲线与既有判读产物，不产生任何物理数字。

公开面说明：本模块刻意**不带 __all__**（metric_glossary_service 同例
——公开 API 金快照有他席在制漂移，本席不翻公开名、不重钉金快照；
函数保持可 import 消费，后续快照重生成批再显式登记）。
"""

from __future__ import annotations

import csv as _csv
from pathlib import Path
from typing import Any

from rfauto.service.envelope import ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）。
#: 1.0=首发 10 族口径（R3 §1.2 清单 + 本席在盘复核）。
CREDIBILITY_CURVES_SERVICE_SCHEMA_VERSION = "1.0"

#: runs/ 证据根（cwd 相对，与 ui_service.cache.RUNS_DIR 同约定；测试可
#: monkeypatch 本常量做隔离）。本模块对证据目录**纯只读**（R3 §5：
#: 归档证据零改写，#325/#326 golden 纪律）。
RUNS_ROOT = Path("runs")

#: 同栅判定容差：max|Δf| ≤ 1e-9 × f_max（#287 频轴 ulp 噪声量级）。
_SAME_GRID_RTOL = 1e-9

#: 最近邻配对容差因子：|Δf| ≤ 0.5 × min(两轴步长)（半细步内才算配对；
#: #294 argmin 最近邻口径 + n_matched 如实）。
_MATCH_TOL_FACTOR = 0.5

#: HFSS 侧缺省梯级 rung（b2a 判读 remote_fetch.server_path 引用 rung3=
#: 最细 ΔS 档；rung1/2/3 同目录在盘，改梯级=改登记表）。
HFSS_RUNG_FILE = "rung3"

#: 曲线族注册表（R3 §1.2 清单 + 本席 2026-10-19 在盘复核；路径相对
#: runs/。oe_file=None=该族 v1 无 OE 曲线归集（R3 §1.2 如实注记）；
#: oe_file 声明而缺盘=运行时 note 如实降级单引擎）。
#:
#: 字段：template=模板族名（画廊/锚 template_family 同名空间）；
#: hfss_file=HFSS Touchstone（相对 runs/）；oe_file=openEMS sparams.csv
#: （相对 runs/，可 None）；verdict_file=判读/仲裁 JSON（相对 runs/，
#: 可 None）；oe_note=OE 侧缺席时的人话注记。
_FAMILIES: tuple[dict[str, str | None], ...] = (
    {
        "template": "wilkinson",
        "hfss_file": "hfss_window_b2a/wilkinson/hfss_side/rung3.s3p",
        "oe_file": "hfss_window_b2a/wilkinson/oe_nominal/sparams.csv",
        "verdict_file": "hfss_window_b2a/wilkinson/hfss_side/verdict.json",
        "oe_note": None,
    },
    {
        "template": "stepped_impedance",
        "hfss_file": "hfss_window_b2a/stepped_impedance/hfss_side/rung3.s2p",
        "oe_file": "hfss_window_b2a/stepped_impedance/oe_nominal/sparams.csv",
        "verdict_file": (
            "hfss_window_b2a/stepped_impedance/hfss_side/verdict.json"),
        "oe_note": None,
    },
    {
        "template": "coupled_line",
        "hfss_file": "hfss_window_b2a/coupled_line/hfss_side/rung3.s3p",
        "oe_file": "hfss_window_b2a/coupled_line/oe_nominal/sparams.csv",
        "verdict_file": (
            "hfss_window_b2a/coupled_line/hfss_side/verdict.json"),
        "oe_note": None,
    },
    {
        "template": "patch_array_2x2",
        "hfss_file": "hfss_window_b2a/patch_array_2x2/hfss_side/rung3.s1p",
        "oe_file": (
            "hfss_window_b2a/patch_array_2x2/oe_rerun_nrts/run_nrts2p3m"
            "/sparams.csv"),
        "verdict_file": (
            "hfss_window_b2a/patch_array_2x2/hfss_side/verdict.json"),
        "oe_note": (
            "oe_rerun_nrts/run_nrts2p3m 在盘但无 sparams.csv 产物"
            "（fdtd/ 仅 et/ht 时序）——R3 §0 曲线配对清单口径乐观，"
            "本席 2026-10-19 在盘复核如实降级单引擎"),
    },
    {
        "template": "branchline",
        "hfss_file": "hfss_window_b2a/branchline/hfss_side/rung3.s4p",
        "oe_file": (
            "hfss_window_b2a/branchline/oe_rerun_prep/mesh02_rotation/p1"
            "/sparams.csv"),
        "verdict_file": (
            "hfss_window_b2a/branchline/hfss_side/verdict.json"),
        "oe_note": (
            "oe_rerun_prep/mesh02_rotation/p1 在盘但无 sparams.csv 产物"
            "（fdtd/ 仅时序）——v1 如实降级单引擎"),
    },
    {
        "template": "gysel",
        "hfss_file": "hfss_window_b2a/gysel/hfss_side/rung3.s3p",
        "oe_file": None,
        "verdict_file": "hfss_window_b2a/gysel/hfss_side/verdict.json",
        "oe_note": (
            "OE 侧数据散在各自 smoke/真机 run 未归集（R3 §1.2）——"
            "v1 单引擎曲线+per_metric 配对值（verdict_file）"),
    },
    {
        "template": "marchand_balun",
        "hfss_file": "hfss_window_b2a/marchand_balun/hfss_side/rung3.s3p",
        "oe_file": None,
        "verdict_file": (
            "hfss_window_b2a/marchand_balun/hfss_side/verdict.json"),
        "oe_note": (
            "OE 侧数据散在各自 smoke/真机 run 未归集（R3 §1.2）——"
            "v1 单引擎曲线+per_metric 配对值（verdict_file）"),
    },
    {
        "template": "ratrace",
        "hfss_file": "ratrace_arbitration/hfss_ratrace.s4p",
        "oe_file": "ratrace_arbitration/mesh_0p2mm/p1/sparams.csv",
        "verdict_file": "ratrace_arbitration/ratrace_arbitration.json",
        "oe_note": None,
    },
    {
        "template": "slotline_transitions",
        "hfss_file": "slotline_transitions/hfss/hfss_trans.s2p",
        "oe_file": "slotline_transitions/trans/sparams.csv",
        "verdict_file": "slotline_transitions/compare.json",
        "oe_note": None,
    },
)


def registered_families() -> list[str]:
    """注册表模板族名清单（注册序）。"""
    return [str(f["template"]) for f in _FAMILIES]


#: 存量 run 旧模型名 → 现行模板名（aurora_j W1-S2 席 2026-10-23）。
#: 证据链：P0–P6 时代（2026-08-27~08-30）模型插件恰三族
#: src/rfauto/models/{wilkinson_power_divider,branchline_coupler,
#: patch_antenna}/（git 851614e8 的 models/registry.py 实测）；v3 模板库
#: 扩充（936a8e8e 2026-09-01，"branchline/dipole/stepped/coupled_line"）
#: 起改用现行短名 wilkinson/branchline/patch（f65a9afe 2026-09-02
#: "wilkinson/patch openEMS 真跑"旁证；patch_antenna→patch 另有参数面
#: 实证：湖内 patch_antenna run 的 samples.json bounds 恰为现行 patch
#: 族 TEMPLATE_NOMINAL 的 patch_len_mm/patch_w_mm 同名参数）。
#: runs/ 湖 meta.model 旧名存量实测（2026-10-23 抽样 1819 份 meta.json）：
#: wilkinson_power_divider×~1290 / branchline_coupler×~77 /
#: patch_antenna×4。映射只认此处**显式登记**的历史名——不做模糊/前缀
#: 匹配（模糊匹配会制造假对照，违反诚实降级原则）；表为空时零行为
#: 变化。注意：别名解析到的是**模板注册表名空间**（72 族）——归一结果
#: 未必在本服务对照注册表（如 patch 不在 _FAMILIES 9 族），此时与直查
#: 该现行名同样走诚实空态（别名不虚构曲线注册）。
_MODEL_ALIASES: dict[str, str] = {
    "wilkinson_power_divider": "wilkinson",
    "branchline_coupler": "branchline",
    "patch_antenna": "patch",
}


def _normalize_model_alias(model: str) -> str:
    """存量 run 旧模型名 → 现行模板名（strip→lower→查表）。

    命中 _MODEL_ALIASES 换现行名；未命中返回 strip+lower 后的输入
    （调用方对注册表本就大小写不敏感精确匹配，语义不变）。只认显式
    登记的历史名，不做模糊匹配/前缀匹配——模糊匹配会制造假对照
    （诚实降级原则，#122 同族：不凑对照）；表为空时零行为变化。
    """
    key = str(model).strip().lower()
    return _MODEL_ALIASES.get(key, key)


#: 跨模块消费的公开别名（同一函数对象，aurora_j W5-S20 审查清偿：
#: model_card_service 等外部模块不再引下划线私有名）。本模块无 __all__
#:（见模块 docstring 公开面说明），别名不翻公开 API 金快照。
normalize_model_alias = _normalize_model_alias


# ── 曲线解析（全部走既有链，见模块 docstring 红线节）────────────────────


def _read_csv_header(path: Path) -> list[str]:
    """读 sparams.csv 首行 header（写出端自描述契约，分派依据）。"""
    with open(path, encoding="utf-8", newline="") as fh:
        row = next(_csv.reader(fh), [])
    return [c.strip() for c in row]


def _parse_oe_csv(path: Path) -> dict[str, Any] | None:
    """openEMS sparams.csv → 引擎曲线负载（freq_hz[]/curves/n_ports）。

    分派（header 自描述）：
    - header 含 re_S41 → 4 端口单激励部分矩阵（写出契约
      render_ratrace_cyl.py:415；既有消费先例 scripts/ratrace_k_finalize
      .py:174 np.loadtxt 直读）——S11/S21/S31/S41 四元素全为直接测量；
    - 其余（5 列 2 端口 / 9 列 3 端口 S23 / 7 列带 resid 列）→ 既有
      health_service._parse_sparams_csv_masked（#314 掩码载体优先；
      sidecar 在档即权威，缺档列数启发式向后兼容）。
    解析失败/空表 → None（调用方如实 note，不虚构曲线）。
    """
    import numpy as np

    try:
        header = _read_csv_header(path)
    except OSError:
        return None
    pairs: list[tuple[str, Any]] = []
    if "re_S41" in header:
        # 4 端口单激励写出契约：freq 后每 S 名 re/im 相邻对。
        try:
            data = np.loadtxt(str(path), delimiter=",", skiprows=1, ndmin=2)
        except Exception:
            return None
        if data.shape[0] == 0:
            return None
        freq_hz = data[:, 0]
        col = {name: i for i, name in enumerate(header)}
        for sname in ("S11", "S21", "S31", "S41"):
            re_i, im_i = col.get(f"re_{sname}"), col.get(f"im_{sname}")
            if re_i is None or im_i is None or im_i != re_i + 1:
                continue
            pairs.append((sname, data[:, re_i] + 1j * data[:, im_i]))
        if not pairs:
            return None
        curves = [
            {"name": n, "s_db": [round(float(v), 4) for v in _to_db(s)]}
            for n, s in pairs
        ]
        return {"freq_hz": freq_hz, "curves": curves, "n_ports": 4,
                "omitted_filled": [], "mask_note": None}
    # 既有链（#314）：masked 解析器主路。
    from rfauto.service.health_service import _parse_sparams_csv_masked

    try:
        parsed = _parse_sparams_csv_masked(path)
    except Exception:
        return None
    if parsed is None:
        return None
    freq_hz, s, mask = parsed
    n_ports = int(s.shape[1])
    omitted: list[str] = []
    curves = []
    for m in range(n_ports):
        for k in range(n_ports):
            name = f"S{m + 1}{k + 1}"
            if mask[m, k]:
                curves.append({
                    "name": name,
                    "s_db": [round(float(v), 4)
                             for v in _to_db(s[:, m, k])],
                })
            else:
                omitted.append(name)
    return {
        "freq_hz": freq_hz, "curves": curves, "n_ports": n_ports,
        "omitted_filled": omitted,
        "mask_note": (
            "单激励部分矩阵（掩码载体 #314）：仅直接测量元素出线，"
            "互易/对称补齐元素不单独出线" if omitted else None),
    }


def _to_db(s: Any) -> Any:
    """|S| → dB（20·log10(|S|+1e-12)，sparams_series 同式单源）。"""
    import numpy as np

    return 20 * np.log10(np.abs(s) + 1e-12)


def _parse_hfss_touchstone(path: Path) -> dict[str, Any] | None:
    """HFSS Touchstone → 引擎曲线负载（既有 import_touchstone 链）。"""
    from rfauto.measurement.import_data import import_touchstone

    try:
        data = import_touchstone(path)
    except Exception:
        return None
    s = data.s_params
    n = s.shape[1]
    curves = []
    for m in range(n):
        for k in range(n):
            curves.append({
                "name": f"S{m + 1}{k + 1}",
                "s_db": [round(float(v), 4) for v in _to_db(s[:, m, k])],
            })
    return {
        "freq_hz": data.freq_ghz * 1e9,  # 统一 Hz 语义（GHz property×1e9）
        "curves": curves, "n_ports": int(n),
        "omitted_filled": [], "mask_note": None,
    }


def _engine_payload(rel_file: str | None, engine: str) -> dict[str, Any]:
    """单引擎曲线负载组装（缺文件/解析失败 → available=False+note）。"""
    out: dict[str, Any] = {
        "available": False, "source": rel_file,
        "n_ports": None, "n_points": 0, "freq_ghz": [], "curves": [],
        "omitted_filled": [], "mask_note": None, "note": None,
    }
    if not rel_file:
        return out
    path = RUNS_ROOT / rel_file
    if not path.is_file():
        out["note"] = f"产物不在盘: runs/{rel_file}"
        return out
    parsed = (_parse_oe_csv(path) if engine == "openems"
              else _parse_hfss_touchstone(path))
    if parsed is None:
        out["note"] = f"解析失败（见模块 docstring 解析链口径）: {path.name}"
        return out
    import numpy as np

    freq_hz = np.asarray(parsed["freq_hz"], dtype=float)
    out.update({
        "available": True, "source": f"runs/{rel_file}",
        "n_ports": parsed["n_ports"], "n_points": int(freq_hz.size),
        # 频轴 9 位小数（GHz 域 µHz 粒度）：既压 JSON 体积，又保
        # _pair_curves 的 ulp 级同栅判定（1e-9 相对容差 > 5e-10 舍入
        # 上界；6 位小数的 1kHz 粒度会在舍入边界假分栅）。
        "freq_ghz": [round(float(x / 1e9), 9) for x in freq_hz],
        "curves": parsed["curves"],
        "omitted_filled": parsed["omitted_filled"],
        "mask_note": parsed["mask_note"], "note": None,
    })
    return out


# ── 配对与偏差注记（#287/#294 口径，见模块 docstring）───────────────────


def _pair_curves(hfss: dict[str, Any], oe: dict[str, Any]) -> dict[str, Any]:
    """双引擎曲线配对与逐 S 名最大偏差注记（dB 域）。

    单边缺席 → pairing=None+note（单引擎态）；双引擎在盘 → 同栅/最近邻
    两口径（#287 ulp 同栅直配；异栅 argmin 最近邻+半细步容差，n_matched
    如实——不插值不外推）。
    """
    if not (hfss["available"] and oe["available"]):
        return {"state": "single_engine", "note": "双引擎曲线不全，无配对"}
    import numpy as np

    fh = np.asarray(hfss["freq_ghz"], dtype=float)
    fo = np.asarray(oe["freq_ghz"], dtype=float)
    step_h = float(np.median(np.diff(fh))) if fh.size > 1 else 0.0
    step_o = float(np.median(np.diff(fo))) if fo.size > 1 else 0.0
    same_grid = (
        fh.size == fo.size
        and fh.size > 0
        and float(np.max(np.abs(fh - fo))) <= _SAME_GRID_RTOL
        * max(float(fh[-1]), 1e-12))
    if same_grid:
        idx_h = np.arange(fh.size)
        idx_o = np.arange(fh.size)
        n_matched = int(fh.size)
        tol_note = "同栅（ulp 级 #287）"
    else:
        tol = _MATCH_TOL_FACTOR * min(step_h, step_o) if step_h and step_o \
            else 0.0
        near = np.argmin(np.abs(fo[None, :] - fh[:, None]), axis=1) \
            if fo.size else np.zeros(fh.size, dtype=int)
        d = np.abs(fo[near] - fh) if fo.size else np.full(fh.size, np.inf)
        keep = d <= tol
        idx_h = np.nonzero(keep)[0]
        idx_o = near[keep]
        n_matched = int(idx_h.size)
        tol_note = f"最近邻（|Δf|≤{tol * 1e3:.3f}MHz，#294）"
    if n_matched == 0:
        return {"state": "no_overlap", "same_grid": False,
                "note": "频轴无重叠配对点（各自窗口不交或步长失配）"}
    oe_by_name = {c["name"]: c["s_db"] for c in oe["curves"]}
    per_s: dict[str, Any] = {}
    for c in hfss["curves"]:
        if c["name"] not in oe_by_name:
            continue
        yh = np.asarray(c["s_db"], dtype=float)[idx_h]
        yo = np.asarray(oe_by_name[c["name"]], dtype=float)[idx_o]
        dev = np.abs(yh - yo)
        j = int(np.argmax(dev))
        per_s[c["name"]] = {
            "max_dev_db": round(float(dev[j]), 4),
            "at_ghz": round(float(fh[idx_h[j]]), 6),
        }
    worst = max(per_s.items(), key=lambda kv: kv[1]["max_dev_db"],
                default=(None, None))
    lo = float(max(fh[idx_h].min(), fo[idx_o].min()))
    hi = float(min(fh[idx_h].max(), fo[idx_o].max()))
    return {
        "state": "paired",
        "same_grid": bool(same_grid),
        "match_rule": tol_note,
        "n_matched": n_matched,
        "overlap_ghz": [round(lo, 6), round(hi, 6)],
        "max_dev_db": per_s,
        "worst": ({"name": worst[0], **worst[1]} if worst[0] else None),
        # 口径注记（无判定数字）：dB 域差值在深谷/深隔离频点天然放大
        # （metric_glossary #370 同族语义），逐频差值以前端 hover 读数为准。
        "db_domain_note": (
            "max_dev_db 为 dB 域逐频最大差——深谷（回波/隔离凹陷）频点"
            "天然放大，判读以逐频 hover 差值与 per_metric 判读态为准"),
    }


def _verdict_summary(rel_file: str | None) -> dict[str, Any]:
    """判读态汇总（AGREE/DISAGREE/UNKNOWN 如实，#122 不凑绿）。

    verdict 形态两代兼容：b2a verdict.json 的 per_metric[].state 与
    ratrace/slotline 仲裁 JSON（无 per_metric → states 空表+路径指针
    如实）。缺盘 → available=False。
    """
    out: dict[str, Any] = {"available": False, "source": rel_file,
                           "states": [], "counts": {}}
    if not rel_file:
        return out
    import json

    path = RUNS_ROOT / rel_file
    if not path.is_file():
        return out
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return out
    states: list[str] = []
    pm = doc.get("per_metric") if isinstance(doc, dict) else None
    if isinstance(pm, list):
        states = [str(m.get("state")) for m in pm
                  if isinstance(m, dict) and m.get("state")]
    agree = sum(1 for s in states if s.startswith("AGREE"))
    disagree = sum(1 for s in states if s.startswith("DISAGREE"))
    unknown = sum(1 for s in states if s.startswith("UNKNOWN"))
    out.update({
        "available": True, "source": f"runs/{rel_file}", "states": states,
        "counts": {"agree": agree, "disagree": disagree,
                   "unknown": unknown, "total": len(states)},
    })
    return out


# ── 对外面（service 层 JSON 进出，规则 4）───────────────────────────────


def credibility_curves(model: str | None = None) -> dict[str, Any]:
    """双引擎对照曲线族组装（JSON 进出信封，只读）。

    Args:
        model: 模板族名（registered_families() 同名空间；None=全族
            可用性总览——前端画廊抽屉"对照"标签页清单面）。存量 run
            旧模型名（wilkinson_power_divider 等 P0–P6 三族，见
            _MODEL_ALIASES）归一到现行族后匹配。

    Returns:
        model=None → ok 信封：families=[{template, engines 可用性,
        pairing_state, verdict_counts}]（逐族实时在盘探测，零缓存——
        证据湖是归档静态面，探测为 10 族 ×2 次 isfile 量级）。
        model 命中 → ok 信封：engines.{hfss,openems} 曲线族
        （freq_ghz[]+curves[].s_db[]）+ pairing 偏差注记 + verdict 汇总
        + provenance 路径指针；OE 侧缺席 → 单引擎+如实 note（不虚构）。
        model 未注册 → **诚实空信封**：ok=True、engines 空、notes 说明、
        available_templates 供前端引导（未知模板不是错误，是"暂无数据"
        的如实态；乱路径名在此不触盘，零穿越面）。
    """
    if model is None:
        families = []
        for f in _FAMILIES:
            hfss_ok = bool(f["hfss_file"]) and (
                RUNS_ROOT / str(f["hfss_file"])).is_file()
            oe_ok = bool(f["oe_file"]) and (
                RUNS_ROOT / str(f["oe_file"])).is_file()
            verdict = _verdict_summary(
                str(f["verdict_file"]) if f["verdict_file"] else None)
            families.append({
                "template": str(f["template"]),
                "engines": {"hfss": hfss_ok, "openems": oe_ok},
                "pairing_state": ("paired" if hfss_ok and oe_ok
                                  else "single_engine"),
                "verdict_counts": verdict.get("counts") or {},
            })
        n_paired = sum(1 for x in families
                       if x["pairing_state"] == "paired")
        return ok_envelope(
            schema_version=CREDIBILITY_CURVES_SERVICE_SCHEMA_VERSION,
            count=len(families),
            n_paired=n_paired,
            n_single_engine=len(families) - n_paired,
            families=families,
            notes=[
                "曲线级配对=双引擎 S 曲线都在盘且同一名义设计"
                "（R3 §1.2 口径）；single_engine=仅 HFSS 侧在盘",
                "证据零改写：本面纯只读（R3 §5，#325/#326）",
            ])

    key = _normalize_model_alias(model)
    entry = next((f for f in _FAMILIES
                  if str(f["template"]).lower() == key), None)
    if entry is None:
        return ok_envelope(
            schema_version=CREDIBILITY_CURVES_SERVICE_SCHEMA_VERSION,
            model=str(model),
            engines={},
            pairing=None,
            verdict=None,
            count=0,
            available_templates=registered_families(),
            notes=[f"模板 {model!r} 无对照曲线注册数据（诚实空态——"
                   "不虚构曲线；已注册族见 available_templates）"])

    notes: list[str] = []
    hfss = _engine_payload(str(entry["hfss_file"]), "hfss")
    if not hfss["available"]:
        notes.append(f"HFSS 侧不可用：{hfss['note']}")
    oe_rel = entry["oe_file"]
    oe = _engine_payload(str(oe_rel), "openems") if oe_rel else {
        "available": False, "source": None, "n_ports": None,
        "n_points": 0, "freq_ghz": [], "curves": [],
        "omitted_filled": [], "mask_note": None, "note": None,
    }
    if not oe["available"]:
        note = (entry.get("oe_note")
                or (oe["note"] if oe_rel else "无 OE 曲线登记"))
        notes.append(f"openEMS 侧不可用：{note}")
    if oe["mask_note"]:
        notes.append(oe["mask_note"])
    pairing = _pair_curves(hfss, oe)
    verdict = _verdict_summary(
        str(entry["verdict_file"]) if entry["verdict_file"] else None)
    if verdict["available"] and verdict["counts"].get("disagree"):
        notes.append(
            "verdict 含 DISAGREE 态（如实呈现不隐藏，#122）："
            f"{[s for s in verdict['states'] if s.startswith('DISAGREE')]}")
    return ok_envelope(
        schema_version=CREDIBILITY_CURVES_SERVICE_SCHEMA_VERSION,
        model=str(entry["template"]),
        engines={"hfss": hfss, "openems": oe},
        pairing=pairing,
        verdict=verdict,
        provenance={
            "hfss": hfss["source"],
            "openems": oe["source"],
            "verdict": verdict["source"],
            "runs_root": "runs/",
        },
        notes=notes,
    )

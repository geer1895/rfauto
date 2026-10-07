"""F-C P2：器件老化漂移 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/aging.py 内核（F-C.1 P1 已落地；本服务零物理公式，全部数字出自
确定性内核，规则 7）+ knowledge/aging_laws.yaml 材料老化律注册表（P1 批，
本服务按 laws_material 查表）。三入口（方案
研究扩充 F-C §2 P2 段）：

- :func:`aging_simulate`：模板名义几何 + 任务剖面 + 材料 → εr 漂移轨迹 +
  fake 通道名义/EOL 两点 S 参数重算 + 失谐量 detune_pct；
- :func:`aging_eol_verdict`：失谐量 vs 规范（spec_pct/spec_ppm）→ 纯确定性
  PASS/FAIL（恰等 spec 判 PASS，ge1③ 恰等容差口径）；
- :func:`aging_report`：simulate 结果 + 判据 + 剖面表组装成报告 dict
  （sections：mission_profile 表/漂移轨迹/EOL 判据/法源 provenance）。

**fake 通道 εr 敏感性与等效伸缩编码（2026-09-26 实测登记）**：fake 解析
模型**不直接消费 er 设计变量**（er 只经 substrate 名→materials.yaml
stackup 进入，见 adapters/fake_adapter.py solve() 各分支）；但谐振族的
谷位随谐振长度变量精确 ∝1/L 移动（wilkinson/dipole/patch 实测，branchline
谷在缺省带外）。故 v1 漂移重算用**等效长度伸缩**：εr 漂移 er0→er_eol 对
谐振位置的一阶影响 εeff(εr)=1+q·(εr−1)（q=fill_fraction，缺省 1.0=全填充
上界口径）经 f0∝1/√εeff 折成等效长度 L_eol=L_nom·√(εeff_eol/εeff_nom)，
用同一 fake 响应面（同 seed 独立实例=同噪声实现）重解两点——S 参数形态
不变仅频移，是**一阶等效重算**而非真机重算（真机通道=P3）。

**诚实边界（预声明，先写后跑）**：
1. er_aging 状态 awaiting_data 的材料（laminate_fr4/ceramic_alumina_99p6/
   laminate_ro4350b 等）→ ok=False 不产任何数字（knowledge 只读，按表
   如实拒绝；任务书草稿"alumina/FR4 typical"与 yaml 实态不符，以 yaml 为准）；
2. arrhenius awaiting_data（ceramic_class2_x7r）仅当剖面**全程恒温于
   t_use_c** 时可用（此时 AF≡1 与 Ea 无关，ea_ev=0.0 只作内核占位并在
   provenance 显式标注 isothermal_at_use）；剖面含非使用温度段 → ok=False；
3. engine 仅支持 "fake"；其他值 ok=False 显式 unsupported；
4. 本链是 **EOL 漂移上界估计，非认证寿命结论**（多机理耦合 UNKNOWN，
   F-C §4 风险②④，措辞钉进 report.disclaimer）；
5. v1 仅支持谐振族 fake 模型（长度驱动谷位：wilkinson/branchline/patch/
   dipole/hairpin/hairpin_alt）；传输线族（mline/cpw/cps/...）与未注册
   模板如实 ok=False。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from rfauto.core import aging
from rfauto.service._helpers import (
    err_envelope as _err,
)
from rfauto.service._helpers import (
    parse_num as _num,
)
from rfauto.service._helpers import (
    require_payload_dict as _require_payload_dict,
)
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
AGING_SERVICE_SCHEMA_VERSION = "1.0"

#: v1 唯一合法引擎（openEMS/HFSS 通道=P3）
AGING_ENGINE_FAKE = "fake"

#: aging_laws.yaml（knowledge 只读；与 knowledge_service._KNOWLEDGE_DIR 同源口径）
_AGING_LAWS_PATH = Path(__file__).resolve().parents[3] / "knowledge" / "aging_laws.yaml"

#: 谐振族 fake 模型 → 谐振长度变量候选（与 adapters/fake_adapter.py solve()
#: 各分支消费的谐振长度变量同步，#154 同名同语义；mline/cpw 等 TL 族的
#: line_len 是相位长度不是谐振长度，不进本表）
_FAKE_RESONATOR_VARS: dict[str, tuple[str, ...]] = {
    "wilkinson": ("arm_len_mm", "arm_len"),
    "branchline": ("arm_len_mm", "arm_len"),
    "patch": ("patch_len_mm", "patch_len"),
    "dipole": ("dipole_len_mm",),
    "hairpin": ("arm_len_mm", "arm_len"),
    "hairpin_alt": ("arm_len_mm", "arm_len"),
}

#: 谐振族 fake 模型端口数（与 service/level2_design.py _N_PORTS 同源口径；
#: patch/dipole 单馈 1 端口）
_FAKE_N_PORTS: dict[str, int] = {
    "wilkinson": 3,
    "branchline": 4,
    "patch": 1,
    "dipole": 1,
    "hairpin": 2,
    "hairpin_alt": 2,
}

#: 缺省频率轴（GHz）(start, stop, npts)——宽带覆盖Supported族谷位
#: （dipole λ/2 ~2.6GHz@58mm、wilkinson 谷 ~2.2GHz@17.2mm，branchline 谷
#: 在 4GHz 以上），payload.freq_ghz 可覆盖
_DEFAULT_FREQ_GHZ = (0.5, 6.0, 551)

#: 年 → 秒（儒略年口径，与 astropy/julian year 一致）
_S_PER_YEAR = 365.25 * 86400.0

#: 恒温判定容差（°C）：|t_c − t_use_c| ≤ 此值视为使用温度段
_ISOTHERMAL_TOL_C = 1e-9


# ─── payload 解析助手（字段错误收集进 errors，不抛出） ────────────────────────
# S2-8 单源化（review_ge8e 2026-10-04）：_require_payload_dict/_num/_err
# 本地近逐字节拷贝已删净（#116），单源在 service._helpers（import 别名直引，
# 调用点零改动）；本服务 _err 无版本戳口径（= error_envelope 同形）。


# ─── aging_laws.yaml 查表 ─────────────────────────────────────────────────────


def _load_laws_registry() -> list[dict[str, Any]]:
    """读 knowledge/aging_laws.yaml materials 列表（只读；解析失败显式抛出）。"""
    import yaml

    raw = _AGING_LAWS_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict) or not isinstance(data.get("materials"), list):
        raise ValueError(f"{_AGING_LAWS_PATH} 缺 materials 列表")
    return data["materials"]


def _find_material(material_id: str) -> dict[str, Any] | None:
    for entry in _load_laws_registry():
        if isinstance(entry, dict) and entry.get("material_id") == material_id:
            return entry
    return None


# ─── εr 漂移 → 等效 εeff/失谐（一阶映射，服务层确定性函数） ──────────────────


def eps_eff_of(er: float, fill_fraction: float) -> float:
    """一阶等效介电常数 εeff(εr) = 1 + q·(εr−1)。

    q=fill_fraction（介质填充份额，(0,1]，缺省 1.0=全填充上界口径——
    本链定位漂移上界工具，上界口径保守可辩护）；q<1 时贴近空气-介质
    混合的一阶线性内插。
    """
    return 1.0 + fill_fraction * (er - 1.0)


def detune_pct_of_er_drift(
    er0: float, er_eol: float, fill_fraction: float = 1.0
) -> float:
    """εr 漂移 → 谐振频率相对失谐（%，f0∝1/√εeff 一阶口径）。

    εr 上升 → εeff 上升 → f0 下降（物理方向单调）；X7R 类 er 衰减材料
    给正失谐（f0 上移）。纯函数，无 IO。
    """
    if er0 <= 0.0 or er_eol <= 0.0:
        raise ValueError("er0/er_eol 必须 >0")
    q = fill_fraction
    if not (0.0 < q <= 1.0):
        raise ValueError("fill_fraction 必须 ∈ (0,1]")
    eps_nom = eps_eff_of(er0, q)
    eps_eol = eps_eff_of(er_eol, q)
    return (math.sqrt(eps_nom / eps_eol) - 1.0) * 100.0


# ─── fake 通道两点重算（等效长度伸缩编码，同 seed 独立实例） ──────────────────


def _variable_strings(params: dict[str, Any]) -> dict[str, str]:
    """名义几何 → 适配器变量串。

    S2-8③ 漂移勘误（review_ge8e 2026-10-04）：docstring 原称"与
    level2_design._variable_strings 同口径"已漂移不实——level2 跳过
    f0_ghz（f0 走适配器 init 不作变量），本链 f0_ghz 保留为变量串
    （fake 频轴消费）；bool 均经 str() 落串。同名同语义纪律（#154）：
    消费前先对语义，不改实体行为。
    """
    out: dict[str, str] = {}
    for key, value in params.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = f"{value}mm" if str(key).endswith("_mm") else str(value)
        else:
            out[key] = str(value)
    return out


def _resolve_resonator_len(
    params: dict[str, Any], candidates: tuple[str, ...]
) -> tuple[str, float] | None:
    """在 params 里定位谐振长度变量（候选名+_mm 后缀省略变体，与
    physics_roles.resolve_role 同一匹配语义），返回 (变量名, 数值)；未命中
    返回 None（调用方 ok=False，不静默回退缺省——漂移编码必须有真柄）。"""
    for name in candidates:
        for key in (name, name[:-3] if name.endswith("_mm") else f"{name}_mm"):
            if key in params:
                probe_errors: list[str] = []
                parsed = _num(params[key], f"params.{key}", probe_errors)
                if parsed is not None and parsed > 0.0:
                    return key, parsed
                # 存在但非法（非数值/≤0）≠ 缺失——缺与坏必须分开报（审查轨 C P2-6）
                shown = probe_errors[0] if probe_errors else repr(params[key])
                raise ValueError(
                    f"params.{key} 存在但非法（{shown}），"
                    "非缺失——请修正数值而非补参数")
    return None


def _solve_fake_once(
    model_type: str,
    variables: dict[str, str],
    freq_ghz: tuple[float, float, int],
    n_ports: int,
    f0_ghz: float,
) -> Any:
    """同 seed 独立 FakeAdapter 实例求解一次（确定性：两次调用同噪声实现，
    曲线差异只来自频移）。返回 skrf.Network。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    adapter = FakeAdapter(
        model_type=model_type, freq_ghz=freq_ghz, n_ports=n_ports,
        f0_ghz=f0_ghz, seed=42,
    )
    adapter.connect({})
    adapter.set_variables(dict(variables))
    report = adapter.solve("aging_service_chain")
    if not report.success:
        raise RuntimeError(f"fake 求解失败: {report.message}")
    return adapter.get_sparams()


def _f_dip_ghz(network: Any) -> float:
    """|S11| 谷位（GHz，argmin dB——#195 谷深语义的谷位口径）。"""
    import numpy as np

    freq_ghz = np.asarray(network.frequency.f, dtype=float) * 1e-9
    s11_db = 20.0 * np.log10(np.abs(network.s[:, 0, 0]) + 1e-30)
    return float(freq_ghz[int(np.argmin(s11_db))])


def _sparams_to_json(network: Any) -> dict[str, Any]:
    """网络 → JSON 数组面（f_ghz + 逐端口 |S|dB；端口数自适应）。"""
    import numpy as np

    freq_ghz = np.asarray(network.frequency.f, dtype=float) * 1e-9
    s = np.asarray(network.s)
    n_ports = s.shape[1]
    out: dict[str, Any] = {"f_ghz": [float(v) for v in freq_ghz]}
    for i in range(n_ports):
        for j in range(n_ports):
            mag_db = 20.0 * np.log10(np.abs(s[:, i, j]) + 1e-30)
            out[f"s{i + 1}{j + 1}_db"] = [float(v) for v in mag_db]
    return out


# ─── 1. aging_simulate ───────────────────────────────────────────────────────


def aging_simulate(payload: Any) -> dict[str, Any]:
    """老化漂移仿真：任务剖面 → εr 漂移轨迹 → fake 通道名义/EOL 两点重算。

    Args（payload 键）:
        template: 模板注册名（models/registry，如 "branchline_coupler"）；
        params: 名义几何 dict（必含所选 fake 模型的谐振长度变量）；
        mission_profile: [{"t_s": 秒, "t_c": °C, "delta_t_c"?, "j_density"?},
            ...]（透传 core.profile_integrate）；
        lifetime_years 或 t_total_s: 寿命终点（二选一）；
        laws_material: knowledge/aging_laws.yaml material_id；
        er0: 名义 εr（>0）；t_use_c: 使用温度（°C）；
        engine: 缺省 "fake"（v1 唯一合法值）；
        fill_fraction: (0,1] 缺省 1.0（全填充上界口径）；
        freq_ghz: [start, stop, npts] 可覆盖缺省频率轴；
        n_ports: 可覆盖族缺省端口数；f0_ghz: 适配器 init 中心频率可覆盖。

    Returns:
        dict: {ok, er_drift_curve, drift, eps_eff, s_params_nominal,
        s_params_eol, f_dip_ghz, detune_pct（实测）, detune_pct_predicted,
        damage, failed, mission_profile, laws_provenance}；材料 awaiting/
        引擎不支持/参数缺失 → ok=False errors（不产数字）。
    """
    errors: list[str] = []
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        # F-11/S3：非 dict payload 收敛为失败信封（glass_weave_skew_service
        # 同款 try 收敛）——原裸 raise 与全模块「ok/errors 不抛穿」口径相悖。
        return _err([str(exc)])

    engine = p.get("engine", AGING_ENGINE_FAKE)
    if engine != AGING_ENGINE_FAKE:
        return _err([f"engine={engine!r} unsupported（v1 仅 '{AGING_ENGINE_FAKE}'；"
                     "openEMS/HFSS 老化通道属 P3）"])

    template = p.get("template")
    if not isinstance(template, str) or not template:
        return _err(["template 缺失（模型注册名，如 'branchline_coupler'）"])
    from rfauto.models.registry import get as get_plugin

    try:
        plugin_cls = get_plugin(template)
    except (KeyError, ImportError) as exc:
        return _err([f"template {template!r} 未注册: {exc}"])
    model_type = getattr(plugin_cls, "fake_model_type", "")
    if model_type not in _FAKE_RESONATOR_VARS:
        return _err([
            f"template {template!r} 的 fake 模型 {model_type!r} v1 不支持"
            f"（仅谐振族 {sorted(_FAKE_RESONATOR_VARS)}；长度驱动谷位）"
        ])

    params = p.get("params")
    if not isinstance(params, dict):
        return _err(["params 缺失（名义几何 dict）"])
    span = _resolve_resonator_len(params, _FAKE_RESONATOR_VARS[model_type])
    if span is None:
        return _err([
            f"params 缺谐振长度变量（候选 {_FAKE_RESONATOR_VARS[model_type]}）"
            "——等效伸缩编码必须有真柄，不静默回退"
        ])
    len_key, len_nom = span

    profile = p.get("mission_profile")
    if not isinstance(profile, list) or not profile:
        return _err(["mission_profile 缺失或为空"])

    lifetime_years = p.get("lifetime_years")
    t_total_in = p.get("t_total_s")
    t_total: float | None = None
    if lifetime_years is not None and t_total_in is not None:
        return _err(["lifetime_years 与 t_total_s 二选一"])
    if lifetime_years is not None:
        t_total = _num(lifetime_years, "lifetime_years", errors, positive=True)
        if t_total is not None:
            t_total = t_total * _S_PER_YEAR
    elif t_total_in is not None:
        t_total = _num(t_total_in, "t_total_s", errors, positive=True)
    else:
        errors.append("lifetime_years 与 t_total_s 至少给一个")
    if errors:
        return _err(errors)

    er0 = _num(p.get("er0"), "er0", errors, positive=True)
    t_use_c = _num(p.get("t_use_c"), "t_use_c", errors)
    fill_fraction = _num(p.get("fill_fraction", 1.0), "fill_fraction", errors,
                         positive=True)
    if fill_fraction is not None and fill_fraction > 1.0:
        errors.append(f"fill_fraction 必须 ∈ (0,1]，实际 {fill_fraction}")
    if errors:
        return _err(errors)

    material_id = p.get("laws_material")
    if not isinstance(material_id, str) or not material_id:
        return _err(["laws_material 缺失（aging_laws.yaml material_id）"])
    try:
        material = _find_material(material_id)
    except (OSError, ValueError) as exc:
        return _err([f"aging_laws.yaml 不可读: {exc}"])
    if material is None:
        return _err([f"laws_material {material_id!r} 未注册于 aging_laws.yaml"])
    er_law = material.get("er_aging") or {}
    ar_law = material.get("arrhenius") or {}
    laws_provenance: dict[str, Any] = {
        "source": str(_AGING_LAWS_PATH),
        "schema": "aging_laws/v1",
        "material_id": material_id,
        "description": material.get("description"),
        "er_aging": {
            "status": er_law.get("status"),
            "provenance": er_law.get("provenance"),
            "reason": er_law.get("reason"),
            "single_source": er_law.get("single_source"),
        },
        "arrhenius": {
            "status": ar_law.get("status"),
            "provenance": ar_law.get("provenance"),
            "reason": ar_law.get("reason"),
        },
    }
    # 诚实边界①：er 老化律 awaiting_data → 不产数字（先例 knowledge/anchors）
    if er_law.get("status") != aging.LAW_STATUS_TYPICAL:
        return error_envelope(
            [
                f"laws_material {material_id!r} 的 er_aging 状态="
                f"{er_law.get('status')!r}（awaiting_data 不产数字）："
                f"{er_law.get('reason')}"
            ],
            laws_provenance=laws_provenance,
        )
    frac = _num(er_law.get("frac_per_decade"), "frac_per_decade", errors)
    t_ref_h = _num(er_law.get("t_ref_h", 1.0), "t_ref_h", errors, positive=True)
    if t_ref_h is not None and t_ref_h != 1.0:
        errors.append("service v1 仅支持 t_ref_h=1.0（与 core.profile_integrate 口径一致）")
    if errors:
        return _err(errors)

    # 诚实边界②：arrhenius awaiting → 仅恒温于使用温度的剖面可用（AF≡1）
    isothermal_at_use = False
    if ar_law.get("status") == aging.LAW_STATUS_TYPICAL:
        ea_ev = _num(ar_law.get("ea_ev"), "ea_ev", errors, nonneg=True)
    else:
        try:
            all_at_use = all(
                isinstance(seg, dict)
                and seg.get("t_c") is not None
                and abs(float(seg["t_c"]) - t_use_c) <= _ISOTHERMAL_TOL_C
                for seg in profile
            )
        except (TypeError, ValueError) as exc:
            return _err([f"mission_profile.t_c 非数值: {exc}"])
        if not all_at_use:
            return error_envelope(
                [
                    f"laws_material {material_id!r} 的 arrhenius 状态="
                    f"{ar_law.get('status')!r} 且剖面含非使用温度段——等效时间"
                    f"折算需 Ea，不产数字：{ar_law.get('reason')}"
                ],
                laws_provenance=laws_provenance,
            )
        ea_ev = 0.0
        isothermal_at_use = True
    laws_provenance["isothermal_at_use"] = isothermal_at_use
    if isothermal_at_use:
        laws_provenance["isothermal_note"] = (
            "剖面全程恒温于 t_use_c，AF≡1 与 Ea 无关；ea_ev=0.0 仅为内核占位"
        )
    if errors:
        return _err(errors)

    laws_core = {
        "t_use_c": t_use_c,
        "ea_ev": ea_ev,
        "er0": er0,
        "aging_frac_per_decade": frac,
    }
    try:
        integ = aging.profile_integrate(profile, laws_core, t_total_s=t_total)
    except (KeyError, TypeError, ValueError) as exc:
        return _err([f"任务剖面积分失败: {exc}"])

    er_eol = float(integ["drift"]["er_eol"])
    eps_nom = eps_eff_of(er0, fill_fraction)
    eps_eol = eps_eff_of(er_eol, fill_fraction)
    g = math.sqrt(eps_eol / eps_nom)
    detune_pred = detune_pct_of_er_drift(er0, er_eol, fill_fraction)

    freq_in = p.get("freq_ghz")
    if freq_in is not None:
        if (
            not isinstance(freq_in, (list, tuple))
            or len(freq_in) != 3
            or any(_num(v, "freq_ghz[]", errors) is None for v in freq_in)
        ):
            return _err(["freq_ghz 须为 [start, stop, npts]"])
        freq_axis = (float(freq_in[0]), float(freq_in[1]), int(freq_in[2]))
    else:
        freq_axis = _DEFAULT_FREQ_GHZ
    n_ports = p.get("n_ports")
    if n_ports is None:
        n_ports = _FAKE_N_PORTS[model_type]
    if isinstance(n_ports, bool):
        return _err(["n_ports 不接受布尔值（df7+⑯）"])
    n_ports = int(n_ports)
    f0_init = _num(p.get("f0_ghz", 2.4), "f0_ghz", errors, positive=True)
    if errors:
        return _err(errors)

    variables = _variable_strings(params)
    try:
        net_nom = _solve_fake_once(model_type, variables, freq_axis, n_ports, f0_init)
        variables[len_key] = f"{len_nom * g}mm"
        net_eol = _solve_fake_once(model_type, variables, freq_axis, n_ports, f0_init)
    except (RuntimeError, ValueError, KeyError) as exc:
        return _err([f"fake 通道重算失败: {exc}"])

    f_dip_nom = _f_dip_ghz(net_nom)
    f_dip_eol = _f_dip_ghz(net_eol)
    detune_meas = (f_dip_eol / f_dip_nom - 1.0) * 100.0

    return ok_envelope(
        schema_version=AGING_SERVICE_SCHEMA_VERSION,
        engine=AGING_ENGINE_FAKE,
        template=template,
        model_type=model_type,
        laws_material=material_id,
        t_total_s=integ["t_total_s"],
        t_equivalent_s=integ["t_equivalent_s"],
        t_equivalent_h=integ["t_equivalent_h"],
        er_drift_curve=[
            {"t_s": pt["t1_s"], "er": pt["er_t"],
             "drift_frac": float(pt["er_t"]) / er0 - 1.0}
            for pt in integ["trajectory"]
        ],
        drift=integ["drift"],
        eps_eff={
            "nominal": eps_nom,
            "eol": eps_eol,
            "fill_fraction": fill_fraction,
            "model": "1 + q*(er-1)（一阶填充口径，q=1 全填充上界）",
        },
        s_params_nominal=_sparams_to_json(net_nom),
        s_params_eol=_sparams_to_json(net_eol),
        f_dip_ghz={"nominal": f_dip_nom, "eol": f_dip_eol},
        detune_pct=detune_meas,
        detune_pct_predicted=detune_pred,
        damage=integ["damage"],
        failed=integ["failed"],
        mission_profile=profile,
        laws_provenance=laws_provenance,
    )


# ─── 2. aging_eol_verdict ────────────────────────────────────────────────────


def aging_eol_verdict(payload: Any) -> dict[str, Any]:
    """EOL 失谐判据：|detune_pct| ≤ spec → PASS（恰等判 PASS，ge1③ 口径）。

    Args（payload 键）:
        detune_pct: 失谐量（%，可直接给）；或 simulate/simulate_result:
            aging_simulate 结果 dict（取其 detune_pct）；
        spec_pct 或 spec_ppm: 频率容差规范（二选一；ppm = 百万分之一）。

    Returns:
        dict: {ok, verdict: PASS|FAIL, detune_pct, detune_ppm, spec_pct,
        spec_ppm, margin_pct}；纯确定性，无随机无网络。
    """
    errors: list[str] = []
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        # F-11/S3：非 dict payload 收敛为失败信封（同 aging_simulate 口径）。
        return _err([str(exc)])

    detune: float | None = None
    if p.get("detune_pct") is not None:
        detune = _num(p.get("detune_pct"), "detune_pct", errors)
    else:
        for wrap_key in ("simulate", "simulate_result"):
            inner = p.get(wrap_key)
            if isinstance(inner, dict) and inner.get("detune_pct") is not None:
                detune = _num(inner.get("detune_pct"),
                              f"{wrap_key}.detune_pct", errors)
                break
    spec_pct: float | None = None
    spec_ppm: float | None = None
    if p.get("spec_pct") is not None:
        spec_pct = _num(p.get("spec_pct"), "spec_pct", errors, nonneg=True)
    if p.get("spec_ppm") is not None:
        spec_ppm = _num(p.get("spec_ppm"), "spec_ppm", errors, nonneg=True)
    if spec_pct is not None and spec_ppm is not None:
        return _err(["spec_pct 与 spec_ppm 二选一"])
    if spec_pct is None and spec_ppm is None:
        errors.append("spec_pct 与 spec_ppm 至少给一个")
    if errors or detune is None:
        return _err(errors or ["detune_pct 缺失（或 simulate 结果未给）"])
    if spec_pct is None:
        spec_pct = spec_ppm / 1e4

    margin = spec_pct - abs(detune)
    return ok_envelope(
        schema_version=AGING_SERVICE_SCHEMA_VERSION,
        gate="aging_eol_detune",
        verdict="PASS" if abs(detune) <= spec_pct else "FAIL",
        criterion="|detune_pct| <= spec_pct（恰等判 PASS，ge1③ 恰等容差口径）",
        detune_pct=detune,
        detune_ppm=detune * 1e4,
        spec_pct=spec_pct,
        spec_ppm=spec_pct * 1e4,
        margin_pct=margin,
    )


# ─── 3. aging_report ─────────────────────────────────────────────────────────

#: 措辞钉（F-C §4 风险④：夸大预期防御——非认证寿命结论）
_AGING_DISCLAIMER = (
    "EOL 漂移上界估计（PoF 一阶模型），非认证寿命结论；多机理耦合项 "
    "UNKNOWN（v1 独立叠加口径）；fake 通道为等效伸缩一阶重算，非真机重算"
)


def aging_report(payload: Any) -> dict[str, Any]:
    """组装老化报告 dict（mission_profile 表/漂移轨迹/EOL 判据/法源 provenance）。

    Args（payload 键）:
        simulate_result: aging_simulate 的结果 dict（直接内嵌）；或
            simulate_payload: 现场先跑 aging_simulate；
        spec_pct 或 spec_ppm: 可选——给出则产出 EOL 判据节，缺省判据节
            verdict=UNKNOWN（如实，不冒充）。

    Returns:
        dict: {ok, template, disclaimer, sections: {mission_profile,
        drift_trajectory, eol_verdict, provenance}}。
    """
    errors: list[str] = []
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        # F-11/S3：非 dict payload 收敛为失败信封（同 aging_simulate 口径）。
        return _err([str(exc)])

    sim = p.get("simulate_result")
    if not isinstance(sim, dict) or not sim.get("ok"):
        sim_payload = p.get("simulate_payload")
        if sim_payload is None:
            return _err(["simulate_result（含 ok=True）与 simulate_payload 至少给一个"])
        sim = aging_simulate(sim_payload)
        if not sim.get("ok"):
            return error_envelope([f"simulate 失败: {sim.get('errors')}"], sections=None)

    spec_pct: float | None = None
    spec_ppm: float | None = None
    if p.get("spec_pct") is not None:
        spec_pct = _num(p.get("spec_pct"), "spec_pct", errors, nonneg=True)
    if p.get("spec_ppm") is not None:
        spec_ppm = _num(p.get("spec_ppm"), "spec_ppm", errors, nonneg=True)
    if errors:
        return _err(errors)
    verdict: dict[str, Any]
    if spec_pct is not None or spec_ppm is not None:
        v_in: dict[str, Any] = {"detune_pct": sim.get("detune_pct")}
        if spec_pct is not None:
            v_in["spec_pct"] = spec_pct
        if spec_ppm is not None:
            v_in["spec_ppm"] = spec_ppm
        verdict = aging_eol_verdict(v_in)
    else:
        verdict = {
            "ok": True,
            "verdict": "UNKNOWN",
            "reason": "payload 未给 spec_pct/spec_ppm——不设规范则不判",
        }

    profile_rows: list[dict[str, Any]] = []
    for idx, seg in enumerate(sim.get("mission_profile") or []):
        if isinstance(seg, dict):
            profile_rows.append({
                "seg": idx,
                "t_s": seg.get("t_s"),
                "t_c": seg.get("t_c"),
                "delta_t_c": seg.get("delta_t_c"),
                "j_density": seg.get("j_density"),
            })

    curve = sim.get("er_drift_curve") or []
    provenance_in = sim.get("laws_provenance") or {}

    return ok_envelope(
        schema_version=AGING_SERVICE_SCHEMA_VERSION,
        template=sim.get("template"),
        engine=sim.get("engine"),
        disclaimer=_AGING_DISCLAIMER,
        sections={
            "mission_profile": {
                "columns": ["seg", "t_s", "t_c", "delta_t_c", "j_density"],
                "rows": profile_rows,
                "t_total_s": sim.get("t_total_s"),
                "t_equivalent_s": sim.get("t_equivalent_s"),
            },
            "drift_trajectory": {
                "t_s": [pt.get("t_s") for pt in curve],
                "er": [pt.get("er") for pt in curve],
                "drift_frac": [pt.get("drift_frac") for pt in curve],
                "er0": (sim.get("drift") or {}).get("er0"),
                "er_eol": (sim.get("drift") or {}).get("er_eol"),
                "detune_pct": sim.get("detune_pct"),
                "detune_pct_predicted": sim.get("detune_pct_predicted"),
            },
            "eol_verdict": verdict,
            "provenance": {
                "laws_source": provenance_in.get("source"),
                "laws_schema": provenance_in.get("schema"),
                "material_id": provenance_in.get("material_id"),
                "er_aging": provenance_in.get("er_aging"),
                "arrhenius": provenance_in.get("arrhenius"),
                "isothermal_at_use": provenance_in.get("isothermal_at_use"),
                "isothermal_note": provenance_in.get("isothermal_note"),
                "kernel": "rfauto.core.aging（F-C.1；三律+Miner+profile_integrate）",
                "disclaimer": _AGING_DISCLAIMER,
            },
        },
    )

"""uq_yield_at/robustness_report/uq_design_center/uq_temperature_zone（WP4.2 良率/稳健性）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 24. 公差/良率收口（WP4.2，0bw① 薄壳） ───────────────────────────────────

@mcp.tool
def uq_yield_at(
    samples_path: str,
    tolerances: dict[str, float],
    nominal: dict[str, float],
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
) -> dict[str, Any]:
    """名义点良率（uq 域）：代理 MC 抽样 → 良率点值（确定性 seed 复现）。

    无副作用（只读校准样本集）；代理估计面不替代真机复验。样本集缺失/
    公差参数未覆盖 → ok=False 如实。只读无时序约束。

    Args:
        samples_path: 校准样本集 samples.json
        tolerances: 公差 σ {参数名: σ}
        nominal: 名义点（须覆盖全部公差参数）
        n: 蒙特卡洛抽样数
        seed: 随机种子
        kind: 代理类型 poly_ridge|nn

    Returns:
        dict: {ok, yield_rate, metric_stats, nominal_params, ...}；样本集
        缺失 → ok=False
    """
    from rfauto.service.uq_service import surrogate_yield_at
    return surrogate_yield_at(samples_path, tolerances, nominal, n=n, seed=seed,
                              kind=kind)


@mcp.tool
def robustness_report(
    source: str,
    specs: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
    tolerances: dict[str, float] | None = None,
    n_mc: int = 100000,
    seed: int = 42,
    kind: str = "poly_ridge",
    form_engine: str = "auto",
    persist: bool = False,
    store_name: str | None = None,
) -> dict[str, Any]:
    """稳健性报告（uq 域）：良率 MC+FORM Pf+worst-case 角点+逐规范 Cpk。

    只读消费数据集/run/samples.json（persist=True 时写 Parquet 数据集，
    为唯一写面）；代理/闭式估计面不替代真机复验。源缺失/规范非法 →
    ok=False 如实。只读无时序约束。

    Args:
        source: samples.json 路径 | 数据集名 | run id
        specs: 规范限列表 [{metric, op, value, weight?}]（op: max_below|min_above 等）
        profile: 公差剖面 dict（load_tolerance_profile schema，优先于 tolerances）
        tolerances: 公差 σ {参数名: σ}（无 profile 时生效）
        n_mc: MC 抽样数
        seed: 随机种子
        kind: 代理类型 poly_ridge|nn
        form_engine: FORM 引擎 auto|internal|openturns|uqpy
        persist: MC 抽样落盘 Parquet
        store_name: 落盘数据集名

    Returns:
        dict: {ok, yield_mc, form, worst_case, cpk, uncertainty_status, ...}
    """
    from rfauto.service.robustness_service import robustness_report
    return robustness_report(source, specs, profile=profile, tolerances=tolerances,
                             n_mc=n_mc, seed=seed, kind=kind,
                             form_engine=form_engine, persist=persist,
                             store_name=store_name)


@mcp.tool
def uq_design_center(
    samples_path: str,
    tolerances: dict[str, float],
    k_sigma: float = 3.0,
    n_levels: int = 3,
    max_iter: int = 40,
    n_mc: int = 2000,
    seed: int = 42,
    kind: str = "poly_ridge",
) -> dict[str, Any]:
    """设计中心化（uq 域）：容差盒网格违约 cost → 坐标搜索名义点。

    良率目标函数+设计中心化（容差盒网格违约 cost≤0 良率，坐标搜索）。
    无副作用（只读校准样本集；MC 只做前后认证不入环）；代理估计面不
    替代真机复验。样本集缺失 → ok=False 如实。只读无时序约束。

    Args:
        samples_path: 校准样本集 samples.json
        tolerances: 公差 σ {参数名: σ}
        k_sigma: 容差盒半宽 = k_sigma·σ
        n_levels: 每维网格层数
        max_iter: 坐标搜索最大迭代
        n_mc: 前后认证 MC 抽样数
        seed: 随机种子
        kind: 代理类型 poly_ridge|nn

    Returns:
        dict: YieldDesignCenterPayload 契约 + contract_check
    """
    from rfauto.service.contracts import annotate_contract
    from rfauto.service.uq_service import yield_design_center
    return annotate_contract("yield_design_center", yield_design_center(
        samples_path, tolerances, k_sigma=k_sigma, n_levels=n_levels,
        max_iter=max_iter, n_mc=n_mc, seed=seed, kind=kind))


@mcp.tool
def uq_temperature_zone(
    samples_path: str,
    env_key: str,
    tolerances: dict[str, float] | None = None,
    t_ref_c: float | None = None,
    k_sigma: float = 3.0,
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
) -> dict[str, Any]:
    """温区良率（uq 域）：环境包络温度轴并入 MC+温区两端角点评估。

    D9。无副作用（只读样本集；要求样本集含 t_c 维）；角点不满足规格
    如实 FAIL 不凑绿；代理估计面不替代真机复验。缺 t_c 维/包络键未知
    → ok=False 如实。只读无时序约束。

    Args:
        samples_path: 校准样本集 samples.json（含 t_c 维）
        env_key: 环境包络键（bands_env_list 查询）
        tolerances: 几何公差 σ（可空，只做温度维扰动）
        t_ref_c: 参考温度 °C（缺省用包络自身参考温度）
        k_sigma: σ_c = 包络半宽/k_sigma
        n: 蒙特卡洛抽样数
        seed: 随机种子
        kind: 代理类型 poly_ridge|nn

    Returns:
        dict: TemperatureZoneYieldPayload 契约 + contract_check
    """
    from rfauto.service.contracts import annotate_contract
    from rfauto.service.uq_service import temperature_zone_yield
    return annotate_contract("temperature_zone_yield", temperature_zone_yield(
        samples_path, dict(tolerances or {}), env_key, t_ref_c=t_ref_c,
        k_sigma=k_sigma, n=n, seed=seed, kind=kind))


@mcp.tool
def uq_rare_yield(
    samples_path: str,
    tolerances: dict[str, float] | None = None,
    threshold: float = 0.0,
    n_is: int = 5000,
    seed: int = 0,
) -> dict[str, Any]:
    """稀有失效概率（uq 域）：FORM u* 喂重要性采样+MC 交叉核对。

    XD-11（W2-G 2026-10-05）。零逻辑转发 service uq_service.rare_yield_is
    （代理拟合+FORM 寻优+IS+MC 交叉核对全在确定性内核；agent 只拿 typed
    结果）。ESS 守卫与 suspect 如实分级在信封（#122 不凑绿）；小概率
    估计面不替代高保真复验。样本集缺失 → ok=False 如实。只读无时序约束。

    Args:
        samples_path: 校准样本集 samples.json
        tolerances: 公差 σ（缺省 None=取样本集 meta 缺省）
        threshold: 失效阈（cost 语义，与样本集 cost 同参照）
        n_is: IS 抽样数
        seed: 随机种子

    Returns:
        dict: rare_yield_is JSON 契约（{ok, pf_form, pf_is, pf, beta, cov,
            cov_is, ess, ess_ratio, n_evals, seed, method,
            rel_diff_form_is, form_is_consistency, applicability, note}）
    """
    from rfauto.service.uq_service import rare_yield_is
    return rare_yield_is(samples_path, dict(tolerances or {}), threshold=threshold,
                         n_is=n_is, seed=seed)

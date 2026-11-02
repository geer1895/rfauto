"""单目标竞赛持久门服务包装（aurora_n O5 席，2026-10-31）：合成族进 → JSON 出。

消费 :mod:`rfauto.optimization.competition_scalar`（T-N5 标量竞赛架内核，
judge 记分面 #118 零改动——本层只做参数解析/引擎与问题族解析/信封组装，
零数值逻辑）。zero_wiring REGISTRY O5 登记欠账清偿：竞赛架此前仅测试 +
一次性探针脚本驱动，无运行时持久门；本服务 + ``rfauto competition run``
CLI 叶（cli/domains/competition.py）转常驻。

规则 4（服务层 JSON 进出）+ 铁律 7（数值全部来自注入的内置合成目标函数
与各引擎公开入口——judge AUC/秩/达标记分是确定性纯函数，#207 元裁判面）。

问题族口径：**JSON 面只承载族键名**（目标函数不可 JSON 化）——内置 4 族
（concave2d 凹 / rastrigin2d 多谷 / rosenbrock2d 窄谷 / noisysphere4d 噪声）
与首榜（runs/aurora_n/wave1_d/tn5_competition_report.md）同定义同参数盒
同 target/known_optimum，逐字节同源移植；外部真函数通道=Python 编程层
:func:`register_problem_factory` 注册后经族键消费。

引擎口径：缺省=``SCALAR_ENGINE_REGISTRY`` 全部已注册（注册序）；显式
点名 ``botorch_ei`` 走 opt-in 注册（:func:`ensure_botorch_engine_registered`，
未装 ``rfauto[botorch]`` extra 报安装指引错误不静默）；其余未知名显式
拒绝并列可用项。saas_post 未进模块级注册面（w2_tn11 为探针脚本级注册，
驱动代码是 T-N11 实验预声明的内嵌 BO 设计，非生产引擎模块）——本服务
不内嵌探针驱动（如实声明，非静默缺席）。

确定性：同 seed 同参数重跑，内核报表剥离 ``elapsed_s`` 后逐位一致
（:func:`strip_elapsed_s` 为对拍单源；md 报表耗时列为实测墙钟，不进
逐位钉）。
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from typing import Any

from rfauto.optimization.competition_scalar import (
    SCALAR_ENGINE_REGISTRY,
    ScalarProblem,
    format_report_markdown,
    list_scalar_engines,
    run_competition_scalar,
)
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "BUILTIN_PROBLEM_FACTORIES",
    "register_problem_factory",
    "run_competition",
    "strip_elapsed_s",
]


# ── 内置合成 4 族（首榜同源；目标函数确定性——同参数同值）─────────────────

_NOISE_W = (0.71, 0.19, 0.83, 0.40)
_NOISE_K = (12.9898, 78.233, 37.719, 93.989)


def _frac(x: float) -> float:
    return x - math.floor(x)


def _concave2d(p: dict[str, float]) -> float:
    """凹族：最小值在参数盒角点（concave min-at-boundary 难例）。"""
    return sum(1.0 - 4.0 * (v - 0.5) ** 2 for v in p.values())


def _rastrigin2d(p: dict[str, float]) -> float:
    """多谷族：平移 Rastrigin（全局谷在 c，规则局部谷栅格）。"""
    c = (0.5, 0.5)
    return 10.0 * 2 + sum(
        (v - ci) ** 2 - 10.0 * math.cos(2.0 * math.pi * (v - ci))
        for v, ci in zip(p.values(), c, strict=True))


def _rosenbrock2d(p: dict[str, float]) -> float:
    """窄谷族：Rosenbrock 抛物谷（谷内易、谷外难）。"""
    x, y = p["x0"], p["x1"]
    return 100.0 * (y - x * x) ** 2 + (1.0 - x) ** 2


def _noisysphere4d(p: dict[str, float]) -> float:
    """噪声族：球面 + 确定性哈希粗糙面（可复现红线：同参数同值）。"""
    base = sum((v - w) ** 2 for v, w in zip(p.values(), _NOISE_W, strict=True))
    dot = sum(v * k for v, k in zip(p.values(), _NOISE_K, strict=True))
    noise = _frac(math.sin(dot) * 43758.5453123) - 0.5
    return base + 0.05 * noise


def _make_concave2d() -> ScalarProblem:
    return ScalarProblem(
        name="concave2d", bounds={"x0": (0.0, 1.0), "x1": (0.0, 1.0)},
        objective_fn=_concave2d, target=0.01, known_optimum=0.0)


def _make_rastrigin2d() -> ScalarProblem:
    return ScalarProblem(
        name="rastrigin2d", bounds={"x0": (0.0, 1.0), "x1": (0.0, 1.0)},
        objective_fn=_rastrigin2d, target=0.05, known_optimum=0.0)


def _make_rosenbrock2d() -> ScalarProblem:
    return ScalarProblem(
        name="rosenbrock2d", bounds={"x0": (-2.0, 2.0), "x1": (-2.0, 2.0)},
        objective_fn=_rosenbrock2d, target=0.5, known_optimum=0.0)


def _make_noisysphere4d() -> ScalarProblem:
    return ScalarProblem(
        name="noisysphere4d",
        bounds={f"x{i}": (0.0, 1.0) for i in range(4)},
        objective_fn=_noisysphere4d, target=0.05, known_optimum=0.0)


#: 内置合成族注册表（模块级单源；键序=首榜问题书序）。``register_problem_
#: factory`` 追加，测试/编程扩展面（外部真函数的确定性代理通道）。
BUILTIN_PROBLEM_FACTORIES: dict[str, Callable[[], ScalarProblem]] = {
    "concave2d": _make_concave2d,
    "rastrigin2d": _make_rastrigin2d,
    "rosenbrock2d": _make_rosenbrock2d,
    "noisysphere4d": _make_noisysphere4d,
}


def register_problem_factory(
        name: str, factory: Callable[[], ScalarProblem]) -> None:
    """族注册面（Python 编程层，不上 CLI/MCP JSON 面）：追加合成族。

    用途=外部真函数的确定性代理通道（调用方自持确定性 objective 闭包，
    包装成 ``ScalarProblem`` 工厂注册后即可经 ``problems=<注册名>`` 全链
    消费竞赛架——JSON 面仍只承载键名，函数本体不 JSON 化）。重名静默
    覆盖（registry_kit 家法同款）；非 callable 显式拒绝（构造面负例单源）。
    """
    if not callable(factory):
        raise ValueError(f"族工厂 {name!r} 必须 callable，收到 {factory!r}")
    BUILTIN_PROBLEM_FACTORIES[str(name)] = factory


# ── 解析面（引擎/族/预算；全部显式报错不静默）─────────────────────────────

def _resolve_engines(engines: Sequence[str] | None) -> list[str] | dict:
    """引擎名单解析：None=全部已注册；显式名单逐名核验（botorch_ei opt-in）。

    Returns:
        list[str] 成功（保序去重前先查重）；dict=error_envelope（失败）。
    """
    if engines is None:
        return list_scalar_engines()
    names: list[str] = []
    for raw in engines:
        name = str(raw).strip()
        if not name:
            return error_envelope("--engines 含空名（检查逗号分隔串）")
        if name in names:
            return error_envelope(f"引擎名重复: {name!r}（名单须唯一）")
        if name not in SCALAR_ENGINE_REGISTRY:
            if name == "botorch_ei":
                from rfauto.optimization.botorch_engine import (
                    ensure_botorch_engine_registered,
                )
                try:
                    ensure_botorch_engine_registered()
                except ImportError as exc:
                    return error_envelope(str(exc))
            else:
                hint = ""
                if name in ("saas_map", "saas_post"):
                    hint = ("（saas 族未进模块级注册面——w2_tn11 为探针脚本"
                            "级注册，非生产引擎模块）")
                return error_envelope(
                    f"未知引擎 {name!r}；可用: {list_scalar_engines()}"
                    f"（botorch_ei 为 opt-in 臂，显式点名即尝试注册）{hint}")
        names.append(name)
    if not names:
        return error_envelope("engines 不得为空")
    return names


def _resolve_problems(problems: Sequence[str] | None) -> list | dict:
    """族名单解析：None=内置全族（注册序）；显式名单逐键核验。"""
    if problems is None:
        return [BUILTIN_PROBLEM_FACTORIES[k]() for k in BUILTIN_PROBLEM_FACTORIES]
    out: list[ScalarProblem] = []
    for raw in problems:
        key = str(raw).strip()
        if not key:
            return error_envelope("--problems 含空族名（检查逗号分隔串）")
        factory = BUILTIN_PROBLEM_FACTORIES.get(key)
        if factory is None:
            return error_envelope(
                f"未知问题族 {key!r}；可用: {list(BUILTIN_PROBLEM_FACTORIES)}"
                "（外部函数走 register_problem_factory Python 注册面）")
        out.append(factory())
    if not out:
        return error_envelope("problems 不得为空")
    return out


def _parse_seeds(seeds: Sequence[int]) -> list[int] | dict:
    """seed 名单归一（int 化；空/非有限显式报错）。"""
    out: list[int] = []
    for raw in seeds:
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return error_envelope(f"seed 须为整数，收到 {raw!r}")
        out.append(v)
    if not out:
        return error_envelope("seeds 不得为空")
    return out


def strip_elapsed_s(payload: Any) -> Any:
    """递归剥离 ``elapsed_s`` 键（确定性对拍单源）。

    同 seed 同参数重跑的内核报表经本函数剥离耗时后应逐位一致——
    ``elapsed_s`` 是唯一墙钟实测字段，不进确定性钉（docstring 口径）。
    """
    if isinstance(payload, dict):
        return {k: strip_elapsed_s(v) for k, v in payload.items()
                if k != "elapsed_s"}
    if isinstance(payload, list):
        return [strip_elapsed_s(v) for v in payload]
    return payload


# ── 主入口 ───────────────────────────────────────────────────────────────────

def run_competition(
    engines: Sequence[str] | None = None,
    problems: Sequence[str] | None = None,
    *,
    n_eval: int = 60,
    seeds: Sequence[int] = (0, 1, 2),
) -> dict[str, Any]:
    """运行同预算标量竞赛（规则 4：JSON 信封进出；零数值逻辑转发内核）。

    Args:
        engines: 引擎名序列（None=``SCALAR_ENGINE_REGISTRY`` 全部已注册；
            ``botorch_ei`` 显式点名走 opt-in 注册；未知名显式拒绝）。
        problems: 问题族键序列（None=内置 4 族全跑；未知名显式拒绝）。
        n_eval: 每引擎×问题×seed 的评估预算（>0；两阶段截点=n_eval//2 与
            n_eval，共享同一轨迹不重跑）。
        seeds: 确定性种子序列（非空；同 seed 组重跑剥离 elapsed_s 逐位）。

    Returns:
        dict: 成功 ``{"ok": True, schema/engines/problems/n_eval/seeds/
        n_runs/result/report_md/elapsed_s}``——``result`` 为内核报表原样
        dict（schema competition-scalar-v1，含 runs 与三套 ranking），
        ``report_md`` 为内核 :func:`format_report_markdown` 产物；
        失败 ``{"ok": False, "errors": [...]}``（入参校验/未知引擎/未知族/
        常数目标 #195/band 退化均信封化，不抛裸 traceback）。
    """
    t0 = time.time()

    # ── 入参校验（显式报错单源）───────────────────────────────────────────
    try:
        n_eval_i = int(n_eval)
    except (TypeError, ValueError):
        return error_envelope(f"n_eval 须为整数，收到 {n_eval!r}")
    if n_eval_i <= 0:
        return error_envelope(f"n_eval 必须 >0，实得 {n_eval}")

    engines_res = _resolve_engines(engines)
    if isinstance(engines_res, dict):
        return engines_res
    problems_res = _resolve_problems(problems)
    if isinstance(problems_res, dict):
        return problems_res
    seeds_res = _parse_seeds(seeds)
    if isinstance(seeds_res, dict):
        return seeds_res

    # ── 内核环跑（ValueError 信封化：常数目标 #195 / band 退化 / 探针非有限）──
    try:
        result = run_competition_scalar(
            problems_res, engines_res, n_eval_i, seeds_res)
    except ValueError as exc:
        return error_envelope(f"竞赛拒跑: {exc}")

    total_elapsed = time.time() - t0
    report_md = format_report_markdown(result)
    return ok_envelope(
        schema=result["schema"],
        engines=result["engines"],
        problems=[p["name"] for p in result["problems"]],
        n_eval=n_eval_i,
        seeds=result["seeds"],
        n_runs=len(result["runs"]),
        result=result,
        report_md=report_md,
        elapsed_s=round(total_elapsed, 3),
    )

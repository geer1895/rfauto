"""openEMS 优化回路适配器——optimizer._create_adapter "openems" 分支的构造体。

产物化自真机战役层的进程内评估补丁：与 fake/hfss 分支同构接入 run_optimization 优化
回路（消费面 = FakeAdapter/HfssAdapter 的 build_objective/self_heal 子集：
set_variables / solve→SolveReport / get_sparams→skrf.Network / close /
health_check / ensure_connected）。

真评估链与 service/autotune_service._make_openems_sampler 同口径：
OpenEMSSolver + build_geometry({"template", "params"}[, "substrate"]) +
resolve_openems_exe。**几何单一事实源 = openems_templates.render_script**——
本适配器不画几何，逐评估按当前变量整脚本重渲染（mline 等锚模板为纯
openEMS 模板，无桌面会话可建）。

缓存口径：openEMS 磁盘缓存（OpenEMSSolver extra_params.cache）与优化器
ResultCache 是两套独立缓存。本适配器 cache 缺省跟随 RFAUTO_CACHE 环境变量
（=off 时引擎缓存同关）——战役脚本 run_campaign 设 RFAUTO_CACHE=off 的
"真评估口径"（历史点也真跑、不吃缓存）经此传递到引擎层，两套缓存同时
关闭（真机战役预声明口径）。
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# HFSS 变量表达式（如 "1.113mm"）→ 数值提取（ParameterSystem.to_hfss_expr
# 产物口径 = 值+单位后缀；纯数字字符串/数值本身也接受）
_EXPR_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def expr_to_float(expr: Any) -> float:
    """HFSS 变量表达式（如 '1.113mm'）→ 浮点值。

    Raises:
        ValueError: 表达式中无可解析数值。
    """
    if isinstance(expr, bool):
        raise ValueError(f"布尔值不是合法的几何变量表达式: {expr!r}")
    if isinstance(expr, (int, float)):
        return float(expr)
    m = _EXPR_FLOAT_RE.search(str(expr))
    if m is None:
        raise ValueError(f"无法从表达式解析数值: {expr!r}")
    return float(m.group(0))


def template_for_model(model: str) -> str:
    """模型名 → openEMS 模板名（子串口径）。

    与 service.ui_service._template_hint 同口径（wilkinson/branchline/
    patch/mline/cpw 五族）；本地实现避免 optimization→service 逆向依赖
    （分层契约：service 在 optimization 之上）。优先级低于模型插件自己
    声明的 openems_template ClassVar（optimizer 分支先查插件、再走本映射）。

    Raises:
        ValueError: 模型名无模板映射（显式失败，不静默降级）。
    """
    model = str(model or "")
    if "wilkinson" in model:
        return "wilkinson"
    if "branchline" in model:
        return "branchline"
    if "patch" in model:
        return "patch"
    if "mline" in model:
        return "mline"
    if "cpw" in model:
        return "cpw"
    raise ValueError(f"模型无 openEMS 模板映射: {model!r}")


def _cache_default_from_env() -> bool:
    """引擎磁盘缓存缺省跟随 RFAUTO_CACHE（off→关；其余/未设→开）。

    与 infra.result_cache 的环境语义同口径（读法同源：裸 os.environ，
    两种独立缓存由调用方/env 一处声明同关，见模块 docstring）。
    """
    return os.environ.get("RFAUTO_CACHE", "readwrite").strip().lower() != "off"


class OpenEMSOptAdapter:
    """run_optimization 优化回路的 openEMS 适配器（单臂一实例、逐评估真跑）。

    每次 solve()：当前变量集 → render_script(template, params) 整脚本重渲染
    → OpenEMSSolver 子进程求解 → skrf.Network（z0=50Ω）。评估产物落
    work_root/eval_NNNN/（缺省 runs/openems_opt_evals/arm_<时间戳>/，
    cwd 相对——战役/单测 chdir 沙箱内自动隔离，#144）。

    Args:
        freq_range_ghz: (f_low, f_high) GHz（recipe.setup.freq_range_ghz）。
        template: openEMS 模板名（如 "mline"）；空串视为无效（显式失败）。
        mesh_resolution_mm: 网格 base 覆盖（mm）；0=官方自动 λ_sub/50 档。
        substrate: 基板覆盖（{"er","h_mm","tan_d"}）；None=模板缺省基板
            （openems_templates._DEFAULT_SUB = rogers4350b 口径）。
        cache: 引擎磁盘缓存开关；None=跟随 RFAUTO_CACHE 环境变量。
        solve_timeout_s: 单评估子进程墙钟帽（防挂死；EMSolverConfig
            extra_params.solve_timeout_s 透传）。
        extra_params: 追加透传 EMSolverConfig.extra_params（显式项优先）。
        work_root: 评估产物根目录；None=runs/openems_opt_evals/arm_<时间戳>。
        eval_index_offset: 评估序号起始偏移（A-02 resume 防覆盖）：挂到既有
            eval_NNNN 归档上接续编号，从 max 既有序号起（0=全新根，缺省）。
            缺省 0 时新会话 _n 回卷会把 work_root/eval_0001 起的既有归档
            整目录覆盖（c10 GT 战役 resume 路径实证形态）。
        seed: 仅 provenance（优化器 sampler 种子经 adapter_kwargs 透传），
            不参与任何物理数值（数值只在确定性内核）。
    """

    def __init__(
        self,
        freq_range_ghz: tuple[float, float],
        *,
        template: str = "",
        mesh_resolution_mm: float = 0.0,
        substrate: dict[str, Any] | None = None,
        cache: bool | None = None,
        solve_timeout_s: float = 900.0,
        extra_params: dict[str, Any] | None = None,
        work_root: str | Path | None = None,
        eval_index_offset: int = 0,
        seed: int | None = None,
    ) -> None:
        if not str(template or "").strip():
            raise ValueError("openems 优化适配器需要 template（模型→模板映射失败？）")
        self._freq = (float(freq_range_ghz[0]), float(freq_range_ghz[1]))
        self._template = str(template)
        self._mesh = float(mesh_resolution_mm)
        self._substrate = dict(substrate) if substrate else None
        self._cache = _cache_default_from_env() if cache is None else bool(cache)
        self._solve_timeout_s = float(solve_timeout_s)
        self._extra_params = dict(extra_params or {})
        self._seed = seed
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self._root = (
            Path(work_root) if work_root is not None
            else Path("runs") / "openems_opt_evals" / f"arm_{stamp}"
        )
        self._vars: dict[str, float] = {}
        self._net: Any | None = None
        self._n = int(eval_index_offset)
        self._solved = False   # 本实例是否已发起过 solve（last_eval_dir 语义锚）

    # ── 优化回路接口（build_objective / self_heal 消费面） ──────────────────

    def connect(self, settings: dict[str, Any] | None = None) -> bool:
        """幂等连接：模板名有效即就绪（exe 可用性在 solve 时探测）。"""
        return bool(self._template)

    def health_check(self) -> bool:
        """健康检查：状态无外部会话，恒就绪（失败经 solve 报告透传）。"""
        return True

    def ensure_connected(self) -> None:
        """自愈重连钩子（无外部会话，no-op）。"""

    def set_variables(self, vars_dict: dict[str, str]) -> None:
        """记录设计变量（HFSS 表达式 → 数值；逐评估渲染时整体生效）。"""
        self._vars.update({k: expr_to_float(v) for k, v in vars_dict.items()})

    def get_variables(self) -> dict[str, float]:
        """当前变量快照（调试/观测用）。"""
        return dict(self._vars)

    @property
    def template(self) -> str:
        """渲染模板名。"""
        return self._template

    @property
    def eval_root(self) -> Path:
        """评估产物根目录（观测用；目录在首次 solve 时创建）。"""
        return self._root

    @property
    def mesh_resolution_mm(self) -> float:
        """网格 base 覆盖（mm）观测面；0.0=官方自动 λ_sub/50 档语义哨兵
        （非实测值——meta 落痕侧须转 "auto" 注记，禁当数值消费）。"""
        return self._mesh

    @property
    def last_eval_dir(self) -> Path:
        """最近一次 solve 的评估产物目录（run 产物归集用；本实例未发起过
        solve=根目录——含 eval_index_offset>0 的 resume 实例，防把既有
        归档目录误报为"最近"）。"""
        if not self._solved:
            return self._root
        return self._root / f"eval_{self._n:04d}"

    def solve(self, setup_name: str = "", timeout_s: float | None = None) -> Any:
        """逐评估真跑：重渲染 → 求解 → 装载 skrf.Network。

        Returns:
            SolveReport：success=False 时 message 带失败原因（优化回路按
            失败剪枝，TrialPruned 路径）。
        """
        import skrf

        from rfauto.adapters.em_solver_base import (
            EMSolverConfig,
            resolve_openems_exe,
        )
        from rfauto.adapters.openems_solver import OpenEMSSolver
        from rfauto.core.interfaces import SolveReport

        self._n += 1
        self._solved = True
        params = dict(self._vars)
        timeout = float(timeout_s) if timeout_s else self._solve_timeout_s
        extra = dict(self._extra_params)
        extra.setdefault("cache", self._cache)
        extra.setdefault("solve_timeout_s", timeout)
        work = self._root / f"eval_{self._n:04d}"
        try:
            solver = OpenEMSSolver(EMSolverConfig(
                solver_type="openems", exe_path=resolve_openems_exe(),
                working_dir=str(work), freq_range_ghz=self._freq,
                mesh_resolution_mm=self._mesh, extra_params=extra))
            if not solver.connect():
                return SolveReport(success=False, message="openEMS exe 不可用")
            geometry: dict[str, Any] = {
                "template": self._template, "params": params,
            }
            if self._substrate:
                geometry["substrate"] = dict(self._substrate)
            if not solver.build_geometry(geometry):
                return SolveReport(success=False, message="CSX 脚本渲染失败")
            t0 = time.monotonic()
            result = solver.solve()
            wall = time.monotonic() - t0
            if not result.success or result.s_params is None:
                return SolveReport(success=False, message=str(result.message))
            f = result.freq_ghz
            self._net = skrf.Network(
                frequency=skrf.Frequency(
                    float(f[0]), float(f[-1]), len(f), unit="ghz"),
                s=result.s_params, z0=50.0)
            return SolveReport(success=True, message=(
                f"openEMS eval#{self._n} template={self._template} "
                f"wall={wall:.1f}s nf={len(f)}"))
        except Exception as exc:  # 求解异常按失败报告透传（TrialPruned 路径）
            return SolveReport(success=False, message=f"openEMS 异常: {exc!r}")

    def get_sparams(self) -> Any:
        """最近一次成功求解的 skrf.Network（z0=50Ω）。"""
        if self._net is None:
            raise RuntimeError("无可用解（solve 未成功）")
        return self._net

    def close(self) -> None:
        """释放最近解引用（无外部会话；评估产物落盘留档）。"""
        self._net = None

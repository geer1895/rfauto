"""ADS 电路前仿优化通道（aurora_p B3 席）——把 ADS 电路前仿链（aurora_o
T-O4 落地内核 + aurora_p A2 M3 编排）接进 optimizer 求解通道注册表。

设想链路（任务书 §0）：优化器提议参数 → ADS 电路仿真（hpeesofsim 真跑或
runner 注入）→ 指标（system_gain_db/input_vswr 等确定性内核产出）→
SpecEvaluator/cost → 优化器下一轮。本模块是 run_optimization 优化回路的
openEMS 同构件（参照 adapters/openems_optimizer_adapter.py 的消费面子集：
set_variables / solve→SolveReport / get_sparams→skrf.Network / close /
health_check / ensure_connected / connect）。

**零新建内核（铁律 7 家法）**：渲染/求解/解析/网络换算/系统指标全部复用
既有单源——
- 渲染 = linkage.ads_template_family.render_family（MVP 两族，网表数字
  只由渲染器产出，本模块零网表语法零数字手抄）；
- 求解 = adapters.ads_netlist.run_hpeesofsim 正规入口（#272 禁裸调 exe）
  或注入 ``runner(netlist_path) -> payload``（离线验收通道，#139 家法，
  与 service.circuit_sim_run 的 runner 注入位同签名同语义）；
- 解析 = adapters.ads_netlist.parse_dataset；
- payload → skrf.Network = ads_template_family.payload_to_network
  （wilkinson_snp）/ field_circuit_anchor.composite_network_from_payload
  （branchline_cascade 合成 2 端口，与 circuit_sim_run 同分派口径）；
- 系统指标 = linkage.ads_circuit.compute_system_metrics（带内均值单源）。
优化器回路的 cost 指标由 SpecEvaluator 从 get_sparams() 网络自算（s11_db
等 S 参数 DSL 键），系统指标作为 ``last_metrics`` 观测面随适配器可查。

**参数映射（#154 家法）**：优化参数（经 ParameterSystem.write_to_adapter
到达 set_variables 的 HFSS 变量表达式）→ ADS 电路族渲染参数的换算全部走
显式映射表 :data:`ADS_CIRCUIT_PARAM_MAP`（含 branchline 插件 hfss_var_map
别名 f0/z0；单位换算只有 ghz_to_hz / identity / to_int 三种显式形态）。
映射表外的变量（如 arm_len 等插件 EM 几何变量）不进电路渲染（落
``unconsumed_variables`` 可查）——ADS 电路级联不消费 EM 几何语义，同名
参数跨通道语义逐键钉在 tests/unit/test_ads_optimizer_channel.py。

**分层与注册（本模块放 linkage 层的原因）**：本适配器消费的渲染/换算/
指标内核全在 linkage 层（ads_template_family / field_circuit_anchor /
ads_circuit），而 import-linter 分层契约禁 optimization（下层）→ linkage
（上层）静态 import——故适配器与工厂函数同住本模块，注册经
linkage → optimization 的**合法向下 import** 在模块导入时完成
（:func:`register_ads_channel`，幂等）：
``import rfauto.linkage.ads_optimizer_channel  # noqa: F401`` 即注册
"ads" 通道。既有 fake/hfss/openems 三通道工厂零变化；惰性导入纪律同
adapter_channels（本模块 import 不拉 rfauto.adapters.*——ads_netlist/
ads_circuit 在 solve 时才 lazy import，tests/unit/test_adapter_channels
子进程钉同过）。

MVP 范围（如实声明）：wilkinson_snp / branchline_cascade 两 MVP 族；
A2 M3 active 两族（active_chain_sparam/loadpull_hb）未接——未知族显式
报错不静默（factory 返回 (None, "") 交上层"适配器创建失败"终 run）。

对拍口径：优化环内每评估不对拍（成本翻倍；openems 通道同口径）；对拍
属离线复核面（circuit_sim_run/annotate 链已覆盖），本通道只保证评估链
单源一致。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from rfauto.linkage import ads_template_family as atf
from rfauto.linkage import field_circuit_anchor as fca

logger = logging.getLogger(__name__)

__all__ = [
    "ADS_CIRCUIT_PARAM_MAP",
    "ADS_OPT_METRIC_NAMES",
    "AdsOptAdapter",
    "register_ads_channel",
]

#: ADS 电路族优化参数映射表（#154 家法单源：到达 set_variables 的变量名
#: → (渲染器关键字参数键, 单位变换标识)）。
#:
#: 语义逐键核对（与 hfss/fake 通道同名参数对齐）：
#: - ``f0``/``f0_ghz``：中心频率，优化侧数值=GHz（ParamValue.to_hfss_expr
#:   产物 "2.4GHz" 经 expr_to_float=2.4）→ 渲染器 ``f0_hz``（Hz）——
#:   与 HFSS 通道 f0 变量、fake 通道 f0_ghz 同一物理量；
#: - ``z0``/``z0_ohm``：系统参考阻抗 ohm → 渲染器 ``z0``（Port Z）——
#:   与 HFSS 通道 z0 变量同语义；
#: - ``theta_in_deg``/``theta_out_deg``/``z_line``/``z_line_ohm``：
#:   ADS 级联电路专属设计参数（TLIN 电长度/特征阻抗），HFSS EM 几何族
#:   无对应变量（显式独占名，不与既有通道撞名）；
#: - ``sweep.*``：频扫三键（优化侧与渲染侧同为 GHz 数值——unit 固定
#:   "GHz"，resolve_sweep 的显式 sweep 键即单位制下数值，故 identity）。
#: 表外变量 = 非 ADS 电路参数（如插件 EM 几何变量 arm_len），不进渲染、
#: 不报错（插件 build 的固定变量集合法路过，与 openems 通道同口径）。
ADS_CIRCUIT_PARAM_MAP: dict[str, dict[str, tuple[str, str]]] = {
    "branchline_cascade": {
        "f0_ghz": ("f0_hz", "ghz_to_hz"),
        "f0": ("f0_hz", "ghz_to_hz"),  # branchline 插件 hfss_var_map 别名
        "theta_in_deg": ("theta_in_deg", "identity"),
        "theta_out_deg": ("theta_out_deg", "identity"),
        "z_line_ohm": ("z_line", "identity"),
        "z_line": ("z_line", "identity"),
        "z0_ohm": ("z0", "identity"),
        "z0": ("z0", "identity"),  # branchline 插件 hfss_var_map 别名
        "sweep.fstart_ghz": ("sweep.fstart", "identity"),
        "sweep.fstop_ghz": ("sweep.fstop", "identity"),
        "sweep.npoints": ("sweep.npoints", "to_int"),
    },
    "wilkinson_snp": {
        "z0_ohm": ("z0", "identity"),
        "z0": ("z0", "identity"),
        "n_ports": ("n_ports", "to_int"),
        "sweep.fstart_ghz": ("sweep.fstart", "identity"),
        "sweep.fstop_ghz": ("sweep.fstop", "identity"),
        "sweep.npoints": ("sweep.npoints", "to_int"),
    },
}

#: ADS 电路族系统指标清单（last_metrics 观测面；与
#: service.circuit_sim_service.METRIC_NAMES 两 MVP 族逐键一致——
#: 双向一致性钉在 tests/unit/test_ads_optimizer_channel.py，#231 家法：
#: 注册表消费者测试互钉，单源漂移即门红）。
ADS_OPT_METRIC_NAMES: dict[str, tuple[str, ...]] = {
    "wilkinson_snp": (
        "system_gain_db", "input_vswr", "amplitude_balance_db",
        "output_phase_balance",
    ),
    "branchline_cascade": ("system_gain_db", "input_vswr"),
}

#: 单位变换标识 → 换算实现（显式表，禁第四种形态；bool 显式拒——
#: bool 是 int 子类，float(True)=1.0 静默手误，service._normalize_override
#: 同款纪律）。
_TRANSFORMS: dict[str, Callable[[Any], float | int]] = {
    "identity": lambda v: float(v),
    "ghz_to_hz": lambda v: float(v) * 1e9,
    "to_int": lambda v: round(float(v)),
}


def _transform(transform: str, value: Any, alias: str) -> float | int:
    """映射表变换实现（fail loud：未知变换/非法值显式报错不静默）。"""
    fn = _TRANSFORMS.get(transform)
    if fn is None:
        raise ValueError(f"映射表未知变换 {transform!r}（alias={alias!r}）")
    if isinstance(value, bool):
        raise ValueError(f"参数 {alias!r} 值不能是 bool（{value!r}）")
    try:
        return fn(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"参数 {alias!r} 值 {value!r} 无法按 {transform} 换算: {exc}") from exc


class AdsOptAdapter:
    """run_optimization 优化回路的 ADS 电路前仿适配器（单臂一实例）。

    每次 solve()：当前变量集 → 映射表换算 → render_family 整网表重渲染
    → hpeesofsim 真跑或注入 runner → parse_dataset → payload→Network
    （family 分派单源）→ compute_system_metrics 观测面。评估产物落
    work_root/eval_NNNN/（缺省 runs/ads_opt_evals/arm_<时间戳>/，cwd 相对
    ——战役/单测 chdir 沙箱内自动隔离，#144 家法同 openems 通道）。

    Args:
        freq_range_ghz: (f_low, f_high) GHz（recipe.setup.freq_range_ghz）
            ——渲染频扫基线（unit 固定 GHz；映射表 sweep.* 显式键逐评估可
            覆盖）。
        freq_points: 频点数（recipe.setup.points）。
        family: ADS 电路族名（wilkinson_snp | branchline_cascade；MVP）。
        snp_path: 器件 Touchstone 路径（网表 SnP File 来源）。
        runner: ``runner(netlist_path) -> payload`` 注入位（离线验收，
            #139；None=真 hpeesofsim 链）。
        ads_dir: ADS 安装根（缺省 env RFAUTO_HPEESOF_DIR → settings）。
        work_root: 评估产物根目录；None=runs/ads_opt_evals/arm_<时间戳>。
    """

    def __init__(
        self,
        freq_range_ghz: tuple[float, float],
        freq_points: int,
        *,
        family: str,
        snp_path: str | Path,
        runner: Callable[[Path], dict[str, Any]] | None = None,
        ads_dir: str | Path | None = None,
        work_root: str | Path | None = None,
    ) -> None:
        if family not in ADS_CIRCUIT_PARAM_MAP:
            raise ValueError(
                f"ads 优化通道未知电路族 {family!r}（MVP 可选 "
                f"{sorted(ADS_CIRCUIT_PARAM_MAP)}；active 族未接，如实声明）")
        self._family = str(family)
        self._snp = Path(snp_path)
        if not self._snp.exists():
            raise FileNotFoundError(f"器件 Touchstone 不存在: {self._snp}")
        self._freq = (float(freq_range_ghz[0]), float(freq_range_ghz[1]))
        self._points = int(freq_points)
        self._runner = runner
        self._ads_dir = ads_dir
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self._root = (
            Path(work_root) if work_root is not None
            else Path("runs") / "ads_opt_evals" / f"arm_{stamp}"
        )
        self._vars: dict[str, float] = {}
        self._net: Any | None = None
        self._n = 0
        self._solved = False
        self._last_metrics: dict[str, float] | None = None
        self._last_circuit_params: dict[str, Any] | None = None

    # ── 优化回路接口（build_objective / self_heal 消费面） ──────────────────

    def connect(self, settings: dict[str, Any] | None = None) -> bool:
        """幂等连接：族名+器件数据合法即就绪（exe 可用性在 solve 时探测）。"""
        return self._snp.exists()

    def health_check(self) -> bool:
        """健康检查：无外部会话，恒就绪（失败经 solve 报告透传）。"""
        return True

    def ensure_connected(self) -> None:
        """自愈重连钩子（无外部会话，no-op）。"""

    def set_variables(self, vars_dict: dict[str, str]) -> None:
        """记录设计变量（HFSS 表达式 → 数值；逐评估渲染时经映射表生效）。

        插件 build 的固定 EM 几何变量（arm_len 等）合法路过本表但不进
        电路渲染（见 ADS_CIRCUIT_PARAM_MAP 表注释；unconsumed_variables
        可查）。
        """
        from rfauto.adapters.openems_optimizer_adapter import expr_to_float

        self._vars.update({k: expr_to_float(v) for k, v in vars_dict.items()})

    def get_variables(self) -> dict[str, float]:
        """当前变量快照（调试/观测用）。"""
        return dict(self._vars)

    @property
    def family(self) -> str:
        """ADS 电路族名。"""
        return self._family

    @property
    def eval_root(self) -> Path:
        """评估产物根目录（观测用；目录在首次 solve 时创建）。"""
        return self._root

    @property
    def last_eval_dir(self) -> Path:
        """最近一次 solve 的评估产物目录（run 产物归集用；未 solve=根）。"""
        if not self._solved:
            return self._root
        return self._root / f"eval_{self._n:04d}"

    @property
    def last_metrics(self) -> dict[str, float] | None:
        """最近一次成功求解的系统指标（compute_system_metrics 单源）。

        未成功求解=None（不虚构，#122）。
        """
        return None if self._last_metrics is None else dict(self._last_metrics)

    @property
    def last_circuit_params(self) -> dict[str, Any] | None:
        """最近一次 solve 实际进渲染器的电路参数（映射有效性观测面）。"""
        if self._last_circuit_params is None:
            return None
        return {k: (dict(v) if isinstance(v, dict) else v)
                for k, v in self._last_circuit_params.items()}

    @property
    def unconsumed_variables(self) -> dict[str, float]:
        """当前变量中未进映射表的键（插件 EM 几何变量等；#154 透明面）。"""
        known = ADS_CIRCUIT_PARAM_MAP[self._family]
        return {k: v for k, v in self._vars.items() if k not in known}

    def _mapped_circuit_params(self) -> dict[str, Any]:
        """当前变量 × 映射表 → 渲染器关键字参数（flat，sweep 展开嵌套）。"""
        mapping = ADS_CIRCUIT_PARAM_MAP[self._family]
        out: dict[str, Any] = {}
        sweep: dict[str, Any] = {}
        for alias, value in self._vars.items():
            entry = mapping.get(alias)
            if entry is None:
                continue  # 非 ADS 电路参数（插件几何变量），不进渲染
            key, transform = entry
            mapped = _transform(transform, value, alias)
            if key.startswith("sweep."):
                sweep[key[len("sweep."):]] = mapped
            else:
                out[key] = mapped
        # 频扫基线：setup freq_range/points（GHz）；映射表 sweep 显式键覆盖
        sweep.setdefault("fstart", self._freq[0])
        sweep.setdefault("fstop", self._freq[1])
        sweep.setdefault("npoints", self._points)
        sweep.setdefault("unit", "GHz")
        out["sweep"] = sweep
        return out

    def solve(self, setup_name: str = "", timeout_s: float | None = None) -> Any:
        """逐评估真跑：映射 → 重渲染 → 求解/解析 → 网络装载 + 指标观测。

        Returns:
            SolveReport：success=False 时 message 带失败原因（优化回路按
            失败剪枝/罚路径），与 openems 通道同语义。
        """
        from rfauto.core.interfaces import SolveReport

        self._n += 1
        self._solved = True
        work = self._root / f"eval_{self._n:04d}"
        try:
            work.mkdir(parents=True, exist_ok=True)
            params = self._mapped_circuit_params()
            self._last_circuit_params = params
            text = atf.render_family(self._family, self._snp, params)
            netlist = work / f"{self._family}_netlist.txt"
            atf.write_netlist(text, netlist)
            t0 = time.monotonic()
            payload = self._run_and_parse(netlist, work)
            wall = time.monotonic() - t0
            net = self._payload_to_network(payload)
            self._net = net
            self._last_metrics = self._compute_metrics(net)
            return SolveReport(
                success=True, wall_time_s=wall,
                message=(f"ADS eval#{self._n} family={self._family} "
                         f"wall={wall:.1f}s nf={len(net.f)}"))
        except Exception as exc:  # 求解异常按失败报告透传（罚路径，不炸进化）
            return SolveReport(success=False, message=f"ADS 评估失败: {exc!r}")

    def _run_and_parse(self, netlist: Path, work: Path) -> dict[str, Any]:
        """求解+解析：注入 runner（离线通道）或 hpeesofsim 正规入口（#272）。"""
        if self._runner is not None:
            payload = self._runner(netlist)
            if not isinstance(payload, dict):
                raise TypeError(
                    f"注入 runner 须返回 payload dict，收到 {type(payload)!r}")
            return payload
        from rfauto.adapters import ads_netlist

        proc = ads_netlist.run_hpeesofsim(netlist, ads_dir=self._ads_dir)
        (work / f"{self._family}_hpeesofsim_stdout.txt").write_text(
            proc.stdout[-6000:] + "\n--- stderr ---\n" + proc.stderr[-2000:],
            encoding="utf-8")
        dataset = Path(f"{netlist}.ds")
        return ads_netlist.parse_dataset(dataset, ads_dir=self._ads_dir)

    def _payload_to_network(self, payload: dict[str, Any]) -> Any:
        """payload → skrf.Network（family 分派，与 circuit_sim_run 同单源）。"""
        if self._family == "wilkinson_snp":
            return atf.payload_to_network(payload)
        return fca.composite_network_from_payload(payload)

    def _compute_metrics(self, net: Any) -> dict[str, float]:
        """系统指标观测面（ads_circuit.compute_system_metrics 单源；lazy
        import——该模块 module 级拉 rfauto.adapters.ads_netlist，惰性纪律
        同 adapter_channels）。"""
        from rfauto.linkage.ads_circuit import compute_system_metrics

        return compute_system_metrics(net, list(ADS_OPT_METRIC_NAMES[self._family]))

    def get_sparams(self) -> Any:
        """最近一次成功求解的 skrf.Network（SpecEvaluator 消费面）。"""
        if self._net is None:
            raise RuntimeError("无可用解（solve 未成功）")
        return self._net

    def close(self) -> None:
        """释放最近解引用（无外部会话；评估产物落盘留档）。"""
        self._net = None


def _create_ads_channel(
    *,
    setup_cfg: dict[str, Any],
    freq_range: list[float],
    freq_points: int,
    adapter_kwargs: dict[str, Any] | None,
    recipe_data: dict[str, Any],
) -> tuple[Any | None, str]:
    """ads 通道工厂（ChannelFactory 签名，注册进 optimization 注册表）。

    adapter_kwargs：``family``（必给）、``snp_path``（必给）、``runner``、
    ``ads_dir``、``work_root``；未知键显式拒绝（防静默手误）。任一失败
    warning + 返回 ``(None, "")``（openems 通道同款语义——上层报"适配器
    创建失败"并终止该 run，原因在本条 warning 日志含 traceback 可见）。
    """
    try:
        kwargs = dict(adapter_kwargs or {})
        family = str(kwargs.pop("family", "") or "")
        snp_raw = str(kwargs.pop("snp_path", "") or "")
        runner = kwargs.pop("runner", None)
        ads_dir = kwargs.pop("ads_dir", None)
        work_root = kwargs.pop("work_root", None)
        if not family:
            raise ValueError(
                "ads 通道需要 adapter_kwargs.family"
                f"（MVP 可选 {sorted(ADS_CIRCUIT_PARAM_MAP)}）")
        if not snp_raw:
            raise ValueError("ads 通道需要 adapter_kwargs.snp_path（器件 Touchstone）")
        if kwargs:
            raise ValueError(f"ads 通道未知 adapter_kwargs: {sorted(kwargs)}")
        adapter = AdsOptAdapter(
            (float(freq_range[0]), float(freq_range[1])), int(freq_points),
            family=family, snp_path=Path(snp_raw), runner=runner,
            ads_dir=ads_dir, work_root=work_root)
        if not adapter.connect({}):
            return None, ""
        return adapter, "ads"
    except Exception as e:  # 宽兜同 openems 通道：原因在 warning 日志可见
        logger.warning("ads 适配器创建失败: %s", e, exc_info=True)
        return None, ""


def register_ads_channel() -> None:
    """把 ads 通道注册进 optimizer 通道注册表（幂等，后注册者胜）。"""
    from rfauto.optimization.adapter_channels import register_channel

    register_channel("ads", _create_ads_channel)


# 模块导入即注册（linkage → optimization 合法向下 import；既有三通道
# 零变化）。消费面先 import 本模块再 run_optimization(adapter_name="ads")。
register_ads_channel()

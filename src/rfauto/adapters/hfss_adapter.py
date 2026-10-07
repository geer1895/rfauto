"""HfssAdapter — HFSS SimulatorAdapter 实现（P0 桩实现）。

委托 HfssSession 管理 gRPC 连接，实现核心八方法接口。
P0 阶段：桩实现，核心方法抛出 NotImplementedError 并给出实现指引。
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Hashable, Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.adapters.hfss_builder_utils import validate_object_name
from rfauto.adapters.hfss_session import HfssSession, remote_session_switches
from rfauto.core.coupled_mode_z import DualConductorModeImpedances
from rfauto.core.coupled_mode_z import (
    dual_conductor_mode_impedances as _dual_conductor_mode_impedances,
)
from rfauto.core.errors import ModelBuildError, SimulationFailedError
from rfauto.core.interfaces import (
    AdapterCapabilities,
    SimulatorAdapter,
    SolveReport,
)

logger = logging.getLogger(__name__)

# ─── profile 状态解析（导出前置 sweep 完成断言，方案 §10.9 / #191 家族） ────

# .profile 文本行形态（r2-r4 真机实证，引号在文件中写作 \' 转义）：
#   状态脚注：ProfileFootnote('I(2, 1, \'Stop Time\', \'...\', 1,
#             \'Status\', \'Engine Detected Error\')', 2)
#   引擎诊断：ProfileItem(..., 'I(1, 0, \'***Port P1sheetP does not have
#             a solved inside material on either side.\')', ...)
_PROFILE_STATUS_RE = re.compile(r"Status\\?',\s*\\?'([^'\\]+)")
_PROFILE_ERROR_MSG_RE = re.compile(r"\*{3}(.+?)(?:\\'|'|\)|$)")

# profile 状态中被判为"未完成"的关键字（大小写不敏感）
_PROFILE_FAILURE_KEYWORDS = ("error", "abort", "terminat")


def parse_profile_text(text: str) -> tuple[str | None, list[str]]:
    """从 .profile 文本提取 (求解状态, 引擎 "***" 诊断消息列表)。

    状态来自 ProfileFootnote 的 ``'Status'`` 键（正常完成 =
    ``Normal Completion``；引擎检测到错误 = ``Engine Detected Error``）；
    诊断消息是 ``***`` 前缀的引擎错误行——r2-r4 实证端口级建模错误
    只在此处可见（``Engine Detected Error`` + 4-7s 静默败）。

    Returns
    -------
    tuple[str | None, list[str]]
        (状态文本或 None, 诊断消息列表)；空文本返回 (None, [])。
    """
    if not text:
        return None, []
    status_match = _PROFILE_STATUS_RE.search(text)
    status = status_match.group(1).strip() if status_match else None
    messages: list[str] = []
    for message_match in _PROFILE_ERROR_MSG_RE.finditer(text):
        msg = message_match.group(1).strip()
        if msg:
            messages.append(msg)
    return status, messages

# ─── Touchstone 端口数通用化（1/N 端口一律按实际，不写死 2 端口） ───────────
# wp34 patch GT 战役 2026-09-16 实证：插件契约声明 2 端口而单馈 patch 的 HFSS
# 设计实际 1 端口，原扩展名修正条件 ``n_ports >= 2`` 恰好排除了单端口——
# 1 端口数据落进 .s2p 后 skrf 按 2x2 reshape 抛 "cannot reshape array of
# size N into shape (4,newaxis)"。skrf 只从 .sNp 扩展名推断 rank，因此
# 扩展名必须由**实际端口数**决定。

#: 端口数推断的搜索上限（Touchstone 1.0 实用范围；更多端口按 None 交给调用方）
_MAX_INFER_PORTS = 64


def infer_touchstone_port_count(source: str | Path) -> int | None:
    """从 Touchstone 1.0 数据行结构反推端口数（不依赖扩展名）。

    skrf 实测行形态（write_touchstone 与 HFSS ExportNetworkData 同规范）：
    1 端口=每行 3 值；2 端口=每行 9 值（单行特例）；N>=3 端口=每频点一个
    多行块，首行 ``1 + 2*min(N, 4)`` 值、块内共 ``N * ceil(N/4)`` 行。首行
    9 值在 2/4/5+ 端口间歧义，故用"到下一个含频率行之前的块行数"消歧。

    Parameters
    ----------
    source : str | Path
        Touchstone 文件路径，或直接传文件文本（含换行即视为文本）。

    Returns
    -------
    int | None
        推断出的端口数；无数据行或结构不匹配任何端口数时返回 None（不猜）。
    """
    text = str(source)
    if "\n" not in text:
        try:
            text = Path(text).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
    rows: list[int] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("!", "#", "[")):
            continue
        rows.append(len(s.split("!")[0].split()))
    if not rows:
        return None
    first = rows[0]
    # 块行数 = 首行到下一个与首行同值数的行之前的行数（N>=3 时块内其余行
    # 值数恒 != 首行值数；1/2 端口每行独立成块，得 1）
    block = 1
    while block < len(rows) and rows[block] != first:
        block += 1
    if first == 3 and block == 1:
        return 1
    if first == 9 and block == 1:
        return 2
    for n in range(3, _MAX_INFER_PORTS + 1):
        if first == 1 + 2 * min(n, 4) and block == n * (-(-n // 4)):
            return n
    return None


def touchstone_path_for_ports(path: str | Path, n_ports: int | None) -> Path:
    """按实际端口数纠正 .sNp 扩展名（n_ports 未知或已一致则原样返回）。"""
    path = Path(path)
    if not n_ports or n_ports < 1:
        return path
    suffix = f".s{int(n_ports)}p"
    if path.suffix.lower() == suffix:
        return path
    corrected = path.with_suffix(suffix)
    logger.warning("请求的扩展名 %s 与实际端口数 %d 不符，修正为 %s",
                   path.suffix or "<无>", n_ports, corrected.name)
    return corrected


def contract_for_port_count(contract: Any, n_ports: int | None) -> Any:
    """契约端口数与实际端口数不符时，按实际端口数重建 TouchstoneContract。

    契约的端口数来自插件的 ``n_ports`` 声明，实际端口数来自 HFSS 设计
    （``hfss.ports``）或导出文件的数据列数——二者不一致是插件元数据与建模
    的不一致（如 patch 单馈天线声明 2 端口），不是数据错误。此处以实际数据
    为准重建 port_order（``input`` + 严格递增 ``output_i``），参考阻抗、频率
    单位、格式等其余字段原样沿用，参考阻抗校验因此仍然生效；并 warning
    留痕，绝不静默。``n_ports`` 未知（None）或已一致时原样返回。
    """
    if not n_ports or n_ports < 1 or contract is None:
        return contract
    port_order = getattr(contract, "port_order", None)
    if port_order is None or len(port_order) == int(n_ports):
        return contract
    from rfauto.core.contracts import TouchstoneContract

    new_order = ["input"] + [f"output_{i}" for i in range(1, int(n_ports))]
    logger.warning(
        "契约声明 %d 端口 %s 与 HFSS 实际端口数 %d 不符——按实际端口数校验 "
        "(port_order=%s)，请核对插件 n_ports 声明与建模是否一致",
        len(port_order), list(port_order), n_ports, new_order,
    )
    if isinstance(contract, TouchstoneContract):
        return contract.model_copy(update={"port_order": new_order})
    return TouchstoneContract(
        renormalization_ohm=getattr(contract, "renormalization_ohm", 50.0),
        port_order=new_order,
    )


# 延迟导入标记（pyaedt 仅在 adapter 内使用）
_Hfss = None
def _ensure_hfss():
    global _Hfss
    if _Hfss is None:
        try:
            from ansys.aedt.core import Hfss
            _Hfss = Hfss
        except ImportError as exc:
            raise ImportError(
                f"pyaedt 未安装，请运行: uv sync --extra hfss（原始错误: {exc}）"
            ) from exc
    return _Hfss


def _env_positive_int(name: str, allow_auto_minus1: bool = False) -> int | None:
    """EC-5 HPC 旋钮 env 兜底解析（缺省未设=None；非法值显式拒绝）。

    #364 家法：显式非法值（0/负/非整数）是配置错误必须 fail-loud，
    禁止静默回落单核假跑；``allow_auto_minus1`` 容许 pyaedt tasks=-1
    auto 档（analyze_setup docstring 批量求解语义）。
    """
    import os as _os

    raw = _os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = float(raw)
        ivalue = int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"环境变量 {name}={raw!r} 不是合法整数（HPC 旋钮 fail-loud）"
        ) from None
    if ivalue != value or (ivalue < 1 and not (
            allow_auto_minus1 and ivalue == -1)):
        raise ValueError(
            f"环境变量 {name}={raw!r} 越域（需 ≥1"
            + ("，tasks 容许 -1=auto" if allow_auto_minus1 else "")
            + "）")
    return ivalue


class HfssAdapter(SimulatorAdapter):
    """HFSS 仿真适配器。

    通过 gRPC 连接 AEDT Desktop，执行几何建模、求解和 S 参数提取。

    使用方式::

        adapter = HfssAdapter()
        adapter.connect({"desktop_version": "2024.1", "non_graphical": True})
        adapter.open_or_create_project("path/to/project.aedt", "my_design")
        adapter.set_variables({"patch_length": "30mm", "patch_width": "24mm"})
        adapter.build_and_setup(my_builder_func, setup_config)
        report = adapter.solve("Setup1")
        network = adapter.get_sparams()
        adapter.export_touchstone("output.s2p", contract)
        adapter.close()

    Attributes
    ----------
    session : HfssSession
        底层 AEDT 会话管理器。
    """

    def __init__(self) -> None:
        self.session = HfssSession.instance()
        self._project_path: Path | None = None
        self._design_name: str | None = None

    # ─── 核心八方法实现 ──────────────────────────────────────────────────────

    def connect(self, settings: dict[str, Any]) -> None:
        """幂等连接到 AEDT Desktop。

        Parameters
        ----------
        settings : dict
            连接配置，传递给 HfssSession.connect()。
        """
        self.session.connect(settings)

    def open_or_create_project(self, path: str | Path, design_name: str) -> None:
        """打开或创建 HFSS 项目。"""
        from pathlib import Path as StdPath

        Hfss = _ensure_hfss()
        path = StdPath(path)
        self._project_path = path
        self._design_name = design_name

        # 2025.1 gRPC（#191）：本方法是唯一的 Hfss 实例创建点——
        # connect() 只建 Desktop；双 Hfss 实例共存会让后建实例的
        # 设计变量管理器失效（GetVariables 返回 None/Rename gRPC 失败，
        # 2023.1 可用、属版本漂移）。

        # 远程会话分支（多机协同 v0）：session 配置了 remote_machine 时
        # path 是**服务器侧**路径——不创建本地父目录、不按本地存在性判定；
        # Hfss 透传 machine/port（远程 project 路径按服务器文件系统解释）。
        remote = self.session.remote_info
        if remote:
            # 远程 Hfss 构造窗口（review-fix1 v1 锚闭合）：Hfss 构造期与
            # Desktop 构造期消费同一组远程四开关（grpc_local/grpc_secure_mode/
            # remote_rpc_session/PYAEDT_USE_PRE_GRPC_ARGS）——connect() 的 CM
            # 在 Desktop attach 完成时已恢复缺省，本方法是**第二个构造窗口**，
            # 两窗口独立进出互不干扰。CM 内先临时置 remote_rpc_session=None
            # 。
            from ansys.aedt.core.generic.settings import settings as aedt_settings

            with remote_session_switches():
                aedt_settings.remote_rpc_session = None
                hfss = Hfss(project=str(path), design=design_name, solution_type="DrivenModal",
                            non_graphical=self.session._settings.get("non_graphical", True),
                            new_desktop=False,
                            machine=remote["machine"], port=remote["port"])
            logger.info("[remote=%s] 打开或创建项目（服务器侧路径，本地存在性不判定）: %s",
                        remote["name"], path)
        else:
            # Hfss(project=...) 打开已有项目与新build项目为同一调用；不存在时父目录先行创建
            parent = path.parent
            if not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)
            hfss = Hfss(project=str(path), design=design_name, solution_type="DrivenModal",
                        non_graphical=self.session._settings.get("non_graphical", True),
                        new_desktop=False)
            logger.info("%s: %s", "打开已有项目" if path.exists() else "创建新项目", path)

        # 2025.1 gRPC（#191）：新建项目/设计后变量管理器存在延迟就绪窗
        # （GetVariables 返回 None，实测可到 ~10s 量级）——就绪探测后再
        # 返回，否则首批 set_variables 必崩（仲裁脚本 r2 实测）。
        for _ in range(30):
            try:
                if hfss.odesign is not None and \
                        hfss.odesign.GetVariables() is not None:
                    break
            except Exception:
                pass  # 就绪窗内任何 gRPC 抖动/暂态异常都按"未就绪"处理，宽兜后继续轮询（#191 实测 ~10s）
            time.sleep(2)

        # 缓存到 session
        self.session.hfss = hfss

    def set_variables(self, vars: dict[str, str]) -> None:
        """设置设计变量。"""
        hfss = self.session.hfss
        if hfss is None:
            raise ModelBuildError("HFSS 未连接，请先调用 connect() 和 open_or_create_project()")

        for name, value in vars.items():
            hfss[name] = value
            logger.debug("设置变量: %s = %s", name, value)

    def build_and_setup(
        self,
        builder: Callable[[SimulatorAdapter], None],
        setup: Any,
    ) -> None:
        """执行构建器函数 + 配置求解器设置。"""
        hfss = self.session.hfss
        if hfss is None:
            raise ModelBuildError("HFSS 未连接")

        # 执行构建器（创建几何、端口、边界）
        builder(self)

        # 配置求解器设置（setup 为配方 setup 段 dict）
        if isinstance(setup, dict):
            self.configure_setup(setup)

    def configure_setup(self, setup_cfg: dict) -> str:
        """按配方 setup 段创建 Setup + Sweep，返回 setup 名。

        setup_cfg 支持键：name/sweep_name/freq_range_ghz/points/
        convergence_delta/max_passes。
        """
        hfss = self.session.hfss
        if hfss is None:
            raise ModelBuildError("HFSS 未连接")

        setup_name = setup_cfg.get("name", "Setup1")
        freq_range = setup_cfg.get("freq_range_ghz", [2.3, 2.5])
        fstart, fstop = float(freq_range[0]), float(freq_range[1])
        points = int(setup_cfg.get("points", 101))

        new_setup = hfss.create_setup(name=setup_name)
        # 自适应求解频率取频段中点
        new_setup.props["Frequency"] = f"{(fstart + fstop) / 2}GHz"
        new_setup.props["MaxDeltaS"] = float(setup_cfg.get("convergence_delta", 0.02))
        new_setup.props["MaximumPasses"] = int(setup_cfg.get("max_passes", 12))
        new_setup.update()

        sweep_name = setup_cfg.get("sweep_name", "Sweep1")
        hfss.create_linear_count_sweep(
            setup=setup_name,
            unit="GHz",
            start_frequency=fstart,
            stop_frequency=fstop,
            num_of_freq_points=points,
            name=sweep_name,
            save_fields=False,
        )
        logger.info("创建 Setup '%s' + Sweep '%s': %.3f-%.3f GHz, %d 点",
                   setup_name, sweep_name, fstart, fstop, points)
        return setup_name

    @staticmethod
    def _extract_convergence(setup) -> tuple[int, float]:
        """从 setup.get_profile() 提取 (adaptive_passes, final_delta_s)。

        pyaedt 1.4.0 正确 API：``setup.get_profile()`` 返回 ``Profiles`` 映射，
        每个 ``SimulationProfile`` 有 ``num_adaptive_passes``，其
        ``adaptive_pass.steps[<最后 Pass>].delta_s_max`` 是末次自适应 delta S。

        旧路径 ``getattr(setup, "passes", 0)`` 在 1.4.0 恒为 0（已知待办 #1）。
        任何异常回退 (0, 0.0)，不影响主流程。
        """
        try:
            profiles = setup.get_profile()
        except Exception:
            return 0, 0.0
        # Profiles 是 Mapping；空映射的真值为 False（无需 len）
        if not profiles:
            return 0, 0.0
        try:
            key = next(iter(profiles.keys()))
            sim_profile = profiles[key]
            passes = int(sim_profile.num_adaptive_passes)
            delta_s = 0.0
            ap = getattr(sim_profile, "adaptive_pass", None)
            if ap is not None:
                step_names = ap.process_steps or []
                pass_names = [s for s in step_names if "Pass" in s]
                if pass_names and hasattr(ap, "steps"):
                    last = ap.steps[pass_names[-1]]
                    delta_s = float(getattr(last, "delta_s_max", 0.0) or 0.0)
            return passes, delta_s
        except Exception:
            return 0, 0.0

    @staticmethod
    def _profile_status(hfss: Any, setup_name: str) -> tuple[bool, str | None, list[str]]:
        """读取 setup 最新求解 profile 的 (是否找到, 状态, 引擎诊断消息)。

        双来源（都只读，best-effort，异常一律降级为"未找到"不影响主流程
        ——观测性代码不阻塞真机求解，#105）：
        1. 活态 API ``hfss.get_profile(setup_name)``（pyaedt 1.4 官方口，
           返回 Profiles 映射，SimulationProfile.status 即求解状态）；
        2. 磁盘 .profile 兜底（``<project>.aedtresults/<design>.results/``
           下 mtime 最新的 *.profile）——``***`` 引擎诊断行只有这里全量
           可见（求解失败先读 profile）。
        """
        # 来源 1：活态 API（状态）
        status: str | None = None
        try:
            profiles = hfss.get_profile(setup_name)
        except Exception as exc:
            logger.debug("get_profile(%s) 异常: %s", setup_name, exc)
            profiles = None
        if profiles:
            try:
                for sim_profile in profiles.values():
                    live_status = getattr(sim_profile, "status", None)
                    if live_status:
                        status = str(live_status)
                        break
            except Exception as exc:
                logger.debug("遍历 Profiles 异常: %s", exc)

        # 来源 2：磁盘 .profile（最新一份）——状态兜底 + "***" 引擎诊断行
        # 增强（诊断行只有 .profile 全量可见，活态 API 不回传，r2-r4 实证）
        messages: list[str] = []
        try:
            results_dir = (
                Path(hfss.project_path)
                / f"{hfss.project_name}.aedtresults"
                / f"{hfss.design_name}.results"
            )
            candidates = sorted(
                results_dir.glob("*.profile"), key=lambda p: p.stat().st_mtime
            )
            if candidates:
                text = candidates[-1].read_text(encoding="utf-8", errors="ignore")
                disk_status, messages = parse_profile_text(text)
                if status is None:
                    status = disk_status
        except Exception as exc:
            logger.debug("读取磁盘 profile 异常: %s", exc)

        if status is not None or messages:
            return True, status, messages
        return False, None, []

    def assert_sweep_completed(self, setup_name: str, sweep_name: str | None = None) -> None:
        """导出前置 sweep 完成断言（方案 §10.9，#191 家族 r2-r4）。

        在导出/读取 S 参数之前显式确认求解已真正完成；未完成
        （仍在求解 / 引擎报错 / 无解）→ 抛 :class:`SimulationFailedError`，
        绝不读入中间或未收敛数据，也绝不落入"旧文件自动兜底"读到陈旧解。

        三层检查（官方 PyAEDT API，pyaedt 1.4 / AEDT 2025.1 语义）：

        1. ``hfss.are_there_simulations_running``——求解仍在进行（"挂起"
           形态的真身；该属性 2023.2+ 可用，异常降级跳过）；
        2. profile 状态（:meth:`_profile_status`）——``Engine Detected
           Error`` 即抛出并附 ``***`` 引擎诊断行（r2-r4：端口级建模错误
           在此显形，而 pyaedt 日志仍打 "solved correctly"）；
        3. ``hfss.get_setup(setup_name).is_solved``——解可用性官方查询
           （solve_setup.py ``is_solved``）。

        无 profile 且无解 = 从未求解完成，同样拒绝。

        Raises
        ------
        SimulationFailedError
            sweep/求解未真正完成（含引擎诊断消息与官方文档指引）。
        """
        hfss = self.session.hfss
        if hfss is None:
            raise ModelBuildError("HFSS 未连接")

        # 检查 1：求解是否仍在进行（挂起形态）
        try:
            if hfss.are_there_simulations_running:
                raise SimulationFailedError(
                    f"导出前置断言失败：setup '{setup_name}' 求解仍在进行中"
                    "（sweep 未完成），拒绝导出中间数据"
                )
        except SimulationFailedError:
            raise
        except Exception as exc:
            # 2023.2 前不可用/通道抖动 → 降级跳过（正证据不足不拦）
            logger.debug("are_there_simulations_running 查询失败（跳过）: %s", exc)

        # 检查 2：profile 状态（引擎层完成证据）
        found, status, engine_msgs = self._profile_status(hfss, setup_name)
        if found and status and any(
            keyword in status.lower() for keyword in _PROFILE_FAILURE_KEYWORDS
        ):
            detail = "；".join(engine_msgs) if engine_msgs else "（详见 .profile 文件）"
            raise SimulationFailedError(
                f"导出前置断言失败：setup '{setup_name}' 求解未完成——"
                f"profile 状态={status}，引擎诊断: {detail}。"
                "修复路径=官方文档（Ansys Help / Wave Port Size 等端口与"
                "边界口径）→ 官方例惯例，先读 .profile 定位真因"
            )
        if not found:
            raise SimulationFailedError(
                f"导出前置断言失败：setup '{setup_name}' 无求解 profile"
                "（sweep 从未完成），拒绝导出"
            )

        # 检查 3：解可用性（官方 is_solved 查询）
        try:
            setup = hfss.get_setup(setup_name)
            if setup is not None and not setup.is_solved:
                raise SimulationFailedError(
                    f"导出前置断言失败：setup '{setup_name}' 无可用解"
                    "（is_solved=False），拒绝导出"
                )
        except SimulationFailedError:
            raise
        except Exception as exc:
            logger.debug("is_solved 查询失败（跳过）: %s", exc)

        logger.info("导出前置断言通过: setup=%s sweep=%s status=%s",
                    setup_name, sweep_name, status)

    def solve(
        self,
        setup_name: str,
        timeout_s: int = 3600,
        cores: int | None = None,
        tasks: int | None = None,
    ) -> SolveReport:
        """调用 analyze_setup 并轮询等待完成。

        EC-5 HPC 旋钮（2026-10-05）：``cores``/``tasks`` 显式传入
        ``hfss.analyze_setup``（pyaedt 1.4.0 签名原生参数——**这是直连
        Desktop 路线唯一生效的核数入口**；``settings.num_cores`` 只喂
        LSF 启动命令，对直连求解无作用，#222 接地勘误）。缺省双 None=
        analyze_setup 内部跳过 HPC 分支，调用形态逐字节不变（判据①）。
        env 兜底 ``RFAUTO_HFSS_SOLVE_CORES``/``_TASKS``（配置面走既有
        通道，不加 CLI 叶，spec 4.2③）；非法值 fail-loud 拒解。

        超时强杀（计划内缺口 7）：Watchdog 计时器到点后从监控线程调用
        odesign.Abort() 中止求解；Abort 成功打断求解才判超时失败。
        竞态保护（2026-09-03 真机教训）：watchdog 到点但 Abort 失败说明
        analyze_setup 实际已正常返回（求解完成）——此时接受真实结果，
        不得把已算完的解当超时丢弃（曾把 93 分钟的正确求解白白扔掉）。
        超时可用环境变量 RFAUTO_HFSS_SOLVE_TIMEOUT_S 覆盖（秒）。
        """
        hfss = self.session.hfss
        if hfss is None:
            raise ModelBuildError("HFSS 未连接")

        import os

        from rfauto.pipeline.watchdog import Watchdog

        # EC-5：cores/tasks env 兜底解析（显式传参优先）。配置错误在
        # watchdog/try 之外显式抛出（fail-loud——进 try 会被 except 吞成
        # "求解失败"假象，配置错≠求解错）。
        if cores is None:
            cores = _env_positive_int("RFAUTO_HFSS_SOLVE_CORES")
        if tasks is None:
            tasks = _env_positive_int(
                "RFAUTO_HFSS_SOLVE_TASKS", allow_auto_minus1=True)
        if cores is not None or tasks is not None:
            logger.info(
                "HFSS HPC 求解档：cores=%s tasks=%s（analyze_setup "
                "Distributed 分支，setup=%s）", cores, tasks, setup_name)

        timeout_s = float(
            os.environ.get("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "") or timeout_s
        )
        watchdog = Watchdog()
        aborted = False

        def _abort_on_timeout() -> None:
            # 强杀路径：AEDT COM 层 Abort 中止当前 setup 求解，
            # 使阻塞中的 analyze_setup 尽快返回。失败不抛（仅日志）；
            # Abort 成功才置 aborted——只有真打断才算超时（见 docstring）。
            nonlocal aborted
            try:
                odesign = getattr(hfss, "odesign", None)
                if odesign is not None:
                    odesign.Abort()
                    aborted = True
                    logger.warning("求解超时(%ss)，已调用 odesign.Abort()", timeout_s)
            except Exception as abort_exc:
                logger.warning("超时 Abort 调用失败（analyze 返回后按超时处理）: %s", abort_exc)

        start_time = time.time()
        watchdog.start(timeout_s=float(timeout_s), callback=_abort_on_timeout)
        try:
            # 条件透传（df6③ 家法：缺省 None 时不加新 kwargs——旧
            # stub/调用方的 analyze_setup 签名零冲击，缺省调用形态
            # 逐字节不变 #329）
            _hpc_kwargs: dict[str, int] = {}
            if cores is not None:
                _hpc_kwargs["cores"] = cores
            if tasks is not None:
                _hpc_kwargs["tasks"] = tasks
            # 使用 hfss.analyze_setup() 而非 setup.analyze()
            # setup.analyze() 在 pyaedt 1.4.0 中返回 None（非 bool），导致 not success 永远为 True
            success = hfss.analyze_setup(
                name=setup_name, blocking=True, **_hpc_kwargs)
        except Exception as exc:
            logger.error("求解出错: %s", exc)
            return SolveReport(
                success=False,
                passes=0,
                delta_s_final=0.0,
                wall_time_s=time.time() - start_time,
                message=str(exc),
            )
        finally:
            watchdog.cancel()
        elapsed = time.time() - start_time

        if watchdog.fired and aborted:
            return SolveReport(
                success=False,
                passes=0,
                delta_s_final=0.0,
                wall_time_s=elapsed,
                message=f"求解超时（>{timeout_s}s），已调用 Abort 强杀",
            )
        if watchdog.fired and not aborted:
            logger.warning(
                "watchdog 到点但求解已自行完成（耗时 %.0fs > %ss 超时阈值），"
                "接受真实结果；建议调大 RFAUTO_HFSS_SOLVE_TIMEOUT_S",
                elapsed, timeout_s,
            )

        if not success:
            return SolveReport(
                success=False,
                passes=0,
                delta_s_final=0.0,
                wall_time_s=elapsed,
                message="求解失败",
            )

        # profile 状态复核（#191 家族）：pyaedt analyze_setup 吞掉引擎异常
        # 后仍统一打 "solved correctly" 日志（analysis.py:2098 无条件打印），
        # 返回 True ≠ 引擎层完成——profile 状态为引擎错误时如实判失败，
        # 并附引擎诊断消息（r2-r4：4-7s 静默败只在此显形）。
        _found, _status, _msgs = self._profile_status(hfss, setup_name)
        if _status and any(
            keyword in _status.lower() for keyword in _PROFILE_FAILURE_KEYWORDS
        ):
            detail = "；".join(_msgs) if _msgs else "（详见 .profile 文件）"
            logger.error("引擎检测到求解错误（profile 状态=%s）: %s", _status, detail)
            return SolveReport(
                success=False,
                passes=0,
                delta_s_final=0.0,
                wall_time_s=elapsed,
                message=f"引擎检测到求解错误（profile 状态={_status}）: {detail}",
            )

        # 收敛信息：pyaedt 1.4.0 用 get_profile()（getattr 恒 0，已弃用）
        setup = hfss.get_setup(setup_name)
        if setup:
            passes, delta_s = self._extract_convergence(setup)
        else:
            passes, delta_s = 0, 0.0

        logger.info("求解完成: %s, passes=%d, delta_s=%.4f, 耗时=%.1fs",
                    setup_name, passes, delta_s, elapsed)
        return SolveReport(
            success=True,
            passes=passes,
            delta_s_final=delta_s,
            wall_time_s=elapsed,
            message="求解成功",
        )

    def get_sparams(self) -> Any:
        """提取 S 参数并返回 skrf.Network。"""
        import skrf as rf

        hfss = self.session.hfss
        if hfss is None:
            raise ModelBuildError("HFSS 未连接")

        # 简化实现：先导出临时的 Touchstone 文件，然后用 skrf 读取
        # 更优方式是直接从 get_touchstone_data() 获取，但需要进一步调研 API
        # 临时文件后缀只是占位——export_touchstone 会按 HFSS 实际端口数（含 1）
        # 纠正为 .sNp 并返回真实路径。
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".s2p", delete=False) as tmp:
            tmp_path = tmp.name

        # export_touchstone 可能自动修正扩展名（.sNp 按端口数），须用返回的实际路径
        exported = self.export_touchstone(tmp_path)
        try:
            network = rf.Network(exported)
        except Exception:
            # 扩展名 rank 与文件内容不符（hfss.ports 取不到时的兜底，2026-08-31
            # patch 调谐真机发现）：按数据行结构反推真实端口数，重命名后重读
            # （Touchstone 内容不依赖扩展名，无需重导出）。
            n_guess = self._infer_port_count(Path(exported))
            if n_guess and n_guess >= 1:
                corrected = touchstone_path_for_ports(Path(exported), n_guess)
                if corrected != Path(exported):
                    Path(exported).replace(corrected)
                    exported = corrected
                network = rf.Network(exported)
            else:
                raise

        # 清理临时文件
        Path(tmp_path).unlink(missing_ok=True)
        Path(exported).unlink(missing_ok=True)

        logger.info("提取 S 参数: %d 端口, %d 频点", network.nports, network.frequency.npoints)
        return network

    @staticmethod
    def _infer_port_count(path: Path) -> int | None:
        """从 Touchstone 数据行结构反推端口数（委托模块级通用推断，1/N 端口）。"""
        try:
            return infer_touchstone_port_count(Path(path))
        except Exception:
            return None

    @staticmethod
    def _design_port_count(hfss: Any) -> int | None:
        """HFSS 设计实际端口数（**Σ模数口径**，多模波端口按 Modes 累加）。

        Touchstone 导出的是模态矩阵（Σ模数×Σ模数，#307 双模波端口端子组、
        #309 hairpin 锚 .s4p 先例）：按端口边界数计数会把 2 端口×2 模设计的
        4×4 数据改名 .s2p（#248 复发面——skrf 按扩展名推断 rank 抛
        IndexError）。单端口边界模数=BoundaryObject.props["Modes"]（缺省 1，
        集总端口无该键按 1 模）；boundaries 查询失败退回端口边界数口径，
        ports 查询整体失败返回 None 交给文件推断（R4-1 审查批 2026-10-04，
        runs/review_ge8e/r4_adapters/REPORT.md）。
        """
        try:
            names = list(hfss.ports)
        except Exception:
            return None
        if not names:
            return None
        boundaries = None
        try:
            boundaries = list(hfss.boundaries)
        except Exception:
            boundaries = None

        def _modes(name: str) -> int:
            for b in boundaries or ():
                if getattr(b, "name", None) == name:
                    try:
                        m = int((b.props or {}).get("Modes", 1))
                    except Exception:
                        return 1
                    return m if m >= 1 else 1
            return 1

        total = sum(_modes(str(n)) for n in names)
        return int(total) if total >= 1 else None

    def export_touchstone(
        self,
        path: str | Path,
        contract: Any = None,
    ) -> Path:
        """导出 Touchstone 文件并进行契约校验。"""
        from pathlib import Path as StdPath

        path = StdPath(path)
        hfss = self.session.hfss
        if hfss is None:
            raise ModelBuildError("HFSS 未连接")

        # 获取第一个 setup 和 sweep
        setups = hfss.get_setups()
        if not setups:
            raise ModelBuildError("未找到任何 setup")

        # get_setups() 返回字符串列表（非对象）
        setup_name = setups[0] if isinstance(setups[0], str) else setups[0].name
        sweeps = hfss.get_sweeps(setup_name)
        sweep_name = (sweeps[0] if isinstance(sweeps[0], str) else sweeps[0].name) if sweeps else None

        # 导出前置 sweep 完成断言（方案 §10.9，#191 家族 r2-r4）：求解未
        # 真正完成（仍在跑/引擎报错/无解）时显式报错，绝不读入中间或未
        # 收敛数据，也绝不落入旧文件自动兜底读到陈旧解。get_sparams()
        # 走本方法 → 读取路径同样被断言覆盖。
        self.assert_sweep_completed(setup_name, sweep_name)

        # Touchstone 规范要求扩展名 .sNp 中 N = 实际端口数；skrf 也只从扩展名
        # 推断 rank——3 端口存成 .s2p 无法解析，1 端口存成 .s2p 在 skrf 内部
        # reshape(4,-1) 抛 ValueError（wp34 patch GT 战役 2026-09-16 实证，原
        # 条件 n_ports >= 2 把单端口排除在修正之外）。端口数一律以 HFSS 设计
        # 实际端口数为准（含 1），请求的扩展名不符即修正。
        n_ports = self._design_port_count(hfss)
        path = touchstone_path_for_ports(path, n_ports)

        # pyaedt 1.4.0 的 export_touchstone 在导出前调用
        # available_variations.nominal_variation()，unite 后触发 GetObjType 崩溃，
        # 故直接调用底层 osolution.ExportNetworkData 绕过（空 DesignVariations = nominal 变体）
        try:
            self._direct_export_touchstone(hfss, setup_name, sweep_name, path)
        except Exception as exc:
            # 回退：pyaedt 包装方法（可能因 numeric_value 崩溃），或自动导出文件
            if not path.exists():
                try:
                    hfss.export_touchstone(setup=setup_name, sweep=sweep_name, output_file=str(path))
                except Exception as exc2:
                    logger.warning("pyaedt export_touchstone 也失败: %s", exc2)
            if not path.exists():
                found = self._find_auto_exported_touchstone(hfss, tmp_path=path.parent)
                if found:
                    logger.warning("使用自动导出的 Touchstone 文件: %s", found)
                    return found
            if not path.exists():
                raise ModelBuildError(f"Touchstone 导出失败: {exc}") from exc

        if not path.exists():
            raise ModelBuildError(f"Touchstone 导出失败: 文件未生成 {path}")

        # 设计端口数查询失败时，由导出文件的数据行结构反推端口数并纠正扩展名
        # （Touchstone 内容不依赖扩展名，重命名即可，无需重导出）
        if n_ports is None:
            inferred = self._infer_port_count(path)
            corrected = touchstone_path_for_ports(path, inferred)
            if corrected != path:
                path.replace(corrected)
                path = corrected
            n_ports = inferred

        logger.info("导出 Touchstone: %s", path)
        output_file = str(path)

        # 契约校验：导出后实际校验端口数 + 参考阻抗。契约端口数（插件声明）与
        # 实际端口数不一致时按实际端口数校验并 warning（contract_for_port_count）
        if contract is not None:
            from rfauto.adapters.interchange import read_touchstone
            from rfauto.core.contracts import AdsExchangeContract
            tc = contract.touchstone if isinstance(contract, AdsExchangeContract) else contract
            tc = contract_for_port_count(tc, n_ports)
            read_touchstone(output_file, tc)

        return StdPath(output_file)

    @staticmethod
    def _direct_export_touchstone(
        hfss: Any,
        setup_name: str,
        sweep_name: str,
        path: Path,
    ) -> None:
        """直接调用 AEDT Solutions 模块导出 Touchstone（绕过 pyaedt 包装）。

        pyaedt 1.4.0 的 export_touchstone 在导出前会调用
        available_variations.nominal_variation()，modeler.unite() 后该路径
        触发 GetObjType Error。AEDT 的 ExportNetworkData 接受空
        DesignVariations（即 nominal 变体），可完全跳过该问题。
        """
        osolution = hfss.osolution
        if osolution is None:
            raise ModelBuildError("hfss.osolution 不可用（GetModule('Solutions') 返回空）")

        solution_selection = f"{setup_name}:{sweep_name}" if sweep_name else setup_name
        osolution.ExportNetworkData(
            "",                                    # DesignVariations（空 = nominal）
            [solution_selection],
            3,                                     # FileFormat: 3 = Touchstone (.sNp)
            str(path).replace("\\", "/"),          # OutFile
            ["all"],                               # FreqsArray
            False,                                 # DoRenorm
            50,                                    # RenormImped
            "S",                                   # DataType
            -1,                                    # Pass: -1 = all passes
            0,                                     # ComplexFormat: 0 = Mag/Phase
            15,                                    # DigitsPrecision
            False,
            False,                                 # IncludeGammaImpedance
            False,                                 # NonStandardExtensions
        )

    @staticmethod
    def _find_auto_exported_touchstone(hfss: Any, tmp_path: Path, max_age_s: int = 600) -> Path | None:
        """在常见目录中查找 export_touchstone_on_completion 自动导出的 .s2p 文件。"""
        import time as _time

        now = _time.time()
        candidates: list[Path] = []
        for d in (tmp_path, hfss.working_directory, hfss.project_path):
            if not d:
                continue
            p = Path(d)
            if not p.is_dir():
                continue
            try:
                # .sNp 全端口数（自动导出按实际端口数命名，1 端口是 .s1p）
                candidates.extend(p.glob("*.s[0-9]p"))
                candidates.extend(p.glob("*.S[0-9]P"))
            except OSError:
                continue
        # 取最近生成的文件
        candidates = [c for c in candidates if now - c.stat().st_mtime < max_age_s]
        if not candidates:
            return None
        return max(candidates, key=lambda c: c.stat().st_mtime)

    def close(self, save: bool = True) -> None:
        """关闭 HFSS 会话。

        Parameters
        ----------
        save : bool
            是否保存项目。
        """
        try:
            if save and self._project_path and self.session.hfss:
                self.session.hfss.save_project()
        except Exception as exc:
            logger.warning("保存项目时出错: %s", exc)
        finally:
            self.session.close(save=save)
            self._project_path = None
            self._design_name = None

    # ─── 可选方法层 ──────────────────────────────────────────────────────────

    def capabilities(self) -> AdapterCapabilities:
        """HFSS 适配器能力声明。"""
        return AdapterCapabilities(
            supports_wave_port=True,
            supports_lumped_port=True,
            supports_field_export=True,
            supports_convergence_report=True,
            supports_touchstone_export=True,
            supports_headless_solve=True,
            supports_optimetrics=True,
        )

    def health_check(self) -> bool:
        """检查 AEDT 连接是否存活。"""
        return self.session.health_check()

    def ensure_connected(self) -> None:
        """自愈重连（缺口 4 R5）：license 回收/掉线后带退避重建会话。"""
        self.session.reconnect_with_backoff()

    def get_far_field(
        self, setup_name: str, freq_ghz: float = 2.4
    ) -> dict[str, Any] | None:
        """获取远场方向图（GainTotal，Theta 全角度扫描，Phi=0 切面）。

        需要已完成求解的 setup 与辐射边界（军规：可选方法先查
        capabilities().supports_field_export）。缺无限球面时自动创建，
        复用已存在的同名球面。返回契约与 FakeAdapter 一致：
        {theta, phi, gain_db, pattern_type, freq_ghz}；不支持/失败返回 None。

        pyaedt 1.4.0 API（inspect 确认）：
        - ``hfss.insert_infinite_sphere(theta_start, ..., name=...)``
        - ``hfss.post.get_far_field_data(expressions="GainTotal",
          setup_sweep_name="<setup>:LastAdaptive", domain=<sphere>,
          sweeps={...}) -> SolutionData``
        - ``SolutionData.intrinsics["Theta"]`` / ``get_expression_data(...)``
        """
        import numpy as np

        hfss = self.session.hfss
        if hfss is None:
            raise ModelBuildError("HFSS 未连接")
        if not self.capabilities().supports_field_export:
            return None

        sphere_name = "InfiniteSphere1"
        try:
            hfss.insert_infinite_sphere(
                theta_start=0, theta_stop=180, theta_step=5,
                phi_start=0, phi_stop=360, phi_step=45,
                name=sphere_name,
            )
            logger.info("创建无限球面: %s", sphere_name)
        except Exception as exc:
            # 已存在同名球面会抛异常属正常；其他异常记录后继续（domain 查询兜底）
            logger.debug("insert_infinite_sphere(%s): %s（已存在则忽略）", sphere_name, exc)

        # pyaedt 1.4 实测（2026-08-30 真机）：
        # - sweeps 显式传 "Theta": ["All"] 时数据只回单变体（gain 长度 1），
        #   Theta 作为主扫描展开需要不传 Theta；
        # - get_expression_data 返回 (sweeps, values) 或直接数组，
        #   按长度与 theta 对齐者为准。
        def _extract(sd_obj):
            intr = sd_obj.intrinsics if isinstance(sd_obj.intrinsics, dict) else {}
            theta_raw = intr.get("Theta", [])
            theta = np.asarray(theta_raw, dtype=float).ravel()
            if len(theta) == 0:
                try:
                    theta = np.asarray(sd_obj.primary_sweep_values, dtype=float).ravel()
                except Exception:
                    theta = np.array([])  # 属性缺失/形态异常的兜底：空 θ 交上层 len==0 判"无可用解"
            if len(theta) == 0:
                return theta, None
            for call in (
                # pyaedt 1.4 实测：sweeps="Theta" 指定主扫描后返回
                # (theta数组, gain数组)；不带 sweeps 则按 primary_sweep(Freq)
                # 只返回单点
                lambda: sd_obj.get_expression_data("GainTotal", formula="real", sweeps="Theta"),
                lambda: sd_obj.get_expression_data("GainTotal", formula="real"),
            ):
                try:
                    data = call()
                except Exception:
                    continue  # 该返回形态调用失败即弃用，试下一候选形态（pyaedt 版本行为漂移容忍）
                parts = list(data) if isinstance(data, tuple) else [data]
                # (theta数组, gain数组) 形态：取最后一个与 theta 等长的数组
                # （第一个就是 theta 本身，真机实测）
                matched = None
                for part in parts:
                    if part is None:
                        continue
                    arr = np.asarray(part, dtype=float).ravel()
                    if len(arr) == len(theta):
                        matched = arr
                if matched is not None:
                    return theta, matched
            return theta, None

        theta = np.array([])
        gain = None
        for sweeps_kw in (
            {"Freq": [f"{freq_ghz}GHz"], "Phi": ["0deg"]},
            {"Freq": [f"{freq_ghz}GHz"], "Phi": ["0deg"], "Theta": ["All"]},
            {"Freq": ["All"], "Phi": ["0deg"]},
        ):
            try:
                candidate = hfss.post.get_far_field_data(
                    expressions="GainTotal",
                    setup_sweep_name=f"{setup_name}:LastAdaptive",
                    domain=sphere_name,
                    sweeps=sweeps_kw,
                )
            except Exception as exc:
                logger.debug("get_far_field_data(%s) 异常: %s", sweeps_kw, exc)
                continue
            if not candidate or not hasattr(candidate, "intrinsics"):
                continue
            theta, gain = _extract(candidate)
            if gain is not None:
                logger.info("远场数据获取成功: sweeps=%s", sweeps_kw)
                break
        # pyaedt 在无可用解时返回 False（真机实测），不是 SolutionData
        if gain is None:
            logger.warning(
                "远场无可用解或形状不一致（domain=%s, setup=%s:LastAdaptive, "
                "theta=%d）——返回 None",
                sphere_name, setup_name, len(theta),
            )
            return None

        theta_list = [float(t) for t in theta]
        gain_list = [round(float(g), 3) for g in gain]

        return {
            "theta": theta_list,
            "phi": [0.0],
            "gain_db": gain_list,
            "pattern_type": "GainTotal",
            "freq_ghz": freq_ghz,
        }

    # ─── HFSS 特有辅助方法 ──────────────────────────────────────────────────

    def dual_conductor_mode_impedances(
        self,
        zo_by_mode: Mapping[Hashable, float | Sequence[float]],
        eps_eff_by_mode: Mapping[Hashable, float | Sequence[float]],
    ) -> DualConductorModeImpedances:
        """双导体（耦合线对）模端口模阻抗基准换算（#307 单源薄封装）。

        把 HFSS Driven Modal 双导体端口的模阻抗读数换算为单线偶/奇模阻抗：
        模阻抗输出基准是共模 Zc=Z0e/2、差模 Zd=2·Z0o（**不是**单线偶/奇模
        阻抗，50Ω 归一 S 反演得到的同为此基准）；模序必须按 εeff 较高识别
        偶模（按 Z0 大小识别在该基准下反转，#307 首判 −22%/+29% DISAGREE
        即此翻车）。出处与口径全账见 core/coupled_mode_z 模块 docstring；
        本方法=纯函数薄封装（零 gRPC/零 session 触碰，未连接亦可调用），
        供仲裁脚本（scripts/hfss_hairpin_anchor.analyze_line_modes 同链）
        与未来消费者走单源。

        背景（F7 受阻登记收口）：ge8e 审查批 F7 建 core/coupled_mode_z
        单源时本适配器并发在制无法接线（审查 R4-4：换算链只活在 runs
        任务书 文档与战役脚本、无可复用实现）；本批（ge8e W1 A2）补挂。

        Args:
            zo_by_mode: 模键 → 模阻抗读数（Ω；单端口标量或多端口序列，
                序列先跨端口取算术均值）；至少两个模。
            eps_eff_by_mode: 模键 → 有效介电常数（同键面；同法取均值）。

        Returns:
            DualConductorModeImpedances（z0e_ohm/z0o_ohm/k_z 及识别依据）。

        Raises:
            ValueError: 模数 <2 / 键面不一致 / εeff 并列（识别歧义）/
                非正阻抗——与 core 单源同语义透传。
        """
        return _dual_conductor_mode_impedances(zo_by_mode, eps_eff_by_mode)

    def validate_design(self) -> list[str]:
        """检查设计中的对象命名是否符合规范。

        Returns
        -------
        list[str]
            违规的对象名称列表。
        """
        if not self.session.hfss:
            return []

        violations: list[str] = []
        try:
            # 获取所有几何对象
            object_names = self.session.hfss.modeler.object_names
            for name in object_names:
                try:
                    validate_object_name(name)
                except ModelBuildError:
                    violations.append(name)
        except Exception as exc:
            logger.warning("检查设计命名时出错: %s", exc)

        return violations

"""aedt_migrate 通道 Stage 1/2 执行器（2025 R1 直开 + 迁移体检）。

蓝图：aedt_migrate 批量迁移通道设计（2026-11-10 主会话交接稿）§1 决策树。
本模块是 Stage 1（直开尝试）与 Stage 2（体检）的**真实执行器**：对合作者
遗留的老版本 ``.aedt`` 工程，用 AEDT 2025 R1 非图形（``-ng`` 语义，PyAEDT
``non_graphical=True``）会话尝试直开，显式 SaveAs 到 ``migrated/`` 新目录，
然后在 2025 R1 会话内做迁移体检（validate + 消息全量收集 + 六项检查清单
存在性核对 + 可选 heal）。Stage 3（新旧结果对比）/Stage 4（2023 R2 桥接）/
Stage 5（抢救）不在本模块——service 层（aedt_migrate_service，AM-S1 席）
按本模块产出的事实映射蓝图 §1 verdict 枚举。

对接假设（2026-11-10 开工时点，AM-S1 service 文件未落树）：本席按蓝图
§1/§2 自定 executor 协议——service 消费 ``migrate_open_save_and_check()``
（Stage 1+2 一次到位、会话必关）或拆用 ``open_legacy_project()`` /
``save_as_migrated()`` / ``run_health_check()`` 三件自编排。结果 dict 的
``outcome`` 枚举与字段清单见各函数 docstring；``cutoff=True`` ⇔ 直开被
版本 cutoff 硬拒（→蓝图 Stage 4 桥接）；service 落树后若协议有出入，
以 service 声明为准适配（适配点预期只在本模块函数签名薄层）。

分层（AGENTS 规则 3）：adapters 层，可依赖 pipeline/infra/core，禁
import service/cli。会话生命周期复用 :mod:`rfauto.adapters.hfss_session`
（单例 ``HfssSession``，``connect``/``close``→``release_desktop``）。

坑账复用（本模块逐条落位）：

- #265：会话 finally 必 ``release_desktop``——wrapper 入口
  （:func:`migrate_open_save_and_check`）在 finally 走
  ``session.close(save=False)``（save=False：已显式 SaveAs，禁再触发
  任何隐式保存，原件只读铁律）；注入会话不代管；自建会话在
  :func:`open_legacy_project` 失败/占用路径就地关、成功路径留场待
  调用方收尾（活 app 句柄不能交死会话）。
- #374（家族）：本模块不起批处理进程（PyAEDT gRPC 会话直开路线），
  无命令行参数序问题；SaveAs 目标路径恒由调用方显式给出。
- 晶圆键合 §2.2（中文路径）：原件路径含非 ASCII 时默认 staging 到
  ASCII 临时目录（stage=True 缺省）；staging 根自身非 ASCII（%TEMP% 带
  用户名等）→ 显式 ValueError（P5 同款 fail-closed）。
- 晶圆键合 §2.3（.lock 占用）：直开前 :func:`detect_project_occupancy`
  证据链检测，占用即 ``outcome="locked"`` 结构化返回（不 raise，
  service 可如实记账）；fail-unknown 告警放行（同既有纪律）。
- 晶圆键合 §2.4（validate 解包）：``validate_full_design()`` 返回
  **(messages, ok)**——pyaedt 1.9.0 ``hfss.py:4770`` 签名
  ``-> tuple[list[str], bool]`` 实证；本模块唯一解包点
  ``messages, ok = ...`` 顺序钉死并有单测钉（解包反了 messages 当 bool
  即 TypeError/假 pass）。
- #215（禁凭想象写 API）：全部 pyaedt 调用先接地实读 venv 内
  pyaedt 1.9.0 源码（行号证据见 :data:`PYAEDT_API_GROUNDING`）；
  HFSS 3D Modeler 菜单级 "Check" 在 pyaedt 1.9 **无独立封装**
  （仅 3D Layout 有 ``GeometryCheckAndAutofix``，
  ``modeler/modeler_pcb.py:1459``）——体检以
  ``validate_full_design``（内部 ``oDesign.ValidateDesign``，
  ``application/design.py:4713 validate_simple``）为准；Heal 有封装
  （``modeler/cad/primitives.py:7033 heal_objects``）按 opt-in 使用；
  独立 Modeler-Check IronPython 脚本段只留模板常量
  (:data:`_MODEL_CHECK_SCRIPT_TEMPLATE`)，标注 UNVERIFIED-API，
  启用前调用即 NotImplementedError（留真机窗口验证）。

原件只读铁律：本模块对原 ``.aedt`` 只做读与拷贝（staging），一切写
（锁文件/AEDT 版本迁移自动备份/SaveAs 产物）都落在 ASCII staging 目录
或 ``migrated/`` 新目录。``stage=False`` 直开原件时 AEDT 打开动作本身
可能在其旁落版本迁移备份件——docstring 如实警示，缺省 stage=True 规避。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from rfauto.adapters.hfss_session import (
    HfssSession,
    detect_project_occupancy,
    has_non_ascii,
)

logger = logging.getLogger(__name__)

#: 迁移会话缺省 AEDT 版本（2026-11-10 本机口径：HFSS/AEDT 2025 R1，
#: AGENTS 规则 0 版本对齐基准）。可被 settings["desktop_version"] 覆盖。
MIGRATE_VERSION_DEFAULT = "2025.1"

#: cutoff 判定针（AND 语义，两针齐中才算版本 cutoff）。来源=Ansys 官方
#: 论坛 Jim Sherman 回复引述形态："Legacy project files can no longer be
#: opened in this version ... Please use release X or earlier to convert"。
#: 单针不判定：如 "...can no longer be opened because it is locked" 类
#: 无关报错只含第二针，不得误判 cutoff（有单测负例钉）。
CUTOFF_NEEDLES: tuple[str, ...] = (
    "legacy project files",
    "no longer be opened",
)

#: validate 消息里"几何类错误"启发式标记（小写子串，任一命中即
#: geometry_hint=True）。蓝图 §1：geometry 类错误 → Stage 5 抢救——
#: 本标记只是**路由提示**（heuristic），最终判归 service/人工，不凑绿。
GEOMETRY_HINT_MARKERS: tuple[str, ...] = (
    "geometry",
    "intersect",
    "heal",
    "invalid solid",
    "acis",
    "parasolid",
)

#: 体检六项检查清单（蓝图 §0-6 迁不过来清单的自动化存在性核对面）。
#: 每项 = pyaedt 1.9 接地访问器（见 PYAEDT_API_GROUNDING）+ 计数 +
#: 查询异常如实入账（available=False + error 原文，不凑绿）。
CHECKLIST_ITEMS: tuple[str, ...] = (
    "materials",
    "boundaries",
    "mesh_operations",
    "setups",
    "optimetrics_parametric",
    "optimetrics_optimization",
)

#: Stage 1 outcome 枚举（对接假设：service 按此映射蓝图 §1 verdict）：
#: - ``opened``      直开成功（save 单独记账，可能为 save_failed）
#: - ``cutoff``      命中版本 cutoff 硬拒（→ Stage 4 桥接）
#: - ``locked``      原件被 GUI/会话占用（.lock 证据链）
#: - ``open_failed`` 其他打开失败（FAILED(open) 如实）
#: - ``save_failed`` 打开成功但显式 SaveAs 失败（service 可映射 FAILED(open)）
OUTCOME_OPENED = "opened"
OUTCOME_CUTOFF = "cutoff"
OUTCOME_LOCKED = "locked"
OUTCOME_OPEN_FAILED = "open_failed"
OUTCOME_SAVE_FAILED = "save_failed"

#: pyaedt 1.9.0 API 接地证据表（venv 实读，#215 家法；升级 pyaedt 时须复验）。
PYAEDT_API_GROUNDING: dict[str, str] = {
    "validate_full_design": (
        "ansys/aedt/core/hfss.py:4770 "
        "validate_full_design(design=None, output_dir=None, ports=None) "
        "-> tuple[list[str], bool]——解包顺序 (messages, ok)"
    ),
    "save_as": (
        "ansys/aedt/core/application/design.py:4553 "
        "save_project(file_name, overwrite=True, ...) -> bool——带 file_name "
        "走 oproject.SaveAs(str(file_name), overwrite)，父目录自动创建"
    ),
    "desktop_save_as": (
        "ansys/aedt/core/desktop.py:1912 "
        "save_project(project_name, project_path) -> bool——带 project_path "
        "走 oproject.SaveAs（无活动 app 句柄时的工程级 SaveAs 通路）"
    ),
    "open_project": (
        "ansys/aedt/core/desktop.py:2083 load_project(project_file, "
        "design_name=None) -> bool | object——odesktop.OpenProject；.lock "
        "存在抛 RuntimeError('Project is locked...')；有活动设计返回 app "
        "（get_pyaedt_app），无活动设计返回 True"
    ),
    "heal_objects": (
        "ansys/aedt/core/modeler/cad/primitives.py:7033 "
        "heal_objects(assignment, auto_heal=True, ...) -> bool——HFSS 3D "
        "GeometryModeler 封装（assignment=对象名串，校验存在于 object_names）"
    ),
    "modeler_check": (
        "pyaedt 1.9.0 无 HFSS 3D Modeler 菜单级 Check 封装——仅 HFSS 3D "
        "Layout 有 oeditor.GeometryCheckAndAutofix（modeler/modeler_pcb.py:"
        "1459）；设计级验证由 validate_full_design→oDesign.ValidateDesign"
        "（application/design.py:4713 validate_simple）覆盖"
    ),
    "checklist_accessors": (
        "materials=application/analysis.py:260 app.materials + "
        "modules/material_lib.py:78 material_keys；"
        "boundaries=application/design.py:453 app.boundaries；"
        "mesh=modules/mesh.py:527 app.mesh.meshoperations；"
        "setups=application/analysis.py:287 app.setups；"
        "optimetrics=application/analysis.py:310 app.parametrics.setups + "
        ":330 app.optimizations.setups"
    ),
    "desktop_messages": (
        "ansys/aedt/core/desktop.py:3467 odesktop.GetMessages(project, "
        "design, severity)——severity 0/1/2=info/warning/error 分档收集"
    ),
    "grpc_error": (
        "ansys/aedt/core/internal/errors.py:28 class GrpcApiError("
        "RuntimeError)——cutoff 报错经 OpenProject 异常消息表面化，"
        "按 CUTOFF_NEEDLES 文本判定（引擎不提供结构化错误码）"
    ),
}

#: Modeler Check 独立脚本段模板（**UNVERIFIED-API，禁执行**）。
#:
#: 接地结论（2026-11-10 pyaedt 1.9.0 实读）：HFSS 3D Modeler 菜单级
#: "Check" 的独立 oEditor 命令名**未在 pyaedt 1.9 出现**，本席不臆造
#: 命令名（#215 铁律）。模板只承载已证实的骨架（QuitApplication 置
#: finally、#374④ 家法；工程路径常量 ASCII 烘焙），菜单级 Check 命令行
#: 留 TODO 占位——真机窗口用 AEDT journal 记录该菜单动作的真实命令后
#: 回填、实测、再把 :data:`_MODEL_CHECK_VERIFIED` 翻 True。
_MODEL_CHECK_VERIFIED = False

_MODEL_CHECK_SCRIPT_TEMPLATE = """\
# aedt_migrate Modeler Check 脚本段（UNVERIFIED-API——模板未验证，禁执行）
# 用途：迁移体检的 Modeler 菜单级 Check（几何检查）自动化段。
# 现状：HFSS 3D Modeler 菜单级 Check 的 oEditor 命令名未经真机 journal
# 取证（pyaedt 1.9 无封装）——TODO(UNVERIFIED-API) 处回填前不得启用。
# IronPython 2 口径：纯 ASCII、无 f-string、不读 argv/env。
import clr  # noqa: F401  (IronPython)
import sys

PROJECT_PATH = r"{project_path}"  # ASCII 烘焙（中文路径坑）
DESIGN_NAME = "{design_name}"


def _quit(oDesktop):
    # #374④/#265 家法：批处理脚本退出必须 QuitApplication，否则孤儿桌面。
    try:
        oDesktop.QuitApplication()
    except Exception:
        pass


def main():
    oAnsys = sys.modules.get("__main__")
    oDesktop = oAnsys.GetAppDesktop() if hasattr(oAnsys, "GetAppDesktop") \\
        else oAnsys.GetAppletDesktop("")
    try:
        oProject = oDesktop.OpenProject(PROJECT_PATH)
        oDesign = oProject.SetActiveDesign(DESIGN_NAME)
        # 设计级验证（已证实通路，pyaedt validate_simple 同款）：
        oDesign.ValidateDesign()
        # TODO(UNVERIFIED-API): 菜单级 Modeler Check 命令名待真机 journal
        # 取证回填（形如 oEditor.<CommandName>(...)）。回填前此脚本段
        # 不得启用（hfss_migrate._MODEL_CHECK_VERIFIED=False 守卫）。
        pass
    except Exception:
        _quit(oDesktop)
        raise
    _quit(oDesktop)


main()
"""


def is_cutoff_message(text: str) -> bool:
    """判定报错文本是否为版本 cutoff 硬拒形态。

    判据：:data:`CUTOFF_NEEDLES` 全部针（AND）命中——大小写无关、
    空白折叠（换行/多空格归一）。两针齐中才 True，单针命中（如锁定类
    "can no longer be opened because it is locked"）不算 cutoff。
    """
    if not text:
        return False
    normalized = re.sub(r"\s+", " ", str(text)).strip().lower()
    return all(needle in normalized for needle in CUTOFF_NEEDLES)


def _project_stem(project_path: str | Path) -> str:
    return Path(project_path).stem


def _normcase(path: str | Path) -> str:
    return os.path.normcase(str(path))


def stage_ascii_copy(
    project_path: str | Path,
    *,
    stage_root: str | Path | None = None,
) -> dict[str, Any]:
    """把原件拷贝到 ASCII staging 目录（原件只读铁律的落地面）。

    - staging 根缺省 ``%TEMP%/rfauto_aedt_migrate_stage/<stem>_<摘要8>``；
      根路径自身含非 ASCII → ValueError（P5 fail-closed：AEDT 打开
      非 ASCII 目录直接 gRPC 失败且无路径提示，staging 必须真 ASCII）。
    - 只拷 ``.aedt`` 本体（结果目录不拷——迁移体检与 SaveAs 不需要）。
    - 原件零改动（shutil.copy2 只读源）。

    Returns
    -------
    dict[str, Any]
        ``staged_path``（拷贝件全路径）/ ``stage_dir`` / ``errors``。
    """
    src = Path(project_path)
    stem = _project_stem(src)
    if stage_root is None:
        # sha1 摘要（hfss_session.ascii_workdir_path 同款）：同一原工程跨
        # 会话/跨进程落同一 staging 目录（hash() 进程随机化不可用——幂等
        # 重跑复用语义）。同一工程串行复用（service 编排逐工程独占）。
        digest = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:8]
        root = Path(tempfile.gettempdir()) / "rfauto_aedt_migrate_stage" / f"{stem}_{digest}"
    else:
        root = Path(stage_root)
    if has_non_ascii(root):
        raise ValueError(
            f"staging 根路径含非 ASCII 字符: {root}——AEDT 打开非 ASCII 目录"
            "直接 gRPC 失败且报错无路径提示（晶圆键合 §2.2）。请把 TEMP 环境变量"
            "或 stage_root 指向纯 ASCII 目录后重试。"
        )
    root.mkdir(parents=True, exist_ok=True)
    staged = root / src.name
    shutil.copy2(src, staged)
    return {"staged_path": str(staged), "stage_dir": str(root), "errors": []}


def open_legacy_project(
    project_path: str | Path,
    *,
    design: str | None = None,
    session: Any | None = None,
    settings: dict[str, Any] | None = None,
    stage: bool = True,
    stage_root: str | Path | None = None,
) -> dict[str, Any]:
    """Stage 1 直开尝试（2025 R1 非图形会话，原件只读）。

    打开通路=``session.desktop.load_project(path)``（pyaedt 1.9
    ``desktop.py:2083``，odesktop.OpenProject；.lock 在场抛
    RuntimeError）——**有活动设计返回 app、无活动设计返回 True**，
    两种返回都算"打开成功"（后者 app=None、体检如实记
    ``no_active_design``，绝不构造 Hfss 空设计——``Hfss(project=..)`` 对
    空工程会**创建**新设计，违反迁移只读语义）。

    Parameters
    ----------
    project_path : str | Path
        原件路径（只读；永不写入/保存）。
    design : str | None
        目标设计名（None=活动设计）。
    session : Any | None
        会话句柄（duck-typed：``connect(settings)``/``close(save=)``/
        ``desktop``/``desktop_pid``）。None=:class:`HfssSession` 单例；
        注入会话由调用方管生命周期（本函数不代关）。
    settings : dict | None
        ``HfssSession.connect`` 配置（缺省版本
        :data:`MIGRATE_VERSION_DEFAULT`，``non_graphical=True``）。会话
        已连接时幂等跳过（hfss_session 语义），settings 不再生效。
    stage : bool
        True（缺省）=先拷 ASCII staging 再开拷贝件（原件旁零写入，
        规避 AEDT 版本迁移自动备份落原件旁）；False=直开原件
        （**原件路径必须 ASCII**，否则 ValueError）。
    stage_root : str | Path | None
        自定义 staging 根（缺省 %TEMP% 下）。

    Returns
    -------
    dict[str, Any]
        具名结构（janitor lock_owner_verdict 同款普通 dict 惯例）：

        - ``stage``: 常量 ``"open"``；
        - ``ok``: 打开成功（opened/cutoff 判定无关 save）；
        - ``outcome``: :data:`OUTCOME_OPENED` 等五枚举之一；
        - ``cutoff``: True ⇔ 版本 cutoff 硬拒（→蓝图 Stage 4）；
        - ``project_path`` / ``open_path``（实际打开路径=staging 拷贝
          件或原件）/ ``staged`` / ``stage_dir``（staged=False 时 None）；
        - ``designs``（打开后设计名清单）/ ``design``（绑定设计，可为
          None）/ ``app``（活句柄——打开成功时会话**留场**，调用方用完
          必 :func:`close_migrate_session` 收尾；失败且会话为本函数自建
          时已就地关；no_active_design 时 None）；
        - ``no_active_design``: 工程无活动设计（app=None 的原因）；
        - ``messages``: 失败/异常原文清单（cutoff/open_failed 判读第一
          现场，含 best-effort 桌面消息）；
        - ``occupancy``: 原件占用检测报告（detect_project_occupancy）；
        - ``engine``: ``{"version", "desktop_pid"}``（AX-3 engine
          identity 段原料，随迁移报告落盘）；
        - ``session_owned``: 本函数是否自建会话（True=已随之关闭）；
        - ``errors``。
    """
    src = Path(project_path)
    if not src.is_file():
        raise ValueError(f"待迁移工程不存在或不是文件: {src}")
    if src.suffix.lower() != ".aedt":
        raise ValueError(
            f"待迁移工程扩展名必须是 .aedt（本通道一期只收 .aedt，"
            f".aedtz 归档待后续）: {src}"
        )

    injected = session is not None
    sess = session if session is not None else HfssSession.instance()
    session_owned = not injected and not sess.is_connected

    # 占用检测先行（晶圆键合 §2.3；detect_project_occupancy 观测面
    # best-effort 契约不抛）——license 消耗与 staging 拷贝开销之前
    # fail-fast；占用只记账不代清场（清场面=resource_janitor 单源）。
    occupancy = detect_project_occupancy(src)

    # 契约守卫在 try **之外**（ValueError 原样上抛，不折算 open_failed）。
    open_path = src
    if occupancy.get("occupied") is True:
        staged_flag, stage_dir = False, None
    elif stage:
        # staging（原件只读铁律）：拷 ASCII 目录开拷贝件（原件旁零写入，
        # 规避 AEDT 版本迁移自动备份落原件旁——蓝图 §0-1 直开行为）。
        staged_info = stage_ascii_copy(src, stage_root=stage_root)
        open_path = Path(staged_info["staged_path"])
        staged_flag, stage_dir = True, str(open_path.parent)
    elif has_non_ascii(src):
        raise ValueError(
            f"原件路径含非 ASCII 字符且 stage=False: {src}——AEDT 打开"
            "非 ASCII 工程路径直接 gRPC 失败且报错无提示（晶圆键合 "
            "§2.2）。请用缺省 stage=True（ASCII staging 拷贝件直开）。"
        )
    else:
        staged_flag, stage_dir = False, None

    result: dict[str, Any] = {
        "stage": "open",
        "ok": False,
        "outcome": OUTCOME_OPEN_FAILED,
        "cutoff": False,
        "project_path": str(src),
        "open_path": str(open_path),
        "staged": staged_flag,
        "stage_dir": stage_dir,
        "designs": [],
        "design": design,
        "app": None,
        "no_active_design": False,
        "messages": [],
        "occupancy": occupancy,
        "engine": {"version": None, "desktop_pid": None},
        "session_owned": session_owned,
        "errors": [],
    }
    settings = dict(settings or {})
    settings.setdefault("desktop_version", MIGRATE_VERSION_DEFAULT)
    settings.setdefault("non_graphical", True)
    result["engine"]["version"] = settings["desktop_version"]

    if occupancy.get("occupied") is True:
        result["outcome"] = OUTCOME_LOCKED
        result["messages"].append(
            str(occupancy.get("reason") or "project occupied"))
        result["errors"].append(
            f"原件被 GUI/会话占用，拒绝直开: {src}（{occupancy.get('reason')}）。"
            "请先关闭占用会话或经 resource_janitor 清场（核对命令行后只杀"
            "目标 PID）。"
        )
        return result
    if occupancy.get("occupied") is None:
        logger.warning(
            "原件占用不可判定（fail-unknown，放行继续）: %s —— %s",
            src, occupancy.get("reason"),
        )

    opened = False
    try:
        if not sess.is_connected:
            sess.connect(settings)
        result["engine"]["desktop_pid"] = getattr(sess, "desktop_pid", None)

        desktop = sess.desktop
        if desktop is None:
            raise RuntimeError(
                "会话 desktop 不可用（connect 未成功或注入会话缺 desktop）")
        _open = desktop.load_project(str(open_path), design)
        if isinstance(_open, bool) and not _open:
            # load_project False=OpenProject 失败且未抛（pyaedt 返回面）。
            msgs = _collect_desktop_messages(desktop, _project_stem(open_path), None)
            result["messages"].extend(msgs or ["load_project 返回 False（无异常）"])
            result["outcome"] = OUTCOME_OPEN_FAILED
            result["errors"].append(
                f"load_project 返回 False: {open_path}——OpenProject 失败"
                "（桌面消息随 messages）")
            return result

        opened = True
        project_name = _project_stem(open_path)
        if isinstance(_open, bool):
            # 无活动设计：如实记账，不构造 app（Hfss() 会给空工程创建
            # 新设计=迁移写面违规）。设计清单仍枚举。
            result["no_active_design"] = True
            result["designs"] = _list_designs(desktop, project_name)
        else:
            app = _open
            result["app"] = app
            result["design"] = getattr(app, "design_name", None) or design
            result["designs"] = _list_designs(
                desktop,
                getattr(app, "project_name", None) or project_name,
            )
        result["outcome"] = OUTCOME_OPENED
        result["ok"] = True
        return result
    except Exception as exc:
        message = str(exc)
        result["messages"].append(message)
        if is_cutoff_message(message):
            result["cutoff"] = True
            result["outcome"] = OUTCOME_CUTOFF
            result["errors"].append(
                f"版本 cutoff 硬拒（蓝图 Stage 4 桥接入口）: {message}")
        elif not opened:
            result["outcome"] = OUTCOME_OPEN_FAILED
            result["errors"].append(f"直开失败: {message}")
        else:
            # 打开成功后的异常（枚举设计名等）不掩盖 opened 事实。
            result["outcome"] = OUTCOME_OPENED
            result["ok"] = True
            result["errors"].append(f"打开成功但后续枚举异常: {message}")
        # 失败现场补收桌面消息（best-effort，#105）。
        try:
            desktop = sess.desktop
            if desktop is not None:
                result["messages"].extend(
                    _collect_desktop_messages(
                        desktop, _project_stem(open_path), None))
        except Exception:
            pass
        return result
    finally:
        # 会话生命周期（#265 铁律）：注入/已连接会话调用方 owns（绝不
        # 代关）；自建会话**失败/占用路径就地关**（无活句柄可交，不得
        # 留孤儿桌面）；自建会话**打开成功留场**——app 是活句柄，调用
        # 方用完必 :func:`close_migrate_session` 收尾（wrapper 入口在
        # finally 必关）。save=False 禁隐式保存。
        if session_owned and not opened:
            close_migrate_session(sess)


def save_as_migrated(
    app: Any | None,
    migrated_dir: str | Path,
    *,
    original_path: str | Path | None = None,
    project_name: str | None = None,
    desktop: Any | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Stage 1 显式 SaveAs 到 migrated/ 新目录（ng 模式无 GUI 提示，
    另存必须脚本显式做——蓝图 §1 Stage 1 原文）。

    通路（接地 pyaedt 1.9.0）：app 句柄在场 →
    ``app.save_project(str(migrated_file))``（``application/design.py:
    4553``，带 file_name 走 ``oproject.SaveAs(file, overwrite)``，父目录
    自动创建）；app=None → ``desktop.save_project(project_name,
    project_path=...)``（``desktop.py:1912``，no_active_design 工程）。

    Parameters
    ----------
    app : Any | None
        活动设计 app 句柄（open_legacy_project 产出）；None 时须给
        desktop+project_name 或 original_path。
    migrated_dir : str | Path
        新目录（本通道一切写面的家）；路径含非 ASCII → ValueError
        （SaveAs 对 CJK 目标同族失败，fail-closed）；目录不存在自动建。
    original_path : str | Path | None
        原件路径（stem 推导 + "SaveAs 目标≠原件"守卫）。
    project_name : str | None
        工程 stem（app 缺席时从 original_path 推导）。
    desktop : Any | None
        Desktop 句柄（app=None 通路）。
    overwrite : bool
        目标已存在时是否覆写（缺省 False=拒绝，幂等重跑由 service
        跳过已迁移工程——蓝图 Stage 0/1 幂等语义）。

    Returns
    -------
    dict[str, Any]
        ``ok`` / ``migrated_path`` / ``errors``。守卫拒绝时 ok=False 且
        errors 带原因（不 raise；save 失败不推翻 open 事实——service
        映射裁决）。
    """
    mdir = Path(migrated_dir)
    if has_non_ascii(mdir):
        raise ValueError(
            f"migrated 目录含非 ASCII 字符: {mdir}——SaveAs 对 CJK 目标"
            "同族失败（晶圆键合 §2.2 家族）。migrated/ 是本通道自管输出"
            "目录，请改用纯 ASCII 路径。")
    stem = project_name or (
        _project_stem(original_path) if original_path is not None else None)
    if not stem:
        stem = getattr(app, "project_name", None) or "migrated_project"
    mdir.mkdir(parents=True, exist_ok=True)
    migrated_file = mdir / f"{stem}.aedt"

    errors: list[str] = []
    if original_path is not None and _normcase(migrated_file) == _normcase(original_path):
        return {
            "ok": False,
            "migrated_path": str(migrated_file),
            "errors": [
                f"SaveAs 目标与原件同路径，拒绝（原件只读铁律）: {migrated_file}"
            ],
        }
    if migrated_file.exists() and not overwrite:
        return {
            "ok": False,
            "migrated_path": str(migrated_file),
            "errors": [
                f"migrated 目标已存在且 overwrite=False（幂等重跑应由 "
                f"service 按 inventory 跳过）: {migrated_file}"
            ],
        }
    try:
        if app is not None:
            app.save_project(str(migrated_file))
        elif desktop is not None:
            desktop.save_project(project_name=stem, project_path=str(migrated_file))
        else:
            return {
                "ok": False,
                "migrated_path": str(migrated_file),
                "errors": ["app 与 desktop 均不可用——无 SaveAs 通路"],
            }
    except Exception as exc:
        errors.append(f"SaveAs 失败: {exc}")
        return {"ok": False, "migrated_path": str(migrated_file), "errors": errors}
    if not migrated_file.is_file():
        errors.append(
            f"SaveAs 调用无异常但目标未落盘（pyaedt save_project 返回面 "
            f"恒 True，desktop.py:1912——以文件在盘为准）: {migrated_file}")
        return {"ok": False, "migrated_path": str(migrated_file), "errors": errors}
    return {"ok": True, "migrated_path": str(migrated_file), "errors": errors}


def _list_designs(desktop: Any, project_name: str) -> list[str]:
    """枚举已打开工程的设计名（best-effort，#105：失败返回空表不抛）。"""
    for arg in (project_name, None):
        try:
            names = desktop.design_list(arg)
        except Exception:
            continue
        if names:
            return [str(n) for n in names]
    return [project_name] if project_name else []


def _collect_desktop_messages(
    desktop: Any,
    project_name: str | None,
    design_name: str | None,
) -> list[str]:
    """消息管理器全量收集（severity 0/1/2 分档，best-effort #105）。

    接地：``desktop.py:3467`` odesktop.GetMessages(project, design,
    severity)。pyaedt ``validate_full_design`` 内嵌的是 severity=0 一档；
    本函数补齐三档全量（体检报告的消息面）。
    """
    odesktop = getattr(desktop, "odesktop", desktop)
    collected: list[str] = []
    for severity in (0, 1, 2):
        try:
            msgs = odesktop.GetMessages(project_name or "", design_name or "", severity)
        except Exception:
            continue
        for msg in msgs or []:
            text = str(msg).strip()
            if text and text not in collected:
                collected.append(text)
    return collected


def _checklist_entry(app: Any, item: str) -> dict[str, Any]:
    """六项检查清单单项查询（接地访问器见 PYAEDT_API_GROUNDING）。

    任何查询异常=available False + error 原文入账（不凑绿不抛）。
    """
    entry: dict[str, Any] = {
        "item": item,
        "available": False,
        "count": None,
        "error": None,
    }
    try:
        if item == "materials":
            entry["count"] = len(app.materials.material_keys)
        elif item == "boundaries":
            entry["count"] = len(app.boundaries)
        elif item == "mesh_operations":
            entry["count"] = len(app.mesh.meshoperations)
        elif item == "setups":
            entry["count"] = len(app.setups)
        elif item == "optimetrics_parametric":
            entry["count"] = len(app.parametrics.setups)
        elif item == "optimetrics_optimization":
            entry["count"] = len(app.optimizations.setups)
        else:  # pragma: no cover  （CHECKLIST_ITEMS 与本分派同步约束）
            entry["error"] = f"未知检查项: {item}"
            return entry
        entry["available"] = True
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"
    return entry


def run_health_check(
    app: Any,
    *,
    desktop: Any | None = None,
    heal: bool = False,
    heal_assignment: str | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Stage 2 迁移体检（2025 R1 会话内，观察优先、heal 显式 opt-in）。

    - ``validate_full_design()`` 解包 **(messages, ok)**（晶圆键合
      §2.4，pyaedt 1.9 ``hfss.py:4770`` 签名实证）——本模块唯一解包点。
    - 消息管理器全量收集（desktop 在场时 severity 0/1/2 三档）。
    - :data:`CHECKLIST_ITEMS` 六项存在性核对（计数+异常入账）。
    - heal（``heal_objects``，primitives.py:7033）缺省 **False**——
      heal 会改几何，迁移体检先观察；启用时 assignment 缺省
      ``app.modeler.object_names`` 全体（逗号串，heal_objects 校验
      在场）。
    - Modeler 菜单级 Check：pyaedt 1.9 无 HFSS 3D 封装——以
      validate_full_design（oDesign.ValidateDesign）为准；独立脚本段
      模板见 :data:`_MODEL_CHECK_SCRIPT_TEMPLATE`（UNVERIFIED-API）。

    Returns
    -------
    dict[str, Any]
        ``stage="health"`` / ``ok`` / ``outcome``（``pass`` |
        ``validate_failed``）/ ``geometry_hint``（启发式路由提示）/
        ``validate``（messages+ok）/ ``desktop_messages`` /
        ``checklist``（六项）/ ``heal`` / ``model_check``（覆盖判定
        元数据）/ ``errors``。
    """
    errors: list[str] = []
    validate_messages: list[str] = []
    validate_ok: bool | None = None
    try:
        if output_dir is not None:
            validate_messages, validate_ok = app.validate_full_design(
                output_dir=str(output_dir))
        else:
            validate_messages, validate_ok = app.validate_full_design()
    except Exception as exc:
        errors.append(f"validate_full_design 异常: {exc}")
        validate_ok = None
    # 归一：pyaedt 版本漂移保护（list|tuple 之外形态如实入账）。
    if validate_messages is None:
        validate_messages = []

    desktop_messages: list[str] = []
    if desktop is not None:
        try:
            desktop_messages = _collect_desktop_messages(
                desktop,
                getattr(app, "project_name", None),
                getattr(app, "design_name", None),
            )
        except Exception as exc:
            errors.append(f"桌面消息收集异常: {exc}")

    checklist = [_checklist_entry(app, item) for item in CHECKLIST_ITEMS]
    checklist_errors = [e for e in checklist if e["error"]]

    heal_result: dict[str, Any] | None = None
    if heal:
        heal_result = {"ran": False, "ok": False, "assignment": None, "errors": []}
        try:
            assignment = heal_assignment or ",".join(
                str(n) for n in app.modeler.object_names)
            heal_result["assignment"] = assignment
            heal_result["ok"] = bool(app.modeler.heal_objects(assignment=assignment))
            heal_result["ran"] = True
            if not heal_result["ok"]:
                heal_result["errors"].append("heal_objects 返回 False")
        except Exception as exc:
            heal_result["errors"].append(f"heal_objects 异常: {exc}")

    lower_msgs = " ".join(
        [*(m or "" for m in validate_messages), *desktop_messages]
    ).lower()
    geometry_hint = any(m in lower_msgs for m in GEOMETRY_HINT_MARKERS)

    outcome = "pass" if validate_ok is True else "validate_failed"

    ok = (
        validate_ok is True
        and not checklist_errors
        and not errors
        and (heal_result is None or (heal_result.get("ran") and heal_result.get("ok")))
    )
    return {
        "stage": "health",
        "ok": ok,
        "outcome": outcome,
        "geometry_hint": geometry_hint,
        "validate": {"messages": list(validate_messages), "ok": validate_ok},
        "desktop_messages": desktop_messages,
        "checklist": checklist,
        "heal": heal_result,
        "model_check": {
            "covered_by": "validate_full_design (oDesign.ValidateDesign)",
            "heal_api": (
                "pyaedt 1.9 heal_objects (modeler/cad/primitives.py:7033)"
                if heal else
                "pyaedt 1.9 heal_objects 可用（本次未启用，heal=False）"
            ),
            "script_template_verified": _MODEL_CHECK_VERIFIED,
        },
        "errors": errors,
    }


def close_migrate_session(session: Any | None = None) -> None:
    """关迁移会话（#265 铁律落点）：``close(save=False)``——迁移链已
    显式 SaveAs，禁再触发任何隐式保存（原件只读铁律）。"""
    sess = session if session is not None else HfssSession.instance()
    try:
        sess.close(save=False)
    except Exception as exc:
        logger.warning("迁移会话关闭异常（#265 兜底已尽力）: %s", exc)


def migrate_open_save_and_check(
    project_path: str | Path,
    migrated_dir: str | Path,
    *,
    design: str | None = None,
    settings: dict[str, Any] | None = None,
    stage: bool = True,
    stage_root: str | Path | None = None,
    overwrite: bool = False,
    heal: bool = False,
    session: Any | None = None,
) -> dict[str, Any]:
    """Stage 1+2 一次到位（推荐 executor 入口）：直开 → 体检 → 显式
    SaveAs → finally 关会话（#265）→ staging 清理（best-effort）。

    执行序：占用检测（license 前）→ staging 拷贝 → connect →
    ``load_project`` → 体检（app 在场才跑；heal 在 SaveAs **前**，
    迁移件落 heal 后形态）→ SaveAs → ``close(save=False)``。会话失败
    /体检失败都不吞——一切在结果 dict 里如实入账。

    Returns
    -------
    dict[str, Any]
        ``stage="direct_open+health"``；``outcome`` 同 Stage 1 五枚举
        （体检失败**不**改 outcome——体检事实在 ``health`` 键，service
        映射 FAILED(health)/Stage 5）；``ok = open_ok and save_ok and
        health_ok``；其余键：``cutoff`` / ``open``（Stage 1 子报告）/
        ``health``（Stage 2 子报告，app 缺席时 None）/
        ``migrated_path`` / ``engine`` / ``session_owned`` /
        ``stage_dir`` / ``stage_cleaned`` / ``errors``。
    """
    src = Path(project_path)
    injected = session is not None
    sess = session if session is not None else HfssSession.instance()
    session_owned = not injected and not sess.is_connected

    result: dict[str, Any] = {
        "stage": "direct_open+health",
        "ok": False,
        "outcome": OUTCOME_OPEN_FAILED,
        "cutoff": False,
        "open": None,
        "health": None,
        "migrated_path": None,
        "engine": {"version": None, "desktop_pid": None},
        "session_owned": session_owned,
        "stage_dir": None,
        "stage_cleaned": None,
        "errors": [],
    }
    try:
        open_report = open_legacy_project(
            src,
            design=design,
            session=sess,
            settings=settings,
            stage=stage,
            stage_root=stage_root,
        )
        result["open"] = open_report
        result["outcome"] = open_report["outcome"]
        result["cutoff"] = open_report["cutoff"]
        result["engine"]["version"] = open_report["engine"]["version"]
        result["engine"]["desktop_pid"] = open_report["engine"]["desktop_pid"]
        result["stage_dir"] = open_report["stage_dir"]
        result["errors"].extend(open_report["errors"])
        if not open_report["ok"]:
            # 打开失败/占用：无体检无 SaveAs（save_as_migrated 的
            # "无通路"记账只对"打开了但没句柄"形态有意义，此处跳过）。
            return result

        app = open_report["app"]
        if app is not None:
            desktop = sess.desktop if sess.is_connected else None
            result["health"] = run_health_check(
                app,
                desktop=desktop,
                heal=heal,
            )

        # SaveAs（体检后：heal 场景迁移件落 heal 后形态；validate 不改
        # 工程，序无影响）。no_active_design 工程 app=None——desktop
        # 通路 SaveAs（open 会话在场才有 desktop）。
        save = save_as_migrated(
            app,
            migrated_dir,
            original_path=src,
            desktop=sess.desktop if sess.is_connected else None,
            overwrite=overwrite,
        )
        result["migrated_path"] = save["migrated_path"]
        result["errors"].extend(save["errors"])
        if not save["ok"]:
            result["outcome"] = OUTCOME_SAVE_FAILED

        open_ok = bool(open_report["ok"])
        save_ok = bool(save["ok"])
        health = result["health"]
        health_ok = bool(health and health.get("ok")) if health else (app is None)
        # app 缺席（no_active_design）：体检无对象——health_ok 按 True
        # 记（体检面无事可做，open/save 事实承担 ok），health=None 如实。
        result["ok"] = open_ok and save_ok and health_ok
        return result
    except ValueError:
        # 契约类错误（路径不存在/非 ASCII）原样上抛——service 显式处理。
        raise
    except Exception as exc:
        result["errors"].append(f"executor 未预期异常: {exc!r}")
        result["ok"] = False
        return result
    finally:
        if session_owned:
            close_migrate_session(sess)
        # staging 目录清理（best-effort，任务毕清理纪律）：staging 只有
        # 原件拷贝（无产物价值——产物在 migrated/），删；失败只记账。
        stage_dir = result.get("stage_dir")
        if stage_dir:
            try:
                shutil.rmtree(stage_dir, ignore_errors=True)
                result["stage_cleaned"] = True
            except Exception as exc:
                result["stage_cleaned"] = False
                result["errors"].append(f"staging 清理失败（留人工兜底）: {exc}")


def run_modeler_check_script(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Modeler 菜单级 Check 独立脚本段入口——**未验证，禁执行**。

    pyaedt 1.9 无 HFSS 3D Modeler Check 封装且命令名未经真机 journal
    取证（#215 禁凭想象）——模板常量
    :data:`_MODEL_CHECK_SCRIPT_TEMPLATE` 留真机窗口回填+实测后，把
    :data:`_MODEL_CHECK_VERIFIED` 翻 True 才可启用。此前调用一律
    NotImplementedError（体检主通路 validate_full_design 不受影响）。
    """
    raise NotImplementedError(
        "Modeler Check 独立脚本段 UNVERIFIED-API：pyaedt 1.9 无 HFSS 3D "
        "封装、命令名待真机 journal 取证（hfss_migrate._MODEL_CHECK_"
        "SCRIPT_TEMPLATE 模板已就位）——真机验证回填后启用；当前体检以 "
        "validate_full_design(oDesign.ValidateDesign) 为准。"
    )

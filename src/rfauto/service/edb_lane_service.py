"""EDB 快车道服务编排（CLI/MCP 出口层，2026-10-08）。

把既有三件能力编排成 JSON 进出的 service 函数（规则 4：service 先行，
CLI/MCP 薄壳）——本模块**纯编排零物理数值**（铁律 7）：

- 发射：``adapters/edb_templates`` 发射器（branchline/power_divider/
  coupled_line/ratrace 四族，尺寸全部由 core.synthesis 闭式综合产出——
  数值只在确定性内核；lange 声明不支持，见 ``_emit_spec_checked``）；
- 建库：``adapters/edb_adapter.EdbAdapter.build``（spec → pyedb
  configuration → .aedb 工程）；
- 批解：``EdbAdapter.solve_batch`` → ``adapters/hfss_batch``（ansysedt
  ``-BatchSolve`` 短命批进程）+ 批后 ``export_touchstone_after_solve``
  （``-batchextract`` 第二段进程导 Touchstone，hfss_batch 模块 docstring
  判读断链补口口径）。

信封契约（service/envelope 三态）：成功 ``ok_envelope``；发射器/适配器
的 ValueError/RuntimeError/EdbSpecError 等程序性失败归一 ``error_envelope``
（errors 恒 list[str]，不向 CLI/MCP 抛裸异常炸会话）。pyedb/ansysedt
真机依赖全在 adapters 层惰性导入——本模块可离线导入，测试全 fake。

本模块**不定义 __all__**（同 edb_adapter 口径：公开 API 快照只登记带
__all__ 的模块，新模块出生不触发 public_api 金快照重钉动作）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

# 注意：本模块不定义 __all__（公开 API 快照口径，见模块 docstring）。

#: 批后导出 Touchstone 命名形态（``<stem>_export.s<N>p``）。W5 审查修正
#: （2026-10-08）：hfss_batch 导出链按文件内容反推端口数后**改名 .sNp**
#: （.s2p 只是 2 端口占位——4 端口真机产物实为 ``*_export.s4p``，
#: runs/edblane85/w5_batch_campaign/ 五件实证），status 面原只认 ``.s2p``
#: 恒 miss 真实产物；大小写不敏感，stem 捕获组含 ``.aedb`` 工程名形态。
_EXPORT_TOUCHSTONE_RE = re.compile(r"^(.+)_export\.s\d+p$", re.IGNORECASE)

#: Lange（edb_lange 预留键）EDB 发射"声明不支持"的拒绝原因单源（与
#: adapters/edb_templates/lange.py docstring 裁定同口径；升格随
#: LANGE_EDB_SUPPORTED 翻转时拆除相关分支并分派表入册）。
_LANGE_UNSUPPORTED_REASON = (
    "Lange 耦合器 EDB 发射声明不支持（LANGE_EDB_SUPPORTED=False）："
    "pyedb 0.83 configuration 无跨线（crossover/air-bridge）原语，同层"
    "跨越=金属合并短路，单层 U 形跳线受网络 A(指1/3)/B(指2/4) 端部交错"
    "连线的平面性障碍不可行，第二层埋线+过孔跳线近似未经真机仲裁；"
    "综合数值需求走 edb_templates.lange_synth()。"
)

#: Lange 升格前置条件文档（与 lange.py docstring「升格前置条件」互指；
#: docs/templates/edb_lange/meta.yaml 是该族信息元面，非注册表成员）
_LANGE_UPGRADE_DOC = "docs/templates/edb_lange/meta.yaml"


class _TemplateUnsupported(ValueError):
    """模板声明不支持（能力门，非入参错）——携带结构化信封字段。

    ValueError 子类：沿用既有 ``(ValueError, KeyError, TypeError)`` 捕获
    面之外的独立捕获分支，公共函数按 ``fields`` 展开结构化诊断字段
    （template/supported/reason/upgrade_doc）——"不支持"是契约面而非
    程序性失败，裸 errors 行不够 Agent/调用方定位与分支判断。
    """

    def __init__(self, message: str, fields: dict[str, Any]):
        super().__init__(message)
        self.fields = dict(fields)


def _emitters() -> dict[str, Any]:
    """发射分派表（template 键 → 发射器函数）——``_emit_spec_checked``
    与 ``_template_catalog``（edb_status 五族清单）同源消费，名单不复制
    防漂移。四族发射器同签名 ``(params) -> (spec, config_json)``；惰性
    导入保持本模块轻导入纪律（发射器纯函数，但综合链在 core 层）。"""
    from rfauto.adapters.edb_templates import (
        emit_branchline_spec,
        emit_coupled_line_spec,
        emit_power_divider_spec,
        emit_ratrace_spec,
    )

    return {
        "edb_branchline": emit_branchline_spec,
        "edb_power_divider": emit_power_divider_spec,
        "edb_coupled_line": emit_coupled_line_spec,
        "edb_ratrace": emit_ratrace_spec,
    }


def _lange_unsupported() -> tuple[str, dict[str, Any]]:
    """lange 拒绝信封的 (errors 文案, 结构化字段) 单源。

    Returns:
        (message, fields)：message 进信封 ``errors``（含升格指引）；
        fields=``{template, supported, reason, upgrade_doc}`` 结构化诊断。

    Raises:
        AssertionError: ``LANGE_EDB_SUPPORTED`` 已翻转 True（升格落地）
            而服务层分支未拆——防"已支持仍被假拒绝"的漂移（测试钉此联动）。
    """
    from rfauto.adapters.edb_templates import (
        LANGE_EDB_SUPPORTED,
        TEMPLATE_KEY_RESERVED,
    )

    if LANGE_EDB_SUPPORTED:  # pragma: no cover - 升格时拆分支+分派表入册
        raise AssertionError(
            "edb_templates 已升格 lange EDB 发射（LANGE_EDB_SUPPORTED="
            "True）：请把分派表入册并拆除 _TemplateUnsupported 拒绝分支"
            "（防假拒绝漂移）")
    upgrade = (
        f"升格前置条件见 {_LANGE_UPGRADE_DOC}"
        "（pyedb crossover 原语，或经真机仲裁的过孔跳线口径 + schema 契约"
        "层扩展 KNOWN_TEMPLATES/层叠/vias 消费面）。"
    )
    message = (f"edb 模板 {TEMPLATE_KEY_RESERVED!r}："
               + _LANGE_UNSUPPORTED_REASON + upgrade)
    fields = {
        "template": TEMPLATE_KEY_RESERVED,
        "supported": False,
        "reason": _LANGE_UNSUPPORTED_REASON,
        "upgrade_doc": _LANGE_UPGRADE_DOC,
    }
    return message, fields


def _template_catalog() -> list[dict[str, Any]]:
    """快车道发射族五族清单（edb_status ``templates`` 节单源）。

    支持态随 ``_emitters`` 分派表与 ``LANGE_EDB_SUPPORTED`` 走：四支持族
    ``{template, supported: True}``；lange 声明不支持时附
    ``{reason, upgrade_doc}``（与拒绝信封同源同文案）。
    """
    from rfauto.adapters.edb_templates import (
        LANGE_EDB_SUPPORTED,
        TEMPLATE_KEY_RESERVED,
    )

    rows = [{"template": key, "supported": True}
            for key in sorted(_emitters())]
    if LANGE_EDB_SUPPORTED:  # pragma: no cover - 升格时随分派表入册自然翻转
        rows.append({"template": TEMPLATE_KEY_RESERVED, "supported": True})
    else:
        rows.append({
            "template": TEMPLATE_KEY_RESERVED,
            "supported": False,
            "reason": _LANGE_UNSUPPORTED_REASON,
            "upgrade_doc": _LANGE_UPGRADE_DOC,
        })
    return rows


def _emit_spec_checked(template: str, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """发射器分派 + 适配器契约预校验（纯函数链，零 IO）。

    - template → ``_emitters`` 分派表四族发射器（branchline/
      power_divider/coupled_line/ratrace；名单单源在 adapters 层——
      防漂移）；
    - template=``edb_lange``（adapters 层 ``TEMPLATE_KEY_RESERVED`` 预留
      键）→ 抛 :class:`_TemplateUnsupported`（结构化"声明不支持"，理由与
      升格前置条件指向见 :func:`_lange_unsupported`）；
    - 发射器内部 validate_spec 自检失败抛 ValueError（带病 spec 不出
      发射器）；
    - 再走 ``edb_adapter.spec_to_config_json`` 纯函数过一遍适配器契约
      （第二独立校验面：单位/schema_version/未知键 fail-fast——发射器
      与适配器两侧契约由 tests/unit/test_edb_adapter.py 契约测试钉住，
      此处运行时双检早失败定位浅）。

    Raises:
        _TemplateUnsupported: template 为 lange 预留键（声明不支持，
            ValueError 子类，携带结构化信封字段）。
        ValueError: template 不在分派表 / 发射器综合自检失败 / 适配器
            契约校验失败（EdbSpecError 是 ValueError 子类）。
    """
    from rfauto.adapters.edb_adapter import spec_to_config_json
    from rfauto.adapters.edb_templates import TEMPLATE_KEY_RESERVED

    key = str(template or "")
    if key == TEMPLATE_KEY_RESERVED:
        raise _TemplateUnsupported(*_lange_unsupported())
    emitters = _emitters()
    fn = emitters.get(key)
    if fn is None:
        raise ValueError(
            f"未知 edb template: {template!r}（合法：{sorted(emitters)}；"
            f"{TEMPLATE_KEY_RESERVED} 声明不支持——发射会被拒绝并给出升格"
            "指引信封）")
    spec, config_json = fn(dict(params or {}))
    spec_to_config_json(spec)  # 适配器契约双检（纯函数，结果不重复产出）
    return spec, config_json


def edb_emit_spec(
    template: str,
    params: dict[str, Any] | None = None,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """发射声明式 EDB spec（发射器纯函数编排，零 pyedb 零 AEDT）。

    Args:
        template: 模板键（``edb_branchline`` / ``edb_power_divider`` /
            ``edb_coupled_line`` / ``edb_ratrace``；``edb_lange`` 为预留
            键——声明不支持，返回结构化拒绝信封）。
        params: 设计参数 dict（f0_ghz 必填；z0_ohm 仅 50；stackup/sweep/
            adapt 等见发射器 docstring——尺寸综合全在 core.synthesis
            确定性内核）。
        out_dir: 可选落盘目录；给出时把 spec 写
            ``<out_dir>/<name>_spec.json`` 存证（ensure_ascii=False）。

    Returns:
        成功信封：``{ok, template, spec, config_json, spec_path?}``；
        失败信封：``{ok: False, errors: [str]}``（未知模板/综合自检失败/
        契约校验失败/落盘 IO 错误）；lange 拒绝信封另带结构化诊断字段
        ``{template, supported: False, reason, upgrade_doc}``。
    """
    try:
        spec, config_json = _emit_spec_checked(template, params)
    except _TemplateUnsupported as exc:
        return error_envelope(str(exc), **exc.fields)
    except (ValueError, KeyError, TypeError) as exc:
        return error_envelope(str(exc))
    envelope = ok_envelope(template=str(template), spec=spec,
                           config_json=config_json)
    if out_dir is not None:
        try:
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            stem = str(spec.get("name") or template)
            path = out / f"{stem}_spec.json"
            path.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        except OSError as exc:
            return error_envelope(f"spec 存证落盘失败: {exc}")
        envelope["spec_path"] = str(path)
    return envelope


def edb_build(
    template: str,
    params: dict[str, Any] | None = None,
    workdir: str | Path = "runs/edb_lane",
    name: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """发射 + EDB 建库（``EdbAdapter.build`` → .aedb 工程 + config 存证）。

    Args:
        template: 模板键（同 :func:`edb_emit_spec`；lange 预留键在发射段
            即被拒绝——适配器零触碰）。
        params: 设计参数 dict（同上）。
        workdir: 产物根目录（.aedb 与 *_config.json 落点；缺省
            ``runs/edb_lane``，服务端部署按 AGENTS 规则 0 磁盘纪律显式给）。
        name: 产物文件名主干（缺省=template 键；禁路径分隔符与 ``..``，
            适配器 fail-fast）。
        dry_run: True=只发射+契约双检并回显适配器 config 预览，**零写盘
            零 pyedb**（无 license/缺 pyedb 环境的冒烟与计划态）。

    Returns:
        成功信封：``{ok, template, workdir, aedb_path, config_json_path,
        warnings, dry_run?}``（dry_run 时改带 ``spec``/``config`` 预览，
        无路径键）；失败信封同 :func:`edb_emit_spec`（另含 pyedb 缺装/
        建库 RuntimeError 的文本；lange 拒绝带结构化诊断字段）。
    """
    try:
        spec, _config_json = _emit_spec_checked(template, params)
    except _TemplateUnsupported as exc:
        return error_envelope(str(exc), **exc.fields)
    except (ValueError, KeyError, TypeError) as exc:
        return error_envelope(str(exc))
    if name:
        spec["name"] = str(name)
    else:
        spec.setdefault("name", str(template))
    from rfauto.adapters.edb_adapter import EdbAdapter, spec_to_config_json

    try:
        config = spec_to_config_json(spec)
    except ValueError as exc:
        return error_envelope(str(exc))
    if dry_run:
        return ok_envelope(template=str(template), workdir=str(workdir),
                           dry_run=True, spec=spec, config=config)
    try:
        result = EdbAdapter(Path(workdir)).build(spec)
    except (RuntimeError, ValueError, OSError) as exc:
        return error_envelope(f"EDB 建库失败: {exc}")
    return ok_envelope(
        template=str(template), workdir=str(workdir),
        aedb_path=str(result.aedb_path),
        config_json_path=str(result.config_json_path),
        warnings=[str(w) for w in result.warnings],
    )


def edb_solve(
    project: str | Path,
    timeout_s: float = 3600.0,
    export: bool = True,
    design: str | None = None,
    setup: str | None = None,
) -> dict[str, Any]:
    """批处理求解 + 可选 Touchstone 批后导出（hfss_batch 通道编排）。

    求解走 ``EdbAdapter.solve_batch``（``ansysedt -BatchSolve`` 短命批
    进程）；``export=True`` 时求解成功后追加
    ``hfss_batch.export_touchstone_after_solve``（``-batchextract`` 第二
    段进程——``-BatchSolve`` 只求解不产网络参数，hfss_batch 模块 docstring
    判读断链补口口径）。导出失败**只并告警不推翻求解 ok**（hfss_batch
    solve_project_batch 内嵌导出的同款 #105 best-effort 语义，信封
    ``warnings`` 承载）。

    Args:
        project: ``.aedb`` 目录或 ``.aedt`` 工程路径。
        timeout_s: 每段进程的 watchdog 超时（秒；<=0 不设超时）。
        export: True=求解成功后导 Touchstone（缺省 True——快车道闭环
            主口径；只求解不判读=断链）。
        design/setup: 批后导出段的**脚本内**设计选择（
            ``SetActiveDesign`` 钉定，None=自动枚举）——只透传
            ``export_touchstone_after_solve``；求解段 ``-BatchSolve`` 的
            ``-designs`` 限定经 2026-10-13 真机核实不受 AEDT 2025 R1
            支持（旗标被静默吞、退化全设计求解），hfss_batch 已改
            fail-closed，本函数不向求解段传该参数。

    Returns:
        成功信封：``{ok, project, solve:{ok,rc,timed_out,logfile,
        artifacts,elapsed_s,...}, export:{...}|None, warnings}``；
        失败信封：``{ok: False, errors, solve?}``（路径不存在/通道未
        落地/求解失败/超时）。
    """
    from rfauto.adapters.edb_adapter import EdbAdapter

    project_path = Path(project)  # #140：入参一律先 Path() 收敛
    if not project_path.exists():
        return error_envelope(f"工程路径不存在: {project_path}"
                              "（可接受 .aedb 目录或 .aedt 工程）")
    try:
        adapter = EdbAdapter(project_path.parent)
        solved = adapter.solve_batch(project_path, timeout_s=timeout_s)
    except (RuntimeError, FileNotFoundError, OSError) as exc:
        return error_envelope(f"批处理求解发射失败: {exc}")
    solve_view = {
        "ok": bool(solved.success),
        "rc": solved.rc,
        "timed_out": bool(solved.timed_out),
        "message": str(solved.message or ""),
        "logfile": str(solved.log_path) if solved.log_path else None,
        "artifacts": [str(a) for a in solved.artifacts],
        "elapsed_s": float(solved.elapsed_s),
    }
    warnings: list[str] = []
    export_view: dict[str, Any] | None = None
    if not solved.success:
        return error_envelope(
            (solved.message or "批处理求解失败（详见 solve.logfile 尾部）"),
            solve=solve_view)
    if export:
        try:
            from rfauto.adapters.hfss_batch import export_touchstone_after_solve

            raw = export_touchstone_after_solve(
                project_path, design=design, setup=setup, timeout_s=timeout_s)
        except (RuntimeError, OSError) as exc:
            # #105 best-effort：导出段崩溃不推翻求解 ok，降级为告警
            raw = {"ok": False, "errors": [f"导出段异常: {exc}"]}
        export_view = {
            "ok": bool(raw.get("ok")),
            "out_file": raw.get("out_file"),
            "n_ports": raw.get("n_ports"),
            "rc": raw.get("rc"),
            "timed_out": bool(raw.get("timed_out", False)),
            "logfile": raw.get("logfile"),
            "errors": [str(e) for e in raw.get("errors") or []],
        }
        if not export_view["ok"]:
            warnings.append(
                "Touchstone 批后导出失败（不推翻求解 ok，#105 best-effort）: "
                + "；".join(export_view["errors"] or ["未知原因"]))
    return ok_envelope(project=str(project_path), solve=solve_view,
                       export=export_view, warnings=warnings)


def edb_build_solve(
    template: str,
    params: dict[str, Any] | None = None,
    workdir: str | Path = "runs/edb_lane",
    name: str | None = None,
    dry_run: bool = False,
    solve: bool = False,
    timeout_s: float = 3600.0,
    export: bool = True,
) -> dict[str, Any]:
    """建库 + 可选批解一站式编排（MCP ``edb_build_solve`` 主语义）。

    ``solve=False``（缺省）即 :func:`edb_build` 原样（含 dry_run 计划态）；
    ``solve=True`` 建库成功后接 :func:`edb_solve`（真机 opt-in：要 ansysedt
    在位，缺装/失败进信封 errors 不炸会话）。两段结果同信封承载：
    ``build``/``solve`` 分节，整体 ``ok``=两段各自成立。
    """
    built = edb_build(template, params, workdir=workdir, name=name,
                      dry_run=dry_run)
    if not built.get("ok"):
        return built
    if not solve:
        return built
    aedb_path = built.get("aedb_path")
    if not aedb_path:
        return error_envelope("建库信封缺 aedb_path（契约漂移？）",
                              build=built)
    solved = edb_solve(aedb_path, timeout_s=timeout_s, export=export)
    # built 段失败已在开场短路返回，此处整体 ok 只随 solve 段——
    # 成败各走构造器（W4 审查 P3：不再 ok_envelope(ok=ok) 字段覆盖+
    # 事后手挂 errors 的 dict 解包顺序脆弱形态；键集与旧形态等价：
    # 成功 {ok, template, build, solve}，失败 {ok, errors, template,
    # build, solve}，消费方均按键名读、键序无关）。
    if not solved.get("ok"):
        return error_envelope(
            [str(e) for e in solved.get("errors") or
             ["批解段失败（详见 solve 节）"]],
            template=str(template), build=built, solve=solved)
    return ok_envelope(template=str(template), build=built, solve=solved)


def _strip_aedb(stem: str) -> str:
    """stem 归一：剥 ``.aedb`` 尾缀（hfss_batch 对 .aedb 工程按**工程名**
    （含后缀）派生日志/导出文件名——``ansysedt_batch_x.aedb.log``/
    ``x.aedb_export.s4p``；status 面按裸 stem 归组，不折叠则同工程裂成
    双行幽灵 stem）。"""
    low = stem.lower()
    return stem[:-len(".aedb")] if low.endswith(".aedb") else stem


def _first_existing(*paths: Path) -> Path | None:
    """多候选取首个存在者（.aedb 工程的日志/导出名带 .aedb 尾缀变体）。"""
    for p in paths:
        if p.exists():
            return p
    return None


def edb_status(root: str | Path = "runs/edb_lane") -> dict[str, Any]:
    """扫描产物根目录的快车道资产清单（只读，零求解零导入）。

    清点面（按工程 stem 归组）：``.aedb`` 工程目录、``*_config.json``
    建库存证、``ansysedt_batch_*.log``/``ansysedt_batch_extract_*.log``
    求解/导出日志、``*_export.s<N>p`` 批后 Touchstone（按端口数改名后的
    实际扩展名同认——.s2p 只是 2 端口占位，W5 审查修正）、``*_spec.json``
    发射存证（:func:`edb_emit_spec` out_dir 口径）。.aedb 工程的日志/
    导出产物名带 ``.aedb`` 尾缀（hfss_batch 按工程名派生），一律折叠回
    裸 stem 归组（不折叠则同工程裂成双行）。目录不存在=ok True
    + n_projects=0 如实空表（不臆造）。

    信封另带 ``templates`` 节（:func:`_template_catalog` 五族清单：
    branchline/power_divider/coupled_line/ratrace 四支持族 + lange 声明
    不支持附 reason/upgrade_doc——与发射分派表同源，供 Agent/调用方
    免试错发现能力面）。

    Returns:
        ``{ok, root, n_projects, items:[{stem, aedb, config_json,
        solve_log, extract_log, touchstone, spec_json, solved}],
        templates:[{template, supported, reason?, upgrade_doc?}]}``——
        items 缺项 None。
    """
    root_path = Path(root)  # #140 口径
    if not root_path.is_dir():
        return ok_envelope(root=str(root_path), n_projects=0, items=[],
                           templates=_template_catalog())
    try:
        entries = sorted(root_path.iterdir())
    except OSError as exc:
        return error_envelope(f"产物根目录不可读: {root_path}（{exc}）")

    aedbs = {p.name[:-len(".aedb")]: p for p in entries
             if p.name.endswith(".aedb") and p.is_dir()}
    stems = set(aedbs)
    # 批后导出 Touchstone 注册表：stem（小写，含 .aedb 原始形态）→ 路径
    # （同 stem 多扩展名按名字小写序取首个——确定性；常规每 stem 恰一件）
    export_ts: dict[str, Path] = {}
    for p in entries:
        if not p.is_file():
            continue
        m = _EXPORT_TOUCHSTONE_RE.match(p.name)
        if m is None:
            continue
        key = m.group(1).lower()
        cur = export_ts.get(key)
        if cur is None or p.name.lower() < cur.name.lower():
            export_ts[key] = p
    for p in entries:
        name = p.name
        if name.endswith("_config.json"):
            stems.add(name[:-len("_config.json")])
        elif name.endswith("_spec.json"):
            stems.add(name[:-len("_spec.json")])
        else:
            m = _EXPORT_TOUCHSTONE_RE.match(name)
            if m is not None:
                stems.add(_strip_aedb(m.group(1)))
                continue
            for prefix in ("ansysedt_batch_extract_", "ansysedt_batch_"):
                if name.startswith(prefix) and name.endswith(".log"):
                    stems.add(_strip_aedb(name[len(prefix):][:-len(".log")]))
                    break
    items: list[dict[str, Any]] = []
    suffixes = {"config_json": "_config.json", "spec_json": "_spec.json"}
    for stem in sorted(stems):
        row: dict[str, Any] = {"stem": stem}
        for key in ("config_json", "spec_json"):
            candidate = root_path / f"{stem}{suffixes[key]}"
            row[key] = str(candidate) if candidate.exists() else None
        # 批后导出 Touchstone：裸 stem 优先，.aedb 工程名形态（x.aedb_
        # export.s4p）为兜底别名
        ts = export_ts.get(stem.lower()) or export_ts.get(
            f"{stem.lower()}.aedb")
        row["touchstone"] = str(ts) if ts is not None else None
        # 日志面：.aedb 工程的日志名带 .aedb 尾缀（hfss_batch 按工程名
        # 派生），双形态取首个存在者
        solve_log = _first_existing(
            root_path / f"ansysedt_batch_{stem}.log",
            root_path / f"ansysedt_batch_{stem}.aedb.log")
        extract_log = _first_existing(
            root_path / f"ansysedt_batch_extract_{stem}.log",
            root_path / f"ansysedt_batch_extract_{stem}.aedb.log")
        row["solve_log"] = str(solve_log) if solve_log is not None else None
        row["extract_log"] = (str(extract_log) if extract_log is not None
                              else None)
        aedb = aedbs.get(stem)
        row["aedb"] = str(aedb) if aedb is not None else None
        row["solved"] = row["solve_log"] is not None
        items.append(row)
    return ok_envelope(root=str(root_path), n_projects=len(items),
                       items=items, templates=_template_catalog())

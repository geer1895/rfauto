"""em sweep：DOE/矩阵编排器 v1（aurora_k K10 席，2026-10-23；反馈 P16/F9）。

用户实战形态（16 组=2 器件 × 2 版本 × 4 衬底厚度）原先靠 bash 循环串行跑：
手工保证单 AEDT、手工看内存、手工清孤儿进程、手工跳过已完成 case、手工
汇总 16 份 Touchstone。本模块把该流程收敛为 ``rfauto em sweep cases.yaml``
一条命令，分三面（全部薄编排零数值面，铁律 7）：

- ``plan_sweep``   ：cases.yaml 装载+矩阵全积展开+resume 语义判定（纯读，
  零副作用——目标 run 目录已有完成产物则标 done 供跳过）；
- ``run_sweep``    ：逐 case 串行执行（v1 恒 ``max_aedt=1``，>1 显式拒绝）：
  可选启动前 janitor → 逐 case 内存闸（低于阈值=该 case 阻塞如实失败
  **不硬跑**，P4"31GB 机器被孤儿 AEDT 推到提交量 56/59GB"防线）→
  调既有单 case 执行链（``api.run_once``：跑一个 recipe 得一个 run 目录
  的现成正道——campaign_executor 的 final_verify 同款消费面）→case 级
  结果落 ``<case_dir>/case.json``；
- ``summarize_sweep``：扫全部 case run 目录汇总 L/Q/SRF/C/R/S21 类指标
  （主口径=run 产物 ``results/metrics.json`` 的既有读数；补充口径=K8 的
  ``core.deembed.z12_series_metrics`` 对 Touchstone 现场提取，2 端口
  series/1 端口 shunt）+summary.csv/summary.json 落盘；提取不到的指标
  如实列 missing（#122：不凑绿）。对比图 v1 不做（matplotlib 出图留
  followUp，结果恒带 note 声明）。

复用清单（防重复建设）：执行核=api.run_once（禁改其本体）；内存闸/
janitor=resource_janitor_service（S-A 席，只消费）；指标提取=K8 扩展的
core.deembed 纯函数面；runs 根=infra.runs_paths.runs_root（#144 隔离：
测试 chdir tmp 即重定向，绝不污染仓 runs/ 湖）。

cases.yaml schema（纯数据层；axes 间笛卡尔全积，用户 2×2×4=16 形态）::

    base_recipe: recipes/oct_ind.yaml   # 必填；相对 cases.yaml 所在目录
    adapter: hfss                        # 可选（缺省 hfss；hfss|fake）
    naming: {sep: "-"}                   # 可选（case_id 各轴 label 的连接符）
    params: {er: 12.85}                  # 可选（全体 case 公共参数覆盖）
    axis_key: {thickness: sub_t_um}      # 可选（轴名→recipe 参数名映射，
                                         #   缺省同名）
    matrix:                              # 必填；轴序=书写序（展开与命名用）
      device: [ind, idc]                 # 标量值 → params[轴名或映射名]=值
      version:                           # dict 值 → label 必填命名 +
        - label: v5                      #   params 子 dict 整组覆盖
          params: {metal_t_um: 5.0}
        - label: v6
          params: {metal_t_um: 3.0}
      thickness: [200, 150, 100, 50]

每 case 一个 case 目录：``<runs>/em_sweep/sweep_<sha8>/<case_id>/``
（sweep 身份=配置内容指纹，同 yaml 重跑/resume 天然落同根；case 目录内
``case.recipe.yaml``=合并后的配方副本+``case.json``=执行账本）。case_id
各轴 label 以 sep join；label 禁路径非法字符（Windows 保留字符/空白，
点名拒绝防目录穿越），另拒 Windows 文件名陷阱（aurora_l A2 席，K20/R4
P2）：尾点/尾空格（落盘剥除后 ``v5.`` 与 ``v5`` 同一物理目录→case.json
相互覆盖串案）、保留设备名（con/nul/aux/prn/com1-9/lpt1-9 不区分大小写，
含 con.yaml 带扩展名形态——mkdir 直接失败整 case 失败）、连续点。

resume 语义：case.json status=done **且**其记录的 run 目录复核通过
（meta.json 终态 done + results/ 有 Touchstone）才算已完成——产物缺失
如实降级 pending 重跑，不凭账本一句 done 放行（P11"旧产物冒充新结果"
防线）。
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.infra.runs_paths import runs_root
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["plan_sweep", "run_sweep", "summarize_sweep"]

#: sweep 工作根（runs/ 约定证据区内；runs_root 双根收敛=测试 chdir tmp 即隔离）
SWEEP_BASE_DIRNAME = "em_sweep"

#: summary 收敛对比（K16/P6）的网格轴自动识别：轴名含 "mesh" 或为 "grid"
#: 即视为网格档轴（convergence_axis 未显式给出时；多轴命中=歧义不猜）。
_MESH_AXIS_TOKENS = ("mesh", "grid")

#: case 目录内的执行账本/物化配方文件名。
CASE_RECORD_FILE = "case.json"
CASE_RECIPE_FILE = "case.recipe.yaml"

#: 汇总产物文件名（落 sweep 根）。
SUMMARY_CSV_FILE = "summary.csv"
SUMMARY_JSON_FILE = "summary.json"

#: 单 case 执行链缺省（api.run_once：build→solve→post→metrics→sNp 一条龙；
#: 模块级便于测试 monkeypatch 钉通道，#139 口径）。
def _default_case_executor(recipe_path: Path, adapter_name: str) -> dict[str, Any]:
    from rfauto.service.api import run_once  # lazy: run-path（真机链按需载入）

    return run_once(str(recipe_path), adapter_name=adapter_name)


# ─── cases.yaml 装载与矩阵展开（纯数据层，零执行面）──────────────────────────

#: label 白名单外的禁字符（Windows 路径保留字符+空白+控制类；点名拒绝防穿越）。
_LABEL_FORBIDDEN = re.compile(r'[\\/:*?"<>|\s]')

#: Windows 保留设备名（不区分大小写；首个点前主干命中即拒——con.yaml 与 con
#: 同样非法，Windows 一律解析成设备；com10/lpt10 不在保留列故不拒）。
_WINDOWS_RESERVED_STEMS = re.compile(
    r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE)


def _validate_windows_label_traps(label: str, where: str) -> None:
    """case 目录名成分的 Windows 文件名陷阱校验（K20/R4 P2，白名单正则之外）。

    三条补钉：①尾点/尾空格——Windows 落盘剥除结尾点与空格，``v5.`` 与
    ``v5`` 同一物理目录（case_id 去重按原串判不出，case.json 相互覆盖
    串案）；②保留设备名——con/nul/aux/prn/com1-9/lpt1-9（不区分大小写，
    含带扩展名形态 con.yaml），mkdir 直接失败整 case 失败；③连续点——
    ``..`` 入名碍读也是穿越类口子，点名拒绝。非法抛 ``ValueError``（装
    载层统一翻译成 error 信封）。
    """
    if label != label.rstrip(" ."):
        raise ValueError(
            f"{where} {label!r} 以点或空格结尾（Windows 文件名限制：结尾的点与"
            "空格落盘时被剥除，'v5.' 与 'v5' 会落同一物理目录相互覆盖）")
    if ".." in label:
        raise ValueError(f"{where} {label!r} 含连续点（Windows 文件名限制）")
    if _WINDOWS_RESERVED_STEMS.match(label):
        raise ValueError(
            f"{where} {label!r} 是 Windows 保留设备名（CON/PRN/AUX/NUL/"
            "COM1-9/LPT1-9 不区分大小写，含带扩展名形态如 con.yaml；"
            "Windows 文件名限制——目录会创建失败）")


def _load_yaml(path: Path) -> dict[str, Any] | None:
    """yaml 装载（顶层非 mapping=非法形态返回 None 由调用方如实报错）。"""
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _normalize_axis_values(
    axis: str, values: Any, mapped_key: str,
) -> list[tuple[str, dict[str, Any]]]:
    """轴值列表归一：每值 → (label, 覆盖参数 dict)。

    标量值 → params[mapped_key]=值（label=str(值)；mapped_key=axis_key
    映射后的 recipe 参数名，缺省轴名）；dict 值 → ``label`` 必填（命名）+
    ``params`` 子 dict（整组覆盖，键原样不经映射）。非法形态抛
    ``ValueError``（装载层统一翻译成 error 信封）。
    """
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError(f"matrix.{axis} 的值必须是列表，实际 {type(values).__name__}")
    if not list(values):
        raise ValueError(f"matrix.{axis} 的值列表为空（每轴至少一个值）")
    out: list[tuple[str, dict[str, Any]]] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Mapping):
            label = str(value)
            _validate_windows_label_traps(label, f"matrix.{axis} 的 label")
            out.append((label, {mapped_key: value}))
            continue
        label = value.get("label")
        if not isinstance(label, str) or not label:
            raise ValueError(
                f"matrix.{axis} 的 dict 值必须带非空字符串 label（case 命名面）：{value!r}")
        _validate_windows_label_traps(label, f"matrix.{axis} 的 label")
        params = value.get("params")
        if params is None:
            params = {}
        if not isinstance(params, Mapping):
            raise ValueError(f"matrix.{axis}[{label!r}].params 必须是映射，实际 "
                             f"{type(params).__name__}")
        out.append((label, dict(params)))
    return out


def _axis_param_key(axis_key: Mapping[str, Any] | None, axis: str) -> str:
    """轴名 → recipe 参数名（axis_key 映射优先，缺省同名）。"""
    if axis_key is None:
        return axis
    mapped = axis_key.get(axis)
    return axis if mapped is None else str(mapped)


def _expand_matrix(matrix: Mapping[str, Any], axis_key: Mapping[str, Any] | None,
                   base_params: Mapping[str, Any], global_params: Mapping[str, Any],
                   sep: str) -> list[dict[str, Any]]:
    """axes 笛卡尔全积 → case 清单（每 case=合并后 params+axes label+case_id）。

    轴序=yaml 书写序（Python dict 保序）；覆盖优先级=轴值覆盖 > 全局
    params > 基配方 params（后写胜）。dict 轴值的 params 子 dict 键原样
    （不经 axis_key 映射——映射只管标量轴值的键名）。
    """
    if not matrix:
        raise ValueError("matrix 不能为空（至少一个轴）")
    axes = [(str(name),
             _normalize_axis_values(str(name), values,
                                    _axis_param_key(axis_key, str(name))))
            for name, values in matrix.items()]
    case_ids: set[str] = set()
    cases: list[dict[str, Any]] = []
    for combo in itertools.product(*(values for _name, values in axes)):
        labels: dict[str, str] = {}
        overrides: dict[str, Any] = dict(global_params)
        for (axis, _values), (label, case_params) in zip(axes, combo, strict=True):
            labels[axis] = label
            overrides.update(case_params)
        case_id = sep.join(labels[axis] for axis, _v in axes)
        if not case_id or case_id in {".", ".."} \
                or _LABEL_FORBIDDEN.search(case_id):
            raise ValueError(f"case_id 含路径非法字符或为空（axis label 拼接）：{case_id!r}")
        # sep 拼接面终门（label 各自合法仍可能拼出 Windows 陷阱，如 sep 含点串）
        _validate_windows_label_traps(case_id, "case_id（label 拼接结果）")
        if case_id in case_ids:
            raise ValueError(f"case_id 重复（axis label 拼接歧义）：{case_id!r}")
        case_ids.add(case_id)
        cases.append({
            "case_id": case_id,
            "axes": labels,
            "overrides": dict(overrides),
            "params": {**dict(base_params), **overrides},
        })
    return cases


def _sweep_fingerprint(recipe_sha: str, config: Mapping[str, Any]) -> str:
    """sweep 身份指纹：基配方内容哈希+归一配置的 canonical JSON sha1 前 8 位。"""
    canonical = json.dumps(
        {"recipe_sha": recipe_sha, "config": dict(config)},
        ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]


# ─── plan_sweep：装载+展开+resume 判定（纯读零副作用）────────────────────────


def _case_completed(case_dir: Path, record: Mapping[str, Any]) -> bool:
    """resume 完成判据：账本 done **且** run 目录产物复核通过。

    复核=meta.json 终态 done + results/ 下有 Touchstone（params.s*p）——
    产物缺失如实降级 pending 重跑（P11 防线：不凭账本一句 done 放行）。
    """
    if str(record.get("status")) != "done":
        return False
    run_dir = Path(str(record.get("run_dir") or ""))
    if not run_dir.is_dir():
        return False
    meta_path = run_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(meta, dict) or str(meta.get("status")) != "done":
        return False
    if not any(run_dir.glob("results/params.s*p")):
        return False
    # 内容指纹复核（K20 审查 P2-3）：盘上 sNp 被旧文件顶替的 case 不能凭
    # 存在性放行——stale/unreadable/manifest_corrupt 一律降级 pending 重跑
    # （freshness gate 用户验收场景在 DOE 链上同样成立）；legacy（无
    # manifest 的老 case）按设计放行带 note。
    try:
        from rfauto.service.runs_verify_service import verify_run

        verdict = verify_run(run_dir)
    except Exception:  # 校验面故障不阻塞 resume 判定，但也不冒充通过（#105）
        return False
    return str(verdict.get("status")) != "stale" and bool(verdict.get("ok", True))


def _read_case_record(case_dir: Path) -> dict[str, Any]:
    """读 case.json 执行账本（缺失/损坏=None 语义的空 dict）。"""
    path = case_dir / CASE_RECORD_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _case_freshness(run_dir: Path | None) -> tuple[str | None, str]:
    """case run 目录 → (freshness 状态, note)（K4 verify_run 单源，只读）。

    aurora_l A3（R2 侦察 Top2）：summarize 的 metrics.json 主口径读数
    此前对"事后被旧 sNp 顶替"不设防——16 case 的产物被顶替后照常进
    summary。本 helper 每行出 ``freshness`` 列：fresh/stale/legacy 三态
    透传 verify_run；run 目录不在场 → (None, "")（该 case 已有 missing
    记账，不冒充状态）；校验面自身故障 → ("unknown", 诊断 note)
    （#105：观测面不得阻塞汇总主路径）。
    """
    if run_dir is None:
        return None, ""
    try:
        from rfauto.service.runs_verify_service import verify_run

        verdict = verify_run(run_dir)
    except Exception as exc:  # 校验面故障如实 unknown 不阻塞（#105）
        return "unknown", f"新鲜度校验不可用（非阻断）: {exc}"
    status = str(verdict.get("status", "unknown"))
    note = str(verdict.get("note") or "")
    if status == "stale":
        kinds = ",".join(sorted({
            str(issue.get("kind")) for issue in (verdict.get("issues") or [])
            if issue.get("kind")}))
        note = f"stale（{kinds}）：盘上产物与 run 收官指纹不符，采信前先复核"
    return status, note


def plan_sweep(cases_yaml: str | Path, *, resume: bool = False,
               adapter_override: str | None = None) -> dict[str, Any]:
    """cases.yaml → 展开后的 sweep 计划（纯读零副作用）。

    返回 ok 信封：{sweep_id, sweep_root, n_cases, adapter, base_recipe,
    cases:[{case_id, axes, params, case_dir, status:"pending"|"done"}],
    resume:{n_done, n_pending}}。``resume=True`` 时对既有 case 目录做
    完成复核（``_case_completed``），完成者标 done 供 run_sweep 跳过；
    缺省 False=全部 pending（重跑不跳）。装载/展开任何非法形态 → error
    信封（errors 点名原因，不猜不凑）。

    收敛对比轴（K16/P6）：cases.yaml 可选 ``convergence_axis`` 键显式
    指定网格档轴（必须是 matrix 轴名）；缺省自动识别——轴名含 "mesh"/
    "grid" 且恰一个命中者当选（零命中/多命中=不猜，轴=None，summary
    不出收敛列）。
    """
    cases_path = Path(cases_yaml)
    if not cases_path.is_file():
        return error_envelope(f"cases.yaml 不存在: {cases_path}")
    config = _load_yaml(cases_path)
    if config is None:
        return error_envelope(
            f"cases.yaml 不可读或顶层不是映射: {cases_path}")

    base_recipe_ref = config.get("base_recipe")
    if not isinstance(base_recipe_ref, str) or not base_recipe_ref.strip():
        return error_envelope("base_recipe 必填（基配方路径，相对 cases.yaml 所在目录）")
    base_recipe_path = Path(base_recipe_ref)
    if not base_recipe_path.is_absolute():
        base_recipe_path = cases_path.parent / base_recipe_path
    base_recipe = _load_yaml(base_recipe_path)
    if base_recipe is None:
        return error_envelope(f"base_recipe 不可读或顶层不是映射: {base_recipe_path}")

    adapter = adapter_override or str(config.get("adapter") or "hfss")
    if adapter not in ("hfss", "fake"):
        return error_envelope(f"adapter 只能是 hfss|fake，实际 {adapter!r}")

    naming = config.get("naming")
    naming = naming if isinstance(naming, Mapping) else {}
    sep = str(naming.get("sep", "-") or "-")
    if _LABEL_FORBIDDEN.search(sep) or sep in {".", ".."}:
        return error_envelope(f"naming.sep 含路径非法字符: {sep!r}")

    global_params = config.get("params")
    if global_params is None:
        global_params = {}
    if not isinstance(global_params, Mapping):
        return error_envelope("params（公共参数覆盖）必须是映射")
    axis_key = config.get("axis_key")
    if axis_key is None:
        axis_key = {}
    if not isinstance(axis_key, Mapping):
        return error_envelope("axis_key（轴名→参数名映射）必须是映射")
    matrix = config.get("matrix")
    if not isinstance(matrix, Mapping):
        return error_envelope("matrix 必填（轴名→值列表的映射，笛卡尔全积）")
    axis_names = [str(name) for name in matrix]
    # 收敛对比轴（K16/P6）：显式 config 键优先（必须是 matrix 轴名）；
    # 缺省自动识别——轴名含 "mesh"/"grid" 且恰一个命中者当选（歧义不猜）。
    conv_axis_raw = config.get("convergence_axis")
    if conv_axis_raw is not None:
        convergence_axis = str(conv_axis_raw)
        if convergence_axis not in axis_names:
            return error_envelope(
                f"convergence_axis 必须是 matrix 轴名之一 {axis_names}，"
                f"实际 {convergence_axis!r}")
    else:
        meshish = [a for a in axis_names
                   if any(tok in a.lower() for tok in _MESH_AXIS_TOKENS)]
        convergence_axis = meshish[0] if len(meshish) == 1 else None
    base_params = base_recipe.get("params")
    if base_params is None:
        base_params = {}
    if not isinstance(base_params, Mapping):
        return error_envelope(f"基配方 params 不是映射: {base_recipe_path}")

    try:
        cases = _expand_matrix(matrix, axis_key, base_params, global_params, sep)
    except ValueError as exc:
        return error_envelope(f"矩阵展开失败: {exc}")

    recipe_sha = hashlib.sha256(
        json.dumps(base_recipe, ensure_ascii=False, sort_keys=True,
                   default=str).encode("utf-8")).hexdigest()[:16]
    sweep_id = _sweep_fingerprint(recipe_sha, {
        "matrix": dict(matrix), "params": dict(global_params),
        "axis_key": dict(axis_key), "sep": sep, "adapter": adapter})
    sweep_root = runs_root() / SWEEP_BASE_DIRNAME / f"sweep_{sweep_id}"

    n_done = 0
    for case in cases:
        case_dir = sweep_root / case["case_id"]
        case["case_dir"] = str(case_dir)
        status = "pending"
        if resume:
            record = _read_case_record(case_dir)
            if _case_completed(case_dir, record):
                status = "done"
                n_done += 1
        case["status"] = status
    return ok_envelope(
        sweep_id=sweep_id, sweep_root=str(sweep_root), adapter=adapter,
        base_recipe=str(base_recipe_path), resume=resume, n_cases=len(cases),
        n_done=n_done, n_pending=len(cases) - n_done,
        convergence_axis=convergence_axis, cases=cases)


# ─── run_sweep：资源闸+逐 case 串行执行（v1 恒 max_aedt=1）───────────────────


def _write_case_record(case_dir: Path, payload: Mapping[str, Any]) -> None:
    """case.json 账本落盘（best-effort #105：写失败不阻塞执行主路径）。"""
    try:
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / CASE_RECORD_FILE).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True,
                       default=str),
            encoding="utf-8")
    except OSError:
        pass


def _janitor_pre_clean() -> dict[str, Any]:
    """启动前 janitor：扫疑似孤儿 ansysedt + AEDT 锁 → 属主复核后白名单清理。

    消费 resource_janitor_service（S-A 席）单源，doctor --janitor-clean
    同款语义（只动扫描出现过的白名单项）。**锁面属主复核（K20/R4 P2）**：
    自动路径只清 ``lock_owner_verdict`` 判 owner_dead 的锁——两段序=先杀
    疑似孤儿进程、后逐锁判属主（被判杀属主的锁此刻 owner_dead 可清；用户
    另一活会话属主存活的锁保留，WARN 记 skipped_owner_alive；目录锁/无
    PID/疑似远程锁/存活通道不可用一律 undetermined 保守跳过，记
    skipped_undetermined）。janitor 自身失败只记不阻塞（#105：卫生面不是
    业务主路径的故障点）。
    """
    from rfauto.service.resource_janitor_service import (
        janitor_clean,
        janitor_scan,
        lock_owner_verdict,
    )

    try:
        scan = janitor_scan()
        if not scan.get("ok"):
            return {"ok": False, "errors": scan.get("errors") or ["扫描未成功"]}
        kill_pids = sorted(int(p["pid"]) for p in scan.get("processes") or []
                          if p.get("suspect"))
        clean_kills = janitor_clean(kill_pids=kill_pids, locks=[], dry_run=False)
        # 锁属主复核在击杀之后：属主刚被本轮击杀的锁此刻判 dead 可清；
        # 属主仍存活的锁（用户活会话）保留——并发保存冲突防线。
        skipped_alive: list[dict[str, Any]] = []
        skipped_undetermined: list[dict[str, Any]] = []
        removable_locks: list[str] = []
        lock_entries = list(scan.get("locks") or [])
        for lk in lock_entries:
            lock_path = str(lk["path"])
            verdict = lock_owner_verdict(lock_path)
            kind = str(verdict.get("verdict"))
            if kind == "owner_dead":
                removable_locks.append(lock_path)
            elif kind == "owner_alive":
                skipped_alive.append({
                    "path": lock_path, "pid": verdict.get("pid"),
                    "process_path": verdict.get("process_path")})
            else:
                skipped_undetermined.append({
                    "path": lock_path, "reason": verdict.get("reason")})
        clean_locks = janitor_clean(kill_pids=[], locks=removable_locks,
                                    dry_run=False)
        kills_summary = dict(clean_kills.get("summary") or {})
        locks_summary = dict(clean_locks.get("summary") or {})
        return {
            "ok": bool(clean_kills.get("ok")) and bool(clean_locks.get("ok")),
            "n_suspect_killed_candidates": len(kill_pids),
            "n_lock_candidates": len(lock_entries),
            "n_lock_owner_alive_skipped": len(skipped_alive),
            "n_lock_undetermined_skipped": len(skipped_undetermined),
            "skipped_owner_alive": skipped_alive,
            "skipped_undetermined": skipped_undetermined,
            "warnings": ([f"{len(skipped_alive)} 把锁属主进程仍存活，已保留"
                          "（活会话工程锁不可静默删）"] if skipped_alive else []),
            "clean_summary": {
                "n_killed": int(kills_summary.get("n_killed") or 0)
                            + int(locks_summary.get("n_killed") or 0),
                "n_lock_removed": int(kills_summary.get("n_lock_removed") or 0)
                                  + int(locks_summary.get("n_lock_removed") or 0),
                "n_already_gone": int(kills_summary.get("n_already_gone") or 0)
                                  + int(locks_summary.get("n_already_gone") or 0),
                "n_failed": int(kills_summary.get("n_failed") or 0)
                            + int(locks_summary.get("n_failed") or 0),
            },
            "clean_errors": (clean_kills.get("errors") or [])
                            + (clean_locks.get("errors") or []),
        }
    except Exception as exc:  # janitor 面异常如实记账不阻塞（#105）
        return {"ok": False, "errors": [f"janitor 异常: {exc}"]}


def run_sweep(
    plan: dict[str, Any],
    *,
    max_aedt: int = 1,
    min_free_gb: float = 8.0,
    janitor: bool = False,
    dry_run: bool = False,
    execute_fn: Callable[[Path, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """逐 case 串行执行计划（v1 恒串行；资源闸如实失败不硬跑）。

    - ``max_aedt``：并发 AEDT 上限，v1 只支持 1（>1 → error 信封显式
      拒绝，不静默降级）；
    - ``min_free_gb``：逐 case 前的内存闸（resource_janitor_service.
      memory_gate）；不达标=该 case 标 ``blocked_memory`` 并**停跑**（串行
      链后续 case 同样缺内存，如实失败优于连环硬跑；腾出内存后 --resume
      续跑即可）；
    - ``janitor``：启动前资源卫生清理一次（P4：孤儿 ansysedt 累积防线）；
    - ``dry_run``：只返回执行计划预览（零执行零副作用——不建目录、不调
      janitor/内存闸/执行核）；
    - ``execute_fn``：单 case 执行链注入缝（缺省=api.run_once 薄包装；
      测试 mock 通道，#139 口径）。

    case 级状态词表：pending/running/done/failed/blocked_memory/
    skipped_resume/not_run。执行核失败的 case 记 failed 后**继续**下一个
    case（DOE 要最大化数据产出；单 case 失败不连坐）。返回信封 ok=全部
    case 终态 done 或 skipped_resume。
    """
    if not plan.get("ok"):
        return error_envelope(plan.get("errors") or ["计划不可用（先过 plan_sweep）"],
                              plan=plan)
    try:
        max_aedt_i = int(max_aedt)
    except (TypeError, ValueError):
        return error_envelope(f"max_aedt 必须是整数，实际 {max_aedt!r}")
    if max_aedt_i != 1:
        return error_envelope(
            f"当前只支持串行（max_aedt=1），实际 {max_aedt_i}——多 AEDT 并发"
            "编排留待后续版本")
    try:
        min_free_gb_f = float(min_free_gb)
    except (TypeError, ValueError):
        return error_envelope(f"min_free_gb 必须是数字，实际 {min_free_gb!r}")

    sweep_root = Path(str(plan.get("sweep_root")))
    adapter = str(plan.get("adapter") or "hfss")
    cases = list(plan.get("cases") or [])

    if dry_run:
        return ok_envelope(
            dry_run=True, verdict="DRY_RUN", sweep_id=plan.get("sweep_id"),
            sweep_root=str(sweep_root), adapter=adapter, max_aedt=1,
            min_free_gb=min_free_gb_f, janitor=janitor,
            n_cases=len(cases), resume=plan.get("resume"),
            cases=[{"case_id": c.get("case_id"),
                    "status": c.get("status"),
                    "case_dir": c.get("case_dir")} for c in cases])

    janitor_report: dict[str, Any] | None = None
    if janitor:
        janitor_report = _janitor_pre_clean()

    results: list[dict[str, Any]] = []
    n_done = n_failed = n_blocked = n_skipped = 0
    blocked = False
    for case in cases:
        case_id = str(case.get("case_id"))
        case_dir = Path(str(case.get("case_dir") or (sweep_root / case_id)))
        entry: dict[str, Any] = {
            "case_id": case_id, "axes": dict(case.get("axes") or {}),
            "adapter": adapter}
        if str(case.get("status")) == "done":
            n_skipped += 1
            results.append({**entry, "status": "skipped_resume"})
            continue
        if blocked:
            results.append({**entry, "status": "not_run",
                            "reason": "前序 case 内存闸阻塞，串行链停跑"})
            continue

        from rfauto.service.resource_janitor_service import memory_gate

        gate = memory_gate(min_free_gb_f)
        entry["memory_gate"] = {
            "ok": bool(gate.get("ok")),
            "available_gb": gate.get("available_gb"),
            "threshold_gb": gate.get("threshold_gb"),
            "message": gate.get("message"),
        }
        if not gate.get("ok"):
            n_blocked += 1
            blocked = True
            record = {**entry, "status": "blocked_memory",
                      "elapsed_s": 0.0}
            _write_case_record(case_dir, record)
            results.append(record)
            continue

        # 物化 case 配方副本（基配方深拷贝 + 该 case 参数覆盖）
        import copy

        import yaml

        base_recipe = _load_yaml(Path(str(plan.get("base_recipe"))))
        if base_recipe is None:  # 计划后基配方被移走：如实失败
            n_failed += 1
            record = {**entry, "status": "failed",
                      "errors": [f"基配方不可读: {plan.get('base_recipe')}"]}
            _write_case_record(case_dir, record)
            results.append(record)
            continue
        recipe_case = copy.deepcopy(base_recipe)
        recipe_case["params"] = dict(case.get("params") or {})
        case_dir.mkdir(parents=True, exist_ok=True)
        recipe_path = case_dir / CASE_RECIPE_FILE
        try:
            recipe_path.write_text(
                yaml.safe_dump(recipe_case, allow_unicode=True, sort_keys=False),
                encoding="utf-8")
        except OSError as exc:
            n_failed += 1
            record = {**entry, "status": "failed",
                      "errors": [f"case 配方物化失败: {exc}"]}
            _write_case_record(case_dir, record)
            results.append(record)
            continue
        entry["recipe_path"] = str(recipe_path)
        _write_case_record(case_dir, {**entry, "status": "running"})

        started = time.monotonic()
        exec_errors: list[str] = []
        try:
            fn = execute_fn or _default_case_executor
            raw = fn(recipe_path, adapter)
            exec_ok = bool(raw.get("ok"))
            exec_errors = [str(e) for e in (raw.get("errors") or [])]
            entry["run_id"] = str(raw.get("run_id") or "")
            entry["run_dir"] = str(raw.get("run_dir") or "")
        except Exception as exc:  # 执行核异常=case 失败（不吞不猜，继续后续 case）
            exec_ok = False
            exec_errors = [f"执行核异常: {exc}"]
        elapsed = time.monotonic() - started
        if exec_ok:
            n_done += 1
            status = "done"
        else:
            n_failed += 1
            status = "failed"
        record = {**entry, "status": status, "ok": exec_ok,
                  "errors": exec_errors, "elapsed_s": round(elapsed, 3)}
        _write_case_record(case_dir, record)
        results.append(record)

    ok = n_failed == 0 and n_blocked == 0
    payload = ok_envelope(
        sweep_id=plan.get("sweep_id"), sweep_root=str(sweep_root),
        adapter=adapter, max_aedt=1, min_free_gb=min_free_gb_f,
        janitor=janitor_report, n_cases=len(cases), n_done=n_done,
        n_failed=n_failed, n_blocked=n_blocked, n_skipped_resume=n_skipped,
        cases=results)
    if not ok:
        return error_envelope(
            [f"sweep 未全部成功：failed={n_failed} blocked_memory={n_blocked}"
             f"（done={n_done} skipped_resume={n_skipped}"
             f"——内存阻塞时腾出内存后 --resume 续跑）"],
            **{k: v for k, v in payload.items() if k != "ok"})
    return payload


# ─── summarize_sweep：跨 case 指标汇总 + summary.csv/json 落盘 ───────────────


def _extract_touchstone_metrics(run_dir: Path) -> tuple[dict[str, Any], str | None]:
    """run 目录 Touchstone → K8 z12_series_metrics 现场提取（best-effort）。

    K16 单源收编：实现移至 service/em_metrics_service.extract_touchstone
    _metrics（em metrics --run 与收敛对比同源消费），此处薄委托保持原
    私有签名（返回 (扁平指标 dict 或空, 失败原因或 None)）。
    """
    from rfauto.service.em_metrics_service import extract_touchstone_metrics

    return extract_touchstone_metrics(run_dir)


def _convergence_pair_rows(
    rows: list[dict[str, Any]], axis_names: list[str], conv_axis: str,
) -> list[dict[str, Any]]:
    """收敛轴配对对比（K16/P6）：仅网格档不同的 case 两两出收敛判定。

    配对规则：其余轴完全相同的行归一组；组内按收敛轴值排序（可数值则
    数值序，否则字典序——档位标签如 coarse/fine 也有确定序）；相邻两行
    成对（3 档=2 对）。每对按 Q→SRF→C 回退链选第一个可判指标（判据=
    service.em_metrics_service.convergence_check，rel_tol 缺省 0.10）。
    行的 ``convergence`` 列=简标（同处多对的行=最后一对覆盖，全量明细
    在返回 pairs）。
    """
    from rfauto.service.em_metrics_service import (
        CONVERGENCE_METRIC_FALLBACK,
        convergence_check,
    )

    other_axes = [a for a in axis_names if a != conv_axis]
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple((a, row.get(a)) for a in other_axes)
        groups.setdefault(key, []).append(row)

    def _sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
        value = row.get(conv_axis)
        try:
            return (0, float(value), "")
        except (TypeError, ValueError):
            return (1, 0.0, str(value))

    pairs: list[dict[str, Any]] = []
    for group_key in sorted(groups, key=repr):
        members = sorted(groups[group_key], key=_sort_key)
        for a, b in itertools.pairwise(members):
            result: dict[str, Any] | None = None
            for metric in CONVERGENCE_METRIC_FALLBACK:
                result = convergence_check(a, b, metric=metric)
                if str(result.get("verdict")) != "insufficient_data":
                    break
            if result is None:  # pragma: no cover — 回退链非空，防御
                continue
            label = f"{result.get('verdict')}({result.get('metric')}"
            if result.get("rel_dev") is not None:
                label += f",dev={result['rel_dev']:.1%}"
            label += ")"
            a["convergence"] = label
            b["convergence"] = label
            pairs.append({
                "case_ids": [a.get("case_id"), b.get("case_id")],
                f"{conv_axis}_values": [a.get(conv_axis), b.get(conv_axis)],
                "metric": result.get("metric"),
                "verdict": result.get("verdict"),
                "converged": result.get("converged"),
                "rel_dev": result.get("rel_dev"),
                "rel_tol": result.get("rel_tol"),
                "notes": result.get("notes") or [],
            })
    return pairs


def summarize_sweep(plan: dict[str, Any]) -> dict[str, Any]:
    """扫全部 case run 目录 → 指标行 + summary.csv/summary.json 落盘。

    每 case 两路读数（互补，缺谁列谁）：
    1. 主口径=run 产物 ``results/metrics.json`` 的 metrics/cost（配方
       objectives 的现成读数——L/Q/SRF/C/R/S21 类由配方指标面产出）；
    2. 补充口径=Touchstone 现场 K8 提取（series/shunt C/R/Q/SRF——不依赖
       配方 objectives 定义）。

    提取不到的指标如实列 missing（无 case 账本/无 run 目录/无 metrics.json/
    Touchstone 提取失败逐 case 点名，#122 不凑绿）。对比图 v1 不做（note
    声明，matplotlib 出图留 followUp）。

    收敛对比列（K16/P6）：plan 带 ``convergence_axis`` 时，仅该轴不同
    的相邻档 case 两两出收敛判定（``convergence_check``，Q→SRF→C 回退
    链，rel_tol=0.10）——行加 ``convergence`` 简标列、summary 载荷加
    ``convergence_pairs`` 全量明细；>10% 偏差判 not_converged（默认网
    格能解≠数值可用，报告侧显式提示）。无轴时形态与 K10 完全一致。

    freshness 列（aurora_l A3，R2 侦察 Top2）：每 case 读账本后对
    run_dir ``verify_run``（K4 单源）——stale 行标 ``freshness="stale"``
    红列并入 summary（**不整批拒绝**，DOE 最大化产出；stale 计数进
    summary notes 与 ``n_stale_rows``）；legacy（老 run 无 manifest）
    放行带 note；校验面故障记 unknown 不阻塞（#105）。
    """
    if not plan.get("ok"):
        return error_envelope(plan.get("errors") or ["计划不可用（先过 plan_sweep）"])
    sweep_root = Path(str(plan.get("sweep_root")))
    first_case = (plan.get("cases") or [{}])[0]
    axis_names = [str(a) for a in (first_case.get("axes") or {})]

    rows: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for case in plan.get("cases") or []:
        case_id = str(case.get("case_id"))
        case_dir = Path(str(case.get("case_dir")))
        row: dict[str, Any] = {"case_id": case_id}
        for axis in axis_names:
            row[axis] = (case.get("axes") or {}).get(axis)
        record = _read_case_record(case_dir)
        row["status"] = str(record.get("status") or "pending")
        run_dir_str = str(record.get("run_dir") or "")
        row["run_dir"] = run_dir_str
        case_missing: list[str] = []
        if not record:
            case_missing.append("case.json 账本缺失（未执行过）")
        run_metrics: dict[str, Any] = {}
        run_dir = Path(run_dir_str) if run_dir_str else None
        if run_dir is not None and run_dir.is_dir():
            try:
                metrics_data = json.loads(
                    (run_dir / "results" / "metrics.json").read_text(
                        encoding="utf-8"))
                run_metrics = dict(metrics_data.get("metrics") or {})
                row["cost"] = metrics_data.get("cost")
            except (OSError, ValueError):
                case_missing.append("results/metrics.json 不可读")
        else:
            case_missing.append("run 目录不可用（未执行或未记录）")
        for key, value in run_metrics.items():
            row[str(key)] = value
        if run_dir is not None and run_dir.is_dir():
            flat, why = _extract_touchstone_metrics(run_dir)
            if why:
                case_missing.append(f"Touchstone 补充提取: {why}")
            for key, value in flat.items():
                row[f"em.{key}"] = value
        # freshness 列（aurora_l A3）：读账本后对 run_dir verify_run——
        # stale 行标红列并入 summary（不整批拒绝，DOE 最大化产出）；
        # legacy 行带 note（老 case 不废）；stale 计数进 summary notes。
        freshness, fresh_note = _case_freshness(
            run_dir if run_dir is not None and run_dir.is_dir() else None)
        row["freshness"] = freshness
        row["freshness_note"] = fresh_note
        if case_missing:
            missing.append({"case_id": case_id, "missing": case_missing})
        rows.append(row)

    # 收敛对比列（K16/P6）：plan 带网格轴（convergence_axis 显式或自动
    # 识别）时，仅网格档不同的相邻档 case 两两出收敛判定；无轴零改动
    # （既有 summary 形态不变）。
    conv_axis = plan.get("convergence_axis")
    conv_pairs: list[dict[str, Any]] = []
    if conv_axis:
        conv_pairs = _convergence_pair_rows(rows, axis_names, str(conv_axis))

    # 列集=并集（确定性排序）；固定前缀列+指标列+freshness_note/run_dir
    # 收尾（freshness 列进前缀紧跟 status——标红列不被指标列挤散）
    prefix = ["case_id", *axis_names, "status", "cost"]
    if conv_axis:
        prefix.append("convergence")
    prefix.append("freshness")
    fixed_suffix = ["freshness_note", "run_dir"]
    metric_keys = sorted({k for row in rows for k in row
                          if k not in set(prefix) | set(fixed_suffix)})
    columns = prefix + [c for c in metric_keys if c != "cost"] + fixed_suffix

    n_stale_rows = sum(1 for row in rows if row.get("freshness") == "stale")
    n_legacy_rows = sum(1 for row in rows if row.get("freshness") == "legacy")

    try:
        sweep_root.mkdir(parents=True, exist_ok=True)
        import csv

        csv_path = sweep_root / SUMMARY_CSV_FILE
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for row in rows:
                writer.writerow(
                    ["" if row.get(col) is None else row.get(col)
                     for col in columns])
        json_path = sweep_root / SUMMARY_JSON_FILE
        notes = [
            "对比图暂未提供（matplotlib L/Q/SRF/C/R/S21 vs "
            "参数出图留后续版本）",
            "em.* 列=Touchstone 现场提取（series=2 端口"
            "/shunt=1 端口）；其余指标列=run 产物 metrics.json",
        ]
        if n_stale_rows or n_legacy_rows:
            notes.append(
                f"freshness 列=run 收官指纹校验（K4）：stale {n_stale_rows}"
                f"/{len(rows)} 行、legacy {n_legacy_rows} 行（老 run 无 "
                "manifest 不判新鲜度）——stale=盘上产物与收官指纹不符"
                "（旧文件顶替/漏拷/sidecar 错配），该侧行结论采信前先复核")
        if conv_axis:
            n_not_conv = sum(1 for p in conv_pairs
                             if str(p.get("verdict")) == "not_converged")
            notes.append(
                f"convergence 列=两档网格收敛对比（轴={conv_axis}；"
                f"verdict(metric,dev) 形态；同 case 处于多对时列值=最后一对，"
                f"全量明细在 convergence_pairs）——not_converged {n_not_conv}"
                f"/{len(conv_pairs)} 对")
        json_path.write_text(
            json.dumps({"sweep_id": plan.get("sweep_id"),
                        "sweep_root": str(sweep_root),
                        "n_rows": len(rows),
                        "n_stale_rows": n_stale_rows,
                        "columns": columns,
                        "rows": rows, "missing": missing,
                        "convergence_axis": conv_axis,
                        "convergence_pairs": conv_pairs,
                        "notes": notes},
                       ensure_ascii=False, indent=1, sort_keys=False,
                       default=str),
            encoding="utf-8")
    except OSError as exc:
        return error_envelope(f"summary 落盘失败: {exc}", sweep_root=str(sweep_root),
                              rows=rows, missing=missing)

    n_done_rows = sum(1 for row in rows if row.get("status") == "done")
    return ok_envelope(
        sweep_id=plan.get("sweep_id"), sweep_root=str(sweep_root),
        summary_csv=str(csv_path), summary_json=str(json_path),
        n_rows=len(rows), n_done_rows=n_done_rows,
        n_stale_rows=n_stale_rows,
        columns=columns, rows=rows, missing=missing,
        convergence_axis=conv_axis, convergence_pairs=conv_pairs,
        note="对比图 v1 不做（出图留 followUp）；missing 逐 case 点名如实"
             + (f"；convergence 列=两档网格收敛对比（轴={conv_axis}，P6）"
                if conv_axis else "")
             + (f"；freshness：stale {n_stale_rows}/{len(rows)} 行"
                "（结论采信前先复核该侧）" if n_stale_rows else ""))

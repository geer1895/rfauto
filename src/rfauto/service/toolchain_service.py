"""AX-4（aurora_r R-03）服务器工具链 lock——circuit-bench-toolchains
images.lock.json digest 锁定思想的仓内落地（思想级吸收，零新依赖零镜像）。

把 AGENTS 规则 0"服务器侧版本必须=本机"从规则文本升级为 machine-readable
lock：本机采集工具链指纹（HFSS/ADS/openEMS/python 版本 + 关键包版本）写
``configs/toolchain_lock.local.yaml``（schema_version+generated_at+
generator 版本），比对器对 lock vs 探测结果**逐项**比对输出一致/漂移清单
——漂移 = 服务器版本≠本机，正是规则 0 要拦的事（远程 probe 流程把服务器
侧探测 dict 作为 ``probed`` 传入 toolchain_lock_check）。

采集/比对分层（规则 4 服务层 JSON 进出）：

- ``probe_toolchain``：本机指纹采集（best-effort #105——任何单工具探测
  失败降级 unknown，永不 raise）；**内容零敏感信息**（版本串+探测通道
  描述，无安装路径/凭据/主机名）；
- ``build_toolchain_lock``：lock 文档规范化（纯函数；时间戳/生成器版本
  经参数注入后确定性）；
- ``compare_toolchain_lock``：逐项比对器（纯函数，永不 raise）——三态
  verdict：``match``（全对齐）/ ``drift``（≥1 项版本漂移）/
  ``unverifiable``（零漂移但存在任一侧 unknown 不可判项，如实不凑绿
  #122 同族语义）；
- ``toolchain_lock_write`` / ``toolchain_lock_check``：信封入口（ok/
  error/skipped 三态构造器单源）。

lock 文件格式（yaml，键序稳定）::

    schema_version: '1.0'
    generated_at: <ISO8601 UTC>
    generator: rfauto/toolchain_lock
    generator_version: <rfauto.__version__>
    tools: {hfss: {version, version_probe?}, ads: {...}, openems: {...},
            python: {...}}
    packages: {numpy: ..., scipy: ..., scikit-rf: ..., pyaedt: ...,
               optuna: ...}

敏感口径如实申报（gitignore 现状）：.gitignore 只点名
``configs/settings.local.yaml``/``configs/remote_machines.local.yaml``/
``configs/chat_settings.yaml`` 三文件，**无 ``*.local.yaml`` 通配**——
本 lock 内容因此按零敏感信息设计（实测
``git check-ignore configs/toolchain_lock.local.yaml`` 不命中）；文件名
仍取 ``.local.yaml`` 后缀表达"每机一份"语义。若日后引入安装路径类字段，
须先补 gitignore 条目再改格式。

挂账（本席禁改 cli/、mcp_tools/——无 CLI/MCP 叶，处方进 docstring）：
- CLI 候选叶：``rfauto remote toolchain-lock [--check]``——消费本模块
  ``toolchain_lock_write``/``toolchain_lock_check`` 两信封入口（脚本形态
  先行：scripts/toolchain_lock.py）；
- MCP 候选工具：``remote_toolchain_lock_check``——远程 probe 回传服务器
  侧探测 dict 后逐项比对（规则 0 机器可读门）；
- openEMS 引擎侧版本目前=Python 绑定 importlib.metadata 口径（与
  openems_solver._engine_stamp 同源），C++ 引擎 exe --version 探针未接线
  （solver_versions 溯源同款后续项）。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from pathlib import Path
from typing import Any

from rfauto import __version__
from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

#: lock 文档 schema 版本（工具集/键形变化时递增，旧 lock 由比对器按
#: "缺项=unverifiable" 如实降级不炸）。
TOOLCHAIN_LOCK_SCHEMA_VERSION = "1.0"

#: lock 文件缺省落点（相对 cwd——#144 家族同款口径，测试 chdir 隔离；
#: 运营从仓根执行 scripts/toolchain_lock.py 即落 configs/）。
DEFAULT_LOCK_PATH = Path("configs") / "toolchain_lock.local.yaml"

#: 生成器标识（circuit-bench 口径：lock 自报生成器与版本，消费方可审计）。
GENERATOR = "rfauto/toolchain_lock"

#: 采集工具键序（lock 形态稳定；探测不到的引擎 version 如实 unknown）。
_TOOL_ORDER = ("hfss", "ads", "openems", "python")

#: 关键包清单（确定性 lock 语义=固定集合；缺装如实 unknown）。
_PROBED_PACKAGES = ("numpy", "scipy", "scikit-rf", "pyaedt", "optuna")

#: 未知/不可判项的诚实哨兵（AX-3 同款 unknown 纪律，不伪造）。
_UNKNOWN = "unknown"


def _str_or_unknown(value: Any) -> str:
    """值 → 非空 str；None/空/str 化失败一律 unknown（#105 如实降级）。"""
    if value is None:
        return _UNKNOWN
    try:
        s = str(value).strip()
    except Exception:  # pragma: no cover - 防御性
        return _UNKNOWN
    return s or _UNKNOWN


def _probe_hfss_row() -> dict[str, Any]:
    """HFSS 行（infra/version_probe 现有探测——source=通道描述无路径）。

    未发现安装如实 "absent"（可判值——lock 侧 absent vs 探测侧版本=漂移）；
    探测自身异常才降级 "unknown"（不可判）。
    """
    try:
        from rfauto.infra.version_probe import resolve_aedt_install

        install = resolve_aedt_install()
        if install:
            row: dict[str, Any] = {
                "version": _str_or_unknown(install.get("aedt_version")),
            }
            source = install.get("source")
            if source is not None and str(source).strip():
                row["version_probe"] = str(source).strip()
            return row
        return {"version": "absent"}
    except Exception:  # pragma: no cover - 观测面兜底（#105）
        pass
    return {"version": _UNKNOWN}


def _probe_ads_row() -> dict[str, Any]:
    """ADS 行（hpeesof_dir 目录名解析，如 "2027"）。

    settings 解析链：cwd 相对 configs（load_settings 缺省，#295 家族已知
    cwd 相对性）→ 无 hpeesof_dir 时回退仓根 configs（模块定位，非 cwd——
    脚本从任意目录执行不再产生假 unverifiable）→ 仍无如实 unknown。
    """
    try:
        from rfauto.infra.version_probe import detect_ads_version

        version = detect_ads_version()
        if version:
            return {"version": str(version), "version_probe": "hpeesof_dir"}
        repo_configs = Path(__file__).resolve().parents[3] / "configs"
        from rfauto.infra.config import load_settings

        settings = load_settings(repo_configs / "settings.yaml")
        if settings.hpeesof_dir:
            version = detect_ads_version(settings.hpeesof_dir)
            if version:
                return {"version": str(version),
                        "version_probe": "hpeesof_dir(repo_configs)"}
    except Exception:  # pragma: no cover - 观测面兜底（#105）
        pass
    return {"version": _UNKNOWN}


def _probe_openems_row() -> dict[str, Any]:
    """openEMS 行（Python 绑定 importlib.metadata——_engine_stamp 同口径）。

    绑定未安装如实 "absent"（可判）；其他异常降级 "unknown"（不可判）。
    """
    try:
        from importlib.metadata import version as _pkg_version

        return {"version": _pkg_version("openEMS"),
                "version_probe": "importlib.metadata"}
    except _PackageNotFoundError:
        return {"version": "absent"}
    except Exception:
        return {"version": _UNKNOWN}


def _probe_python_row() -> dict[str, Any]:
    """Python 行（sys.version_info 三段；解释器自身无探测失败面）。"""
    v = sys.version_info
    return {"version": f"{v.major}.{v.minor}.{v.micro}",
            "version_probe": "sys.version_info"}


def probe_toolchain(*, include_packages: bool = True) -> dict[str, Any]:
    """本机工具链指纹采集（best-effort #105，永不 raise，零敏感信息）。

    Returns
    -------
    dict
        ``{"tools": {<name>: {"version": str, "version_probe"?: str}},
        "packages"?: {<name>: <version str>}}``。tools 键序=``_TOOL_ORDER``
        固定序（lock 形态稳定）；任一工具探测失败该行 version=unknown；
        ``include_packages=False`` 时省略 packages 键（锁"只锁引擎"形态）。
    """
    rows = {
        "hfss": _probe_hfss_row,
        "ads": _probe_ads_row,
        "openems": _probe_openems_row,
        "python": _probe_python_row,
    }
    tools: dict[str, Any] = {}
    for name in _TOOL_ORDER:
        try:
            tools[name] = rows[name]()
        except Exception as exc:  # 行级兜底（#105：单工具探测失败只降级该行）
            tools[name] = {"version": _UNKNOWN,
                           "version_probe": f"probe_error:{type(exc).__name__}"}
    out: dict[str, Any] = {"tools": tools}
    if include_packages:
        packages: dict[str, str] = {}
        for pkg in _PROBED_PACKAGES:
            try:
                from importlib.metadata import version as _pkg_version

                packages[pkg] = _str_or_unknown(_pkg_version(pkg))
            except _PackageNotFoundError:
                packages[pkg] = "absent"  # 缺装=可判值（vs lock 版本=漂移）
            except Exception:
                packages[pkg] = _UNKNOWN  # 探测异常=不可判
        out["packages"] = packages
    return out


def build_toolchain_lock(
    probe: dict[str, Any] | None = None,
    *,
    generated_at: str | None = None,
    generator_version: str | None = None,
) -> dict[str, Any]:
    """lock 文档规范化（时间戳/生成器版本经参数注入后为纯函数）。

    probe 缺省/非 dict → 空采集（tools/packages 空 dict——消费方比对时
    全部 unverifiable 如实呈现）。键形归一：tools 行非 dict 降级为
    ``{"version": <str|unknown>}``；packages 值 str 化；非 str 键 str() 化。
    """
    probe = probe if isinstance(probe, dict) else {}
    tools_raw = probe.get("tools")
    tools: dict[str, Any] = {}
    if isinstance(tools_raw, dict):
        for name, row in tools_raw.items():
            if isinstance(row, dict):
                normalized = {str(k): v for k, v in row.items()}
                # version 恒 str（缺键/None/空 → unknown，不伪造）
                normalized["version"] = _str_or_unknown(
                    normalized.get("version"))
                tools[str(name)] = normalized
            else:
                tools[str(name)] = {"version": _str_or_unknown(row)}
    packages_raw = probe.get("packages")
    packages: dict[str, str] = {}
    if isinstance(packages_raw, dict):
        for name, ver in packages_raw.items():
            packages[str(name)] = _str_or_unknown(ver)
    return {
        "schema_version": TOOLCHAIN_LOCK_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "generator": GENERATOR,
        "generator_version": generator_version
        if generator_version is not None else str(__version__),
        "tools": tools,
        "packages": packages,
    }


def _compare_section(
    kind: str,
    lock_section: Any,
    probe_section: Any,
) -> list[dict[str, Any]]:
    """单节（tools/packages）逐项比对（纯函数内部件，永不 raise）。"""
    lock_map = lock_section if isinstance(lock_section, dict) else {}
    probe_map = probe_section if isinstance(probe_section, dict) else {}
    items: list[dict[str, Any]] = []
    for name in sorted(set(lock_map) | set(probe_map)):
        lock_row = lock_map.get(name)
        probe_row = probe_map.get(name)
        lock_version = (lock_row.get("version")
                        if isinstance(lock_row, dict) else lock_row)
        probe_version = (probe_row.get("version")
                         if isinstance(probe_row, dict) else probe_row)
        lock_version = _str_or_unknown(lock_version) if lock_row is not None \
            else _UNKNOWN
        probe_version = _str_or_unknown(probe_version) if probe_row is not None \
            else _UNKNOWN
        if _UNKNOWN in (lock_version, probe_version):
            status = "unverifiable"
        elif lock_version == probe_version:
            status = "match"
        else:
            status = "drift"
        items.append({
            "kind": kind,
            "name": str(name),
            "lock": lock_version,
            "probe": probe_version,
            "status": status,
        })
    return items


def compare_toolchain_lock(
    lock: dict[str, Any] | None,
    probe: dict[str, Any] | None,
) -> dict[str, Any]:
    """lock vs 探测结果逐项比对（纯函数，永不 raise）。

    比对面 = ``tools`` 与 ``packages`` 两节的键并集（lock 缺项/probe 多项
    均如实 unverifiable，不静默放过——#316 多报不放过方向）。返回::

        {"verdict": "match"|"drift"|"unverifiable",
         "items": [{kind, name, lock, probe, status}, ...],
         "drift": [<同形 item>], "unverifiable": [<同形 item>],
         "match_count": int}

    verdict 语义：任一 drift → "drift"（规则 0 拦截面）；零 drift 但存在
    unverifiable → "unverifiable"（如实不凑绿）；全 match → "match"。
    值语义：``"unknown"``=探测异常不可判（unverifiable）；``"absent"``=
    未安装（可判——lock 有版本 vs 探测 absent=漂移，规则 0 实环境差）。
    """
    lock = lock if isinstance(lock, dict) else {}
    probe = probe if isinstance(probe, dict) else {}
    items = _compare_section("tool", lock.get("tools"), probe.get("tools"))
    items += _compare_section("package", lock.get("packages"),
                              probe.get("packages"))
    drift = [it for it in items if it["status"] == "drift"]
    unverifiable = [it for it in items if it["status"] == "unverifiable"]
    if drift:
        verdict = "drift"
    elif unverifiable:
        verdict = "unverifiable"
    else:
        verdict = "match"
    return {
        "verdict": verdict,
        "items": items,
        "drift": drift,
        "unverifiable": unverifiable,
        "match_count": sum(1 for it in items if it["status"] == "match"),
    }


def toolchain_lock_write(path: str | Path | None = None) -> dict[str, Any]:
    """采集本机指纹并写 lock 文件（信封 ok/error；JSON 进出规则 4）。

    path 缺省 ``configs/toolchain_lock.local.yaml``（相对 cwd）。返回
    ``{"ok": True, "path", "schema_version", "generated_at",
    "generator_version", "tools", "packages"}``。
    """
    try:
        import yaml

        probe = probe_toolchain()
        lock = build_toolchain_lock(probe)
        target = Path(path) if path is not None else DEFAULT_LOCK_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            yaml.safe_dump(lock, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        return ok_envelope(
            path=str(target),
            schema_version=lock["schema_version"],
            generated_at=lock["generated_at"],
            generator_version=lock["generator_version"],
            tools=lock["tools"],
            packages=lock["packages"],
        )
    except Exception as exc:  # 信封收敛（#105：写 lock 失败不炸调用链）
        return error_envelope(
            [f"toolchain lock 写入失败: {type(exc).__name__}: {exc}"])


def toolchain_lock_check(
    probed: dict[str, Any] | None = None,
    *,
    lock_path: str | Path | None = None,
) -> dict[str, Any]:
    """lock vs 探测逐项比对（信封 ok/skipped/error；供远程 probe 流程调用）。

    Args:
        probed: 服务器侧（或被测机）探测 dict（``probe_toolchain`` 同形）。
            None → 本机自探（自检形态：本机现状 vs 本机 lock 的漂移巡检）。
        lock_path: lock 文件路径（缺省 ``configs/toolchain_lock.local.yaml``）。

    Returns
    -------
    dict
        lock 缺失 → ``skipped_envelope``（lock 尚未生成的机器上属如实跳过，
        不是错误）；lock 读取失败 → ``error_envelope``；成功 →
        ``{"ok": True, "verdict", "items", "drift", "unverifiable",
        "match_count", "lock_path", "lock_generated_at",
        "probed_source": "caller"|"local_probe"}``。
    """
    target = Path(lock_path) if lock_path is not None else DEFAULT_LOCK_PATH
    if not target.exists():
        return skipped_envelope(
            f"lock 文件不存在: {target}（先在基准机上跑 "
            "scripts/toolchain_lock.py 生成）",
            verdict="SKIP",
            lock_path=str(target),
        )
    try:
        import yaml

        lock = yaml.safe_load(target.read_text(encoding="utf-8"))
    except Exception as exc:
        return error_envelope(
            [f"lock 文件读取失败: {type(exc).__name__}: {exc}"],
            lock_path=str(target))
    if probed is None:
        probe = probe_toolchain()
        probed_source = "local_probe"
    else:
        probe = probed
        probed_source = "caller"
    result = compare_toolchain_lock(lock, probe)
    return ok_envelope(
        verdict=result["verdict"],
        items=result["items"],
        drift=result["drift"],
        unverifiable=result["unverifiable"],
        match_count=result["match_count"],
        lock_path=str(target),
        lock_generated_at=(lock.get("generated_at")
                           if isinstance(lock, dict) else None),
        probed_source=probed_source,
    )

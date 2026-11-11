"""IBIS (.ibs) 解析服务包装（aurora_q Q-X46，2026-11-07）。

:mod:`rfauto.core.ibis_parser`（单源解析内核）的规则 4 JSON 进出薄
包装——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸
dict），零数值逻辑（IV 查找表/暂态表/插值全在 core 确定性内核；
铁律 7）。

两函数（与 CLI 同源同名薄壳消费）：

- :func:`parse_ibis_file`：全结构化解析（header/components/models/
  model_selectors/pins + IV 查找表 + Ramp + 暂态表）+ component/model
  过滤 + 表体裁面开关 + stats 计数（对返回视图计数——liberty 同款
  口径）；
- :func:`list_ibis_inventory`：清单只读面（component 名/引脚数 +
  model 名/类型/表名录/行数 + 选择器名录；全量提取只报计数不落表体）。

错误归一：文件不可读/解码失败/语法违规（IbisParseError）/过滤目标
不存在 → error 信封（errors 恒 list[str]），CLI 层 exit 1。解码链=
utf-8-sig 优先（吞 BOM）、Latin-1 兜底（IBIS 规范正文 ASCII，Latin-1
恒可解——供应商文件头注释偶发高位字节不炸读取）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——liberty_service 同款先例，新模块零金快照
漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.ibis_parser import (
    IV_TABLE_KINDS,
    PARSER_SCHEMA_VERSION,
    IbisParseError,
    extract_ibis,
    parse_ibis,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def _read_text(path: str | Path) -> str:
    """读文件文本：utf-8-sig 优先（吞 BOM），Latin-1 兜底（正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _stats(view: dict[str, Any]) -> dict[str, int]:
    """对返回视图计数（过滤/裁面后——liberty 同款口径）。"""
    n_iv = 0
    n_wave = 0
    n_rows = 0
    n_ramp = 0
    for m in view["models"].values():
        for k in IV_TABLE_KINDS:
            t = m.get("tables", {}).get(k)
            if t is not None:
                n_iv += 1
                n_rows += int(t["n_rows"])
        for w in m.get("waveforms", []):
            n_wave += 1
            n_rows += int(w["n_rows"])
        if m.get("ramp") is not None:
            n_ramp += 1
    return {
        "n_components": len(view["components"]),
        "n_pins": len(view["pins"]),
        "n_models": len(view["models"]),
        "n_model_selectors": len(view["model_selectors"]),
        "n_iv_tables": n_iv,
        "n_waveforms": n_wave,
        "n_table_rows": n_rows,
        "n_ramp": n_ramp,
        # warnings 随视图透传不裁面，计数与视图一致（R-22 升位批补键）。
        "n_warnings": len(view["warnings"]),
    }


def parse_ibis_file(
    path: str | Path,
    *,
    component: str | None = None,
    model: str | None = None,
    include_tables: bool = True,
) -> dict[str, Any]:
    """IBIS 文件 → 结构化信封（component/model 过滤+表体裁面）。

    - ``component``：只保留同名 component（未知名 → error 信封附可用
      清单）；pins 扁平视图同步收窄到该器件；
    - ``model``：只保留同名 model（未知名 → error 信封附可用清单）；
    - ``include_tables=False``：剪表体面（tables/waveforms/ramp 整键
      缺席；stats 对返回视图计数同步归零），模型/引脚元数据不受影响；
    - ``filters``：如实声明过滤/裁面状态。

    信封：``{"ok": True, "schema", "path", "header", "components",
    "models", "model_selectors", "pins", "warnings", "stats",
    "filters"}``（``schema="ibis/<N.0>"`` 自描述复合键——R-22 schema
    升位批补键；解析产物为解析树，键由信封携带） /
    error 信封（errors 恒 list[str]）。
    """
    try:
        file = parse_ibis(_read_text(path))
    except OSError as exc:
        return error_envelope(f"IBIS 文件不可读: {exc}")
    except IbisParseError as exc:
        return error_envelope(f"IBIS 解析失败: {exc}")
    view = extract_ibis(file, include_tables=include_tables)
    if component is not None:
        hits = [c for c in view["components"] if c["name"] == component]
        if not hits:
            names = ", ".join(c["name"] for c in view["components"]) or "无"
            return error_envelope(
                f"component 不存在: {component}（可用: {names}）")
        view["components"] = hits
        keep = {p["pin"] for p in hits[0]["pins"]}
        view["pins"] = {k: v for k, v in view["pins"].items() if k in keep}
    if model is not None:
        models = view["models"]
        if model not in models:
            return error_envelope(
                f"model 不存在: {model}"
                f"（可用: {', '.join(sorted(models)) or '无'}）")
        view["models"] = {model: models[model]}
    return ok_envelope(
        path=str(path),
        # 自描述键（R-22 schema 升位批）：``"<域>/<N.0>"`` 复合键。
        schema=f"ibis/{PARSER_SCHEMA_VERSION}",
        header=view["header"],
        components=view["components"],
        models=view["models"],
        model_selectors=view["model_selectors"],
        pins=view["pins"],
        warnings=view["warnings"],
        stats=_stats(view),
        filters={
            "component": component,
            "model": model,
            "tables": include_tables,
        },
    )


def list_ibis_inventory(path: str | Path) -> dict[str, Any]:
    """IBIS 文件 → 清单只读信封（component/model 名录+计数，不落表体）。"""
    try:
        file = parse_ibis(_read_text(path))
    except OSError as exc:
        return error_envelope(f"IBIS 文件不可读: {exc}")
    except IbisParseError as exc:
        return error_envelope(f"IBIS 解析失败: {exc}")
    view = extract_ibis(file, include_tables=True)  # 全量提取，清单只报计数
    components = [
        {
            "name": c["name"],
            "manufacturer": c["manufacturer"],
            "n_pins": len(c["pins"]),
        }
        for c in view["components"]
    ]
    model_rows = []
    for name, m in view["models"].items():
        tables = m.get("tables") or {}
        table_names = [k for k in IV_TABLE_KINDS if tables.get(k) is not None]
        n_rows = sum(int(tables[k]["n_rows"]) for k in table_names)
        n_rows += sum(int(w["n_rows"]) for w in m.get("waveforms", []))
        model_rows.append({
            "name": name,
            "model_type": m.get("model_type"),
            "table_names": table_names,
            "n_waveforms": len(m.get("waveforms", [])),
            "n_table_rows": n_rows,
            "has_ramp": m.get("ramp") is not None,
        })
    return ok_envelope(
        path=str(path),
        header=view["header"],
        components=components,
        models=model_rows,
        model_selector_names=sorted(view["model_selectors"]),
        warnings=view["warnings"],
        stats=_stats(view),
    )

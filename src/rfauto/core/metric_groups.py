"""指标绑定组（metric families）纯函数面（aurora_k K16 席，2026-10-23）。

吸收反馈 P14：衬底 200→50μm 实验里 Q 升 40% 主因 C 降 33%（Q=|X|/R，
|X| 随 C 变小而变大），R_series 反而 1.285→1.365Ω 微升——**只看 Q 会
得出"减薄显著降低损耗"的错误结论**。对策=指标不单发：同族键成组绑定，
报告/CLI 输出 Q 时自动附带同族其余键（数据在盘就附、不在盘如实标
missing），series 族恒附"Q 随 C 变，不是纯损耗"提示行。

族定义（键名与 K8 ``core.deembed.z12_series_metrics`` 输出对齐）：

- ``series_family``（2 端口串联器件）：C（或 L，感性强家族）+ R_series +
  Q_series + S21——**触发提示文案**（Q 随 C 变，判损耗看 R_series/S21）；
- ``shunt_family``（1 端口并联器件）：L（或 C）+ Q_shunt + SRF——
  天然配套（L/Q/SRF 同出）**不触发提示**。

每槽（slot）给候选键优先序：容性/感性两种形态的实际键由数据在场者
落位（如 series 槽名 "C"，感性家族实际落 ``l_series_h``——members 里
回带 resolved key，不靠槽名臆测）。

本模块纯函数零 I/O（core 层红线）；YAML 词典侧语义（q_factor 判读条）
在 knowledge/metric_glossary.yaml（K2 定稿，禁改），消费链=UI kit.js
metricBadgeHtml 悬浮（本模块不重复词典文本，只回 glossary_ref 指针）。

刻意不带 ``__all__``（metric_glossary_service 同例：check_public_api
金快照不翻面，函数保持可 import 消费）。

出处：本模块为**本仓设计**（aurora_k K16 席面，零文献转写公式）——
  series/shunt 两族的分槽与候选键优先序按 K8 ``z12_series_metrics``
  输出键对齐设计（绑定行为，非物理公式）；Q=|X|/R 为教科书串联品质
  因数定义（判读语义，非拟合系数）；"Q 随 C 变，不是纯损耗"提示吸收
  自用户反馈 P14 实验观察（衬底 200→50μm：Q↑40% 主因 C↓33%）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: series 族提示文案（P14 原话吸收；仅 series 族触发，shunt 族不提示）。
SERIES_ADVISORY = "Q 随 C 变，不是纯损耗——看 R_series 与 S21 判损耗"

#: q_factor 词典条目指针（knowledge/metric_glossary.yaml，K2 增补的判读
#: 语义条；绑定结果回带该指针供 UI/报告链接词典悬浮）。
Q_FACTOR_GLOSSARY_REF = "q_factor"


@dataclass(frozen=True)
class MetricFamily:
    """指标族定义：槽名 → 候选键优先序（第一个在场者落位）。"""

    name: str
    slots: dict[str, tuple[str, ...]]
    #: 族提示文案（None=不提示；shunt 族天然配套不设）。
    prompt: str | None
    #: 族主指标的词典条目 metric_id（无则 None）。
    glossary_ref: str | None = None

    @property
    def candidate_keys(self) -> tuple[str, ...]:
        """全族候选键（去重保序；missing 如实清单的检查面）。"""
        seen: list[str] = []
        for keys in self.slots.values():
            for key in keys:
                if key not in seen:
                    seen.append(key)
        return tuple(seen)


#: series 族（2 端口串联：C/R/Q/S21 成组；容性 C 优先，感性落 l_series_h）。
SERIES_FAMILY = MetricFamily(
    name="series_family",
    slots={
        "C": ("c_series_f", "l_series_h"),
        "R_series": ("r_series_ohm",),
        "Q_series": ("q_series",),
        "S21": ("s21_db",),
    },
    prompt=SERIES_ADVISORY,
    glossary_ref=Q_FACTOR_GLOSSARY_REF,
)

#: shunt 族（1 端口并联：L（容性落 c_shunt_f）/Q/SRF 成组；不触发提示）。
SHUNT_FAMILY = MetricFamily(
    name="shunt_family",
    slots={
        "L": ("l_shunt_h", "c_shunt_f"),
        "Q_shunt": ("q_shunt",),
        "SRF": ("srf_hz",),
    },
    prompt=None,
    glossary_ref=Q_FACTOR_GLOSSARY_REF,
)

#: 族注册表（detect/bind 的 group 白名单；键=族名）。
METRIC_FAMILIES: dict[str, MetricFamily] = {
    SERIES_FAMILY.name: SERIES_FAMILY,
    SHUNT_FAMILY.name: SHUNT_FAMILY,
}


def _is_present(value: Any) -> bool:
    """在场判据：非 None 且非空串（0.0 是合法读数，不得当缺失顶掉——
    #364④ ``or`` 惯语家族同款教训：数值可达 0 的面用显式 None 判）。"""
    return value is not None and value != ""


def detect_metric_group(metrics: Mapping[str, Any]) -> str | None:
    """按候选键在场数自动判族（命中多者胜；平手/零命中→ None）。

    纯确定性：只看族候选键在映射中的在场数（``_is_present``），不看值
    语义。两族同 hit 数时返回 None（歧义如实不猜，调用方可显式传 group）。
    """
    hits = {
        name: sum(1 for key in fam.candidate_keys if _is_present(metrics.get(key)))
        for name, fam in METRIC_FAMILIES.items()
    }
    best = max(hits.values())
    if best <= 0:
        return None
    winners = [name for name, n in hits.items() if n == best]
    return winners[0] if len(winners) == 1 else None


def bind_metric_group(
    metrics: Mapping[str, Any], *, group: str | None = None
) -> dict[str, Any]:
    """同族键绑定（纯函数）：Q 输出位自动附带同族其余键。

    Args:
        metrics: 扁平指标映射（键=K8 输出键或 metrics.json 指标名；
            值可为 None——None/空串按缺数据如实记 missing，0.0 是合法值）。
        group: 显式族名（``series_family``/``shunt_family``）；缺省走
            ``detect_metric_group`` 自动判族，判不出→ ``group=None`` 的
            如实结果（不猜族）。

    Returns:
        dict：``group``（族名或 None）/ ``detected``（是否自动判出）/
        ``members``（槽名 → {key, value, status}——key=落位候选键，
        status=ok|missing）/ ``attached``（在场同族键值对——附带输出面）/
        ``missing``（全族检查过但不在场的候选键清单）/ ``advisory``
        （series 族且 Q 在场时=提示文案；其余 None）。

    语义钉（P14）：series 族 advisory 触发条件=Q 槽在场（输出 Q 时才
    解释 Q）；shunt 族 prompt=None 恒不提示。
    """
    family: MetricFamily | None
    detected = False
    if group is not None:
        family = METRIC_FAMILIES.get(str(group))
        if family is None:
            raise ValueError(
                f"未知 metric 族: {group!r}（可选 {sorted(METRIC_FAMILIES)}）")
    else:
        name = detect_metric_group(metrics)
        family = METRIC_FAMILIES.get(name) if name else None
        detected = family is not None
    if family is None:
        return {"group": None, "detected": False, "members": {},
                "attached": {}, "missing": [], "advisory": None}

    members: dict[str, dict[str, Any]] = {}
    attached: dict[str, Any] = {}
    missing: list[str] = []
    q_present = False
    for slot, keys in family.slots.items():
        resolved_key: str | None = None
        value: Any = None
        for key in keys:
            candidate = metrics.get(key)
            if _is_present(candidate):
                resolved_key, value = key, candidate
                break
        if resolved_key is None:
            # 槽内全部候选键都不在场 → 逐键如实记 missing（第一个候选键
            # 作槽代表位，其余候选键一并列入——"不在盘"按键名说话）。
            missing.extend(keys)
            members[slot] = {"key": keys[0], "value": None, "status": "missing"}
        else:
            members[slot] = {"key": resolved_key, "value": value, "status": "ok"}
            attached[resolved_key] = value
            if slot in ("Q_series", "Q_shunt"):
                q_present = True
    advisory = family.prompt if (family.prompt is not None and q_present) else None
    return {
        "group": family.name,
        "detected": detected,
        "members": members,
        "attached": attached,
        "missing": missing,
        "advisory": advisory,
        "glossary_ref": family.glossary_ref,
    }

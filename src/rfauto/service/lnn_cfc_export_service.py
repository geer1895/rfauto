"""CfC 隐态轨迹导出（JSON 落盘面）——Q-R3R 遗留清偿席（Q-W4-1 登记）。

两层分工（分层架构不可破；规则 4 服务层 JSON 进出）：

- **内存面**：``rfauto.optimization.surrogate.lnn_cfc.hidden_state_doc`` /
  ``LnnCfcSurrogate.hidden_states``——rollout 逐 step 隐态快照转 JSON 原生
  doc（纯计算零 I/O）；
- **落盘面（本件）**：:func:`export_cfc_hidden_states`——输出路径**调用方
  显式给**，缺省 ``None`` **拒写**（ValueError；#144 同族：本面不选缺省
  落盘点，禁 cwd 相对默认路径向 runs/ 湖漏写假数据）。

契约（与 animation ``cfc_state`` kind 同形；读取契约面=
``rfauto.service.animation.loaders.load_cfc_state``）：根 object 含非空
矩形数值矩阵 ``hidden``（[T][H]，T=step 数、H=hidden_dim，全有限）、可选
等长 ``time``、可选 ``hidden_dim``/``dt``/``params``/``provenance`` 透传键。

确定性：同 doc 两写逐字节同（``sort_keys`` + 固定缩进 + 尾换行 + LF）；
零时间戳零环境依赖。

本模块无 ``__all__``：公开面快照 tests/gold/public_api.json 本席冻结
（新增公开名收编=显式评审动作，留后续席位 ``--generate`` 重钉）；消费面
走模块路径直接 import。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _validate_hidden_doc(doc: Any) -> tuple[int, int]:
    """隐态 doc 校验（写面兜底）：返回 (T, H)。

    Raises:
        ValueError: 非 dict / 缺非空 hidden / 非矩形 / 含非有限或非数值 /
            time 等长破坏或非有限 / hidden_dim 与实测列数不符。
    """
    if not isinstance(doc, dict):
        raise ValueError(
            f"doc 须为 dict（收到 {type(doc).__name__}）——内存 doc 由 "
            "lnn_cfc.hidden_state_doc / LnnCfcSurrogate.hidden_states 产出")
    raw = doc.get("hidden")
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "doc 缺非空 hidden 矩阵（[T][H] 逐 step 隐态行）——残缺数据"
            "显式拒绝（不写残缺 JSON，读取契约面=loaders.load_cfc_state）")
    width: int | None = None
    for k, row in enumerate(raw):
        if not isinstance(row, list) or not row:
            raise ValueError(f"doc.hidden[{k}] 须为非空数值行（矩形矩阵）")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ValueError(
                f"doc.hidden[{k}] 列数 {len(row)} != 第 0 行 {width}"
                "——非矩形矩阵显式拒绝")
        for c, v in enumerate(row):
            try:
                fv = float(v)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"doc.hidden[{k}][{c}] 不是合法数值：{v!r}") from exc
            if not math.isfinite(fv):
                raise ValueError(
                    f"doc.hidden[{k}][{c}] 非有限数值 {v!r}——写 NaN/Inf 会"
                    "产出非标 JSON，显式拒绝")
    t = doc.get("time")
    if t is not None:
        if not isinstance(t, list) or len(t) != len(raw):
            raise ValueError(
                f"doc.time 长度 {len(t) if isinstance(t, list) else '非数组'}"
                f" != hidden 步数 {len(raw)}——等长破坏显式拒绝")
        for k, v in enumerate(t):
            try:
                fv = float(v)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"doc.time[{k}] 不是合法数值：{v!r}") from exc
            if not math.isfinite(fv):
                raise ValueError(f"doc.time[{k}] 非有限数值 {v!r}")
    hd = doc.get("hidden_dim")
    if hd is not None and int(hd) != width:
        raise ValueError(
            f"doc.hidden_dim={hd!r} != 实测列数 {width}——声明与数据不符"
            "显式拒绝")
    return len(raw), int(width)


def export_cfc_hidden_states(doc: dict[str, Any],
                             output_path: str | Path | None) -> dict[str, Any]:
    """隐态 doc → JSON 落盘；``output_path=None`` **拒写**（Q-W4-1 遗留出口）。

    Args:
        doc: 隐态 doc（内存面产出，形态见模块 docstring；写前兜底校验）。
        output_path: 落盘路径（调用方显式给；``None``=拒写——本面不选缺省
            落盘点，防 cwd 相对默认路径向 runs/ 湖漏写，#144 同族）。

    Returns:
        原样返回 ``doc``（写面零语义改写；落盘成功由文件存在与读回相等钉）。

    Raises:
        ValueError: output_path 为 None 或 doc 残缺（校验明细见
            :func:`_validate_hidden_doc`）。
        OSError: 路径不可写（如实上抛，不静默吞）。
    """
    if output_path is None:
        raise ValueError(
            "output_path=None 拒写（#144 同族：调用方显式给落盘路径，本面"
            "不选缺省落盘点；仅要内存 doc 直接用 "
            "lnn_cfc.hidden_state_doc / LnnCfcSurrogate.hidden_states）")
    p = Path(output_path)  # #140：PathLike 收敛惯例
    _validate_hidden_doc(doc)
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True,
                         indent=1) + "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(payload, encoding="utf-8", newline="\n")
    return doc

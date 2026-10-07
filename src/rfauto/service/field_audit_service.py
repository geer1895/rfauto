"""场图多模态审计封装接口（Y2）——场图 PNG → 确定性预检 + 结构化审计请求。

Y2 规格（池十五 Y2 / 月计划 carry-over §二.2）：E/H 场分布切片渲染 →
确定性检查（能量局域性/馈电激励有效性）+ 多模态 LLM 审计（能量被困/
异常热点=被困模直接证据）——几何视觉审计（#1b 惯例）延伸到场级。

本仓边界：zai 多模态工具面（analyze_image 等）在用户侧 MCP 环境（仓外）；
本模块是**仓内封装接口**，不做任何网络调用：
1. 确定性 PNG 预检（纯 stdlib：IHDR 尺寸解析 + sha256 指纹 + 尺寸退化
   守卫）——请求可复现（#7：LLM/agent 永不产生物理数字，审计结论回填
   后由确定性判据面消费）；
2. 结构化审计请求构造（提示词模板含确定性问题清单：能量被困/异常热点/
   馈电激励有效性三问，对应 #174 激励体积为零与 #344 近被困模两类历史
   事故的场级指纹）；
3. 可注入 client 分发：``client(payload)->dict`` 由调用方注入（仓外
   zai/其他多模态通道）；缺省无 client=skipped（#105 best-effort，不阻塞
   主路径）；测试注入 fake client，零网络（#139 monkeypatch 钉通道）。
"""

from __future__ import annotations

import hashlib
import json
import struct
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

__all__ = [
    "build_field_audit_request",
    "dispatch_field_audit",
    "png_precheck",
]

#: PNG 签名（8 字节）+ IHDR 块头（4 长度+4 类型）；宽高在 IHDR 数据前 8 字节
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: 审计问题清单（确定性文本，三问对应历史事故场级指纹）
_AUDIT_QUESTIONS = (
    "能量是否局域在非馈电区域（被困模指纹，#344 家族场级证据）？",
    "是否存在异常热点/场奇异（热点位置与馈点/缝隙的相对关系）？",
    "馈电激励是否有效（馈点附近场是否被激起，#174 激励体积为零的场级指纹）？",
)


def png_precheck(png_path: str | Path) -> dict[str, Any]:
    """确定性 PNG 预检：尺寸（IHDR 解析）+ sha256 + 尺寸退化守卫。

    纯 stdlib 实现（不解码像素——像素级确定性检查归渲染端，本接口只做
    请求面守卫）。返回 envelope；``degenerate=True`` 表示尺寸异常
    （宽或高 <2px，无法承载场分布切片）。

    References:
        PNG 规范 IHDR 布局：signature(8B) + 长度(4B) + "IHDR"(4B) +
        width(4B BE) + height(4B BE)（ISO/IEC 15948-2003 5.3 节布局，
        字节偏移为规范定义值，非文献数值）。
    """
    path = Path(png_path)
    try:
        blob = path.read_bytes()
    except OSError as exc:
        return error_envelope([f"PNG 不可读: {path}（{exc}）"], path=str(path))
    digest = hashlib.sha256(blob).hexdigest()
    if len(blob) < 24 or blob[:8] != _PNG_SIGNATURE:
        return error_envelope(
            [f"非 PNG 文件（签名不符）: {path}"],
            path=str(path), sha256=digest, size_bytes=len(blob))
    width, height = struct.unpack(">II", blob[16:24])
    return ok_envelope(
        path=str(path),
        width_px=int(width),
        height_px=int(height),
        size_bytes=len(blob),
        sha256=digest,
        degenerate=(width < 2 or height < 2),
    )


def build_field_audit_request(
    png_paths: list[str | Path],
    *,
    run_id: str | None = None,
    template: str | None = None,
    port_note: str | None = None,
    question: str | None = None,
) -> dict[str, Any]:
    """构造结构化场图审计请求（确定性 prompt + 预检后的图片清单）。

    Args:
        png_paths: 场切片 PNG 路径列表（逐张过 :func:`png_precheck`；
            任一张不可读只记入 ``precheck_errors``，不阻塞其余图片）。
        run_id/template: 关联 run 与模板名（进上下文，best-effort 透传）。
        port_note: 端口/激励位置备注（馈电有效性问题的定位上下文）。
        question: 追加的自定义问题（附加到三问清单之后）。

    Returns:
        envelope：``{ok, prompt, images: [precheck...], precheck_errors,
        context}``；``prompt`` 为确定性文本（同输入逐字节同请求）。
    """
    if not png_paths:
        return error_envelope(["png_paths 不能为空"])
    images: list[dict[str, Any]] = []
    precheck_errors: list[str] = []
    for p in png_paths:
        pre = png_precheck(p)
        if pre.get("ok", False):
            images.append(pre)
        else:
            precheck_errors.extend(
                f"{p}: {msg}" for msg in pre.get("errors", []))
    if not images:
        return error_envelope(
            ["全部图片预检失败", *precheck_errors],
            precheck_errors=precheck_errors)
    questions = list(_AUDIT_QUESTIONS)
    if question:
        questions.append(str(question))
    prompt_lines = [
        "你是射频场分布审计员。以下 E/H 场切片图来自 EM 仿真后处理渲染，",
        "请逐图回答（结论引用图中位置证据，不要编造数值）：",
        *[f"{i}. {q}" for i, q in enumerate(questions, start=1)],
    ]
    if port_note:
        prompt_lines.append(f"端口/激励上下文：{port_note}")
    return ok_envelope(
        prompt="\n".join(prompt_lines),
        images=images,
        precheck_errors=precheck_errors,
        context={
            "run_id": run_id,
            "template": template,
            "n_images": len(images),
            "questions": questions,
        },
    )


def dispatch_field_audit(
    request: dict[str, Any],
    client: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """把审计请求分发给注入的多模态 client（仓外通道），best-effort。

    Args:
        request: :func:`build_field_audit_request` 的输出信封。
        client: ``payload -> dict`` 调用方注入的多模态通道（仓外 zai 等）；
            payload 只含 prompt/图片路径/上下文，不含任何二进制。
            None=未配置通道 → skipped（非失败，#105/#139 口径）。

    Returns:
        envelope：``{ok, result, request_echo}``；client 异常 → error 并
        保留原请求（可重放）；请求本身 not ok → 原样透传。
    """
    if not request.get("ok", False):
        return request
    if client is None:
        return skipped_envelope(
            "多模态审计 client 未配置（zai 工具面在仓外用户环境；"
            "注入 client 后可用）",
            request_prompt_present=bool(request.get("prompt")),
            n_images=int(request.get("context", {}).get("n_images", 0)),
        )
    payload = {
        "prompt": request.get("prompt", ""),
        "images": [img.get("path") for img in request.get("images", [])],
        "context": request.get("context", {}),
    }
    try:
        result = client(payload)
    except Exception as exc:
        return error_envelope(
            [f"多模态通道异常: {type(exc).__name__}: {exc}"],
            request_json=json.dumps(payload, ensure_ascii=False))
    return ok_envelope(result=result, request_echo=payload)

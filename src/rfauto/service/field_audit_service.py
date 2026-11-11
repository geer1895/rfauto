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

T-Q6 泛化（aurora_q Q-W7-1）："图像→审计请求"框架的通用路由入口
:func:`audit_artifact`——按扩展名分发：``.png``→既有 PNG 审计面；
``.jpg/.jpeg``→:func:`jpeg_precheck`（SOF 帧尺寸解析，同预检契约）；
``.svg``→:func:`svg_precheck`（文本可直读：根元素属性原文+元素计数）；
其他→显式 unknown（skipped 信封，契约口径=能力不适用非失败）。请求=
声明性 dict（path/kind/questions），零数值产出（预检数字是文件测量值
非物理数字，铁律 7 口径不变）。
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

__all__ = [
    "audit_artifact",
    "build_field_audit_request",
    "dispatch_field_audit",
    "jpeg_precheck",
    "png_precheck",
    "svg_precheck",
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
        png_paths: 场切片图片路径列表（逐张预检：``.png`` 走
            :func:`png_precheck`，``.jpg/.jpeg`` 走 :func:`jpeg_precheck`
            （T-Q6 泛化按扩展名路由）；参数名保留 png_paths=向后兼容）。
            任一张不可读只记入 ``precheck_errors``，不阻塞其余图片。
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
        suffix = Path(p).suffix.lower()
        pre = (jpeg_precheck(p) if suffix in (".jpg", ".jpeg")
               else png_precheck(p))
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


# ---------------------------------------------------------------------------
# T-Q6 泛化：按扩展名的 artifact 审计路由（JPG/SVG 预检 + 通用入口）
# ---------------------------------------------------------------------------

#: JPEG 签名（SOI + 首标记前导 FF；ISO/IEC 10918-1 B.1.1.3 布局）。
_JPEG_SIGNATURE = b"\xff\xd8\xff"
#: SOF 帧头标记集（0xC0-0xCF 去 DHT 0xC4/JPG 0xC8/DAC 0xCC——JPEG 1.02
#: B.1.1.4 表；SOF 内含高度宽度字段，是尺寸解析唯一权威位）。
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
#: SVG 审计缺省问题清单（结构性二问；SVG 文本可直读——问题面向结构/文本）。
_SVG_AUDIT_QUESTIONS = (
    "SVG 图元结构是否与预期设计一致（元素清单有无缺失/多余/未闭合路径）？",
    "文本内容（标注/丝印文字）是否与预期一致（文字原文与所在位置）？",
)
#: SVG 元素计数固定标签清单（计数直读的声明范围；不在清单的标签不计数）。
_SVG_COUNTED_TAGS = (
    "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "path", "text", "tspan", "g", "use", "image", "symbol",
)
#: 计入 n_draw_elements 的几何/引用类标签。
_SVG_DRAW_TAGS = frozenset(
    {"rect", "circle", "ellipse", "line", "polyline", "polygon",
     "path", "image", "use"})
_SVG_ROOT_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)


def jpeg_precheck(jpg_path: str | Path) -> dict[str, Any]:
    """确定性 JPEG 预检：SOI 签名 + 首个 SOF 帧尺寸解析 + sha256 + 退化守卫。

    与 :func:`png_precheck` 同一预检契约（同字段集：path/width_px/
    height_px/size_bytes/sha256/degenerate）。纯 stdlib 标记扫描：

    - 从 SOI 后逐标记走：独立标记（0x01/0xD0-0xD7/RSTn）无长度段；
      其余标记带 2 字节大端段长（含自身）；遇 SOS（0xDA，其后是熵编码
      数据）或 EOI（0xD9）即止——**不扫熵数据**（伪标记会误配）；
    - 首 SOF 帧头（``长度+精度+高+宽+分量数``）→ 高宽大端 2 字节各一；
      无 SOF 即止（截断/非帧数据）→ error 信封。

    退化判定与 PNG 同口径：宽或高 <2px。
    """
    path = Path(jpg_path)
    try:
        blob = path.read_bytes()
    except OSError as exc:
        return error_envelope([f"JPEG 不可读: {path}（{exc}）"], path=str(path))
    digest = hashlib.sha256(blob).hexdigest()
    if len(blob) < 4 or blob[:3] != _JPEG_SIGNATURE:
        return error_envelope(
            [f"非 JPEG 文件（签名不符）: {path}"],
            path=str(path), sha256=digest, size_bytes=len(blob))
    dims: tuple[int, int] | None = None
    n = len(blob)
    i = 2
    while i + 1 < n:
        if blob[i] != 0xFF:
            i += 1
            continue
        marker = blob[i + 1]
        if marker == 0xFF:
            i += 1  # 填充 FF——仍在标记扫描态
            continue
        if marker == 0x00:
            i += 2  # 垫字 FF 00（熵数据态；头部不应现，防御性跳过）
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            i += 2  # 独立标记无段长
            continue
        if marker in (0xD8, 0xD9, 0xDA) or i + 4 > n:
            break  # SOI 内层重入/EOI/SOS——SOF 未现即止
        seg_len = int.from_bytes(blob[i + 2:i + 4], "big")
        if seg_len < 2:
            break
        if marker in _SOF_MARKERS and i + 9 <= n:
            # SOF 段布局：长度(2)+精度(1)+Y高(2)+X宽(2)+分量数(1)——先高后宽
            height, width = struct.unpack(">HH", blob[i + 5:i + 9])
            dims = (int(width), int(height))
            break
        i += 2 + seg_len
    if dims is None:
        return error_envelope(
            ["JPEG 缺 SOF 帧头（无法确定尺寸）——文件截断或无帧数据"],
            path=str(path), sha256=digest, size_bytes=len(blob))
    width, height = dims
    return ok_envelope(
        path=str(path),
        width_px=width,
        height_px=height,
        size_bytes=len(blob),
        sha256=digest,
        degenerate=(width < 2 or height < 2),
    )


def _svg_attr(tag_text: str, name: str) -> str | None:
    """SVG 根标签属性**原文**（双/单引号都认；不转义不转数值——直读）。"""
    for pat in (rf'\b{name}\s*=\s*"([^"]*)"',
                rf"\b{name}\s*=\s*'([^']*)'"):
        m = re.search(pat, tag_text)
        if m:
            return m.group(1)
    return None


def svg_precheck(svg_path: str | Path) -> dict[str, Any]:
    """确定性 SVG 预检（文本可直读）：根元素属性原文 + 固定标签计数。

    统计级口径（边界声明）：元素计数=``<tag\\b`` 正则直读（注释/CDATA 内
    同形文本会计入——统计级不建树）；width/height/viewBox 属性**原文**
    （单位不换算、数值不派生——SVG 单位制多样，解释属消费方）。缺
    ``<svg>`` 根元素 → error 信封。
    """
    path = Path(svg_path)
    try:
        blob = path.read_bytes()
        text = blob.decode("utf-8", errors="replace")
    except OSError as exc:
        return error_envelope([f"SVG 不可读: {path}（{exc}）"], path=str(path))
    digest = hashlib.sha256(blob).hexdigest()
    root_m = _SVG_ROOT_RE.search(text)
    if root_m is None:
        return error_envelope(
            [f"非 SVG 文件（缺 <svg> 根元素）: {path}"],
            path=str(path), sha256=digest, size_bytes=len(blob))
    tag_text = root_m.group(0)
    element_counts = {
        t: len(re.findall(rf"<{t}\b", text, re.IGNORECASE))
        for t in _SVG_COUNTED_TAGS
    }
    return ok_envelope(
        path=str(path),
        size_bytes=len(blob),
        sha256=digest,
        width_attr=_svg_attr(tag_text, "width"),
        height_attr=_svg_attr(tag_text, "height"),
        view_box=_svg_attr(tag_text, "viewBox"),
        element_counts=element_counts,
        n_draw_elements=sum(element_counts[t] for t in _SVG_DRAW_TAGS),
    )


def audit_artifact(path: str | Path, *,
                   question: str | None = None) -> dict[str, Any]:
    """通用 artifact 审计路由入口（T-Q6 泛化）：按扩展名分发审计面。

    路由（扩展名大小写不敏感）：
        - ``.png`` → 既有 PNG 审计面（png_precheck + 场图三问请求）；
        - ``.jpg/.jpeg`` → jpeg_precheck + 同一图像审计面（同三问）；
        - ``.svg`` → svg_precheck + 结构性二问请求（文本可直读，prompt
          携带确定性结构摘要）；
        - 其他 → **显式 unknown**（skipped 信封：能力不适用非失败，契约
          口径；kind="unknown" 声明）。

    Returns:
        envelope（ok 态）：``{ok, kind, path, prompt, images: [预检...],
        precheck_errors, context: {kind, n_images, questions}}``——
        声明性请求 dict（path/kind/questions 顶层可读），形状与
        :func:`build_field_audit_request` 输出兼容（可直接喂
        :func:`dispatch_field_audit`）。图像类路由内部复用
        :func:`build_field_audit_request`（既有 prompt 模板零复制零漂移），
        仅注入 kind/path 契约键。坏文件 → error 信封（预检错误透传）。
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg"):
        kind = "image_png" if suffix == ".png" else "image_jpeg"
        req = build_field_audit_request([p], question=question)
        if not req.get("ok", False):
            # 单工件路由：直透预检精确原因（"全部图片预检失败"包装是
            # 多图批量语义，单路径面不适用）
            return error_envelope(
                req.get("precheck_errors") or req.get("errors") or ["预检失败"],
                kind=kind, path=str(p),
                precheck_errors=req.get("precheck_errors", []))
        out: dict[str, Any] = {"ok": True, "kind": kind, "path": str(p)}
        out.update(req)
        out["context"] = {**req.get("context", {}), "kind": kind}
        return out
    if suffix == ".svg":
        kind = "svg"
        pre = svg_precheck(p)
        if not pre.get("ok", False):
            return error_envelope(list(pre.get("errors", [])), kind=kind,
                                  path=str(p))
        questions = list(_SVG_AUDIT_QUESTIONS)
        if question:
            questions.append(str(question))
        counts = pre.get("element_counts", {})
        nonzero = "、".join(f"{k}={v}" for k, v in sorted(counts.items()) if v)
        prompt_lines = [
            "你是工程图/SVG 结构审计员。以下 SVG 为文本可直读工件，",
            "其确定性结构摘要如下（计数为文件原文统计，非物理数字）：",
            f"  画布声明：width={pre.get('width_attr')} "
            f"height={pre.get('height_attr')} viewBox={pre.get('view_box')}",
            f"  元素计数：{nonzero or '（无计入清单内的元素）'}",
            "请结合 SVG 源文本回答（结论引用元素/文字原文证据，不要编造）：",
            *[f"{i}. {q}" for i, q in enumerate(questions, start=1)],
        ]
        return ok_envelope(
            kind=kind,
            path=str(p),
            prompt="\n".join(prompt_lines),
            images=[pre],
            precheck_errors=[],
            context={"kind": kind, "n_images": 1, "questions": questions},
        )
    return skipped_envelope(
        f"扩展名 {suffix or '(无)'} 无审计路由（显式 unknown；"
        f"支持 .png/.jpg/.jpeg/.svg）",
        kind="unknown", path=str(p))

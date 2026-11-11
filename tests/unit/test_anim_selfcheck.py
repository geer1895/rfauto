"""动图自检闭环测试（Q-W4-1 T-Q4，aurora_q 席）。

验收钉（席位任务书）：
- 三检测器（verify_svg_structure/detect_frame_order/detect_text_overlap）
  各正负例（合成 SVG fixture——**run 湖真数据不进单测夹具**，真数据走
  runs/aurora_q/qw41_examples/ 脚本证据件）；
- AnimationSelfCheckReport 结构（per-issue level/kind/locator/message，
  level∈{warn,error}，issue 序固定 structure→frame→text）；
- render_animation 缺省 self_check=False 零行为变化（无 self_check 属性、
  SVG 与 True 路径逐字节同、165 既有动图测零回归——回归面由既有测试
  文件全量承担，本文件只钉缺省路径契约）。
"""

from __future__ import annotations

import json

import pytest

from rfauto.service.animation import (
    AnimationResult,
    AnimationSelfCheckedResult,
    AnimationSelfCheckReport,
    detect_frame_order,
    detect_text_overlap,
    render_animation,
    run_animation_self_check,
    verify_svg_structure,
)
from tests.unit import _anim_fixtures as fx

# ─── 合成 SVG fixture（kernel _assemble_svg 同构形态；纯字面量） ──────────────

_NS = 'xmlns="http://www.w3.org/2000/svg"'


def _svg(body: str, *, w: int = 400, h: int = 300,
         desc: str | None = None, viewBox: str | None = None) -> str:
    vb = viewBox if viewBox is not None else f"0 0 {w} {h}"
    desc_line = f"<desc>{desc}</desc>\n" if desc is not None else ""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg {_NS} width="{w}" height="{h}" viewBox="{vb}">\n'
            + desc_line + body + "\n</svg>\n")


def _text(x: float, y: float, s: str, *, size: int = 13,
          anchor: str = "start") -> str:
    return (f'<text x="{x}" y="{y}" font-size="{size}" '
            f'text-anchor="{anchor}">{s}</text>')


def _discrete_animate(values: str, key_times: str, *,
                      begin: str | None = None, attr: str = "width") -> str:
    b = f' begin="{begin}"' if begin is not None else ""
    return (f'<animate attributeName="{attr}" calcMode="discrete" '
            f'values="{values}" keyTimes="{key_times}" dur="1.000000s" '
            f'repeatCount="1"{b}/>')


# ─── verify_svg_structure ─────────────────────────────────────────────────────

def test_structure_ok_minimal_has_no_issues():
    issues = verify_svg_structure(_svg("<rect x='0' y='0' width='4' "
                                       "height='4'/>"))
    assert issues == ()


def test_structure_malformed_xml_single_error():
    issues = verify_svg_structure("<svg><unclosed></svg>")
    assert len(issues) == 1
    assert issues[0].level == "error"
    assert issues[0].kind == "structure"
    assert issues[0].locator == "root"


def test_structure_root_not_svg_rejected():
    issues = verify_svg_structure(_svg_body_wrapped_in_g())
    assert issues[0].level == "error"
    assert "svg" in issues[0].message


def _svg_body_wrapped_in_g() -> str:
    return ('<?xml version="1.0"?>\n<g xmlns="http://www.w3.org/2000/svg">'
            "</g>\n")


def test_structure_missing_viewbox_rejected():
    svg = ('<?xml version="1.0"?>\n'
           '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
           "</svg>\n")
    issues = verify_svg_structure(svg)
    assert any(i.kind == "structure" and "viewBox" in i.message
               for i in issues)
    assert all(i.level == "error" for i in issues)


def test_structure_width_height_viewbox_mismatch_rejected():
    issues = verify_svg_structure(_svg("", w=400, h=300, viewBox="0 0 800 600"))
    assert any("不一致" in i.message for i in issues)
    assert all(i.level == "error" for i in issues)


def test_structure_expected_canvas_mismatch_rejected():
    issues = verify_svg_structure(_svg(""), expected_canvas_wh=(800, 600))
    assert any("spec 画幅" in i.message for i in issues)


def test_structure_expected_canvas_match_clean():
    assert verify_svg_structure(_svg(""), expected_canvas_wh=(400, 300)) == ()


# ─── detect_text_overlap ──────────────────────────────────────────────────────

def test_text_overlap_negative_distant_texts_clean():
    svg = _svg(_text(10, 100, "AAAAAAAAAA") + _text(200, 250, "BBBBBBBBBB"))
    assert detect_text_overlap(svg) == ()


def test_text_overlap_positive_reports_warn_with_pair_locator():
    # 13px 字号×10 字符×0.62≈80.6px 宽：x=10 与 x=50 同行必重叠（估算口径）
    svg = _svg(_text(10, 100, "AAAAAAAAAA") + _text(50, 100, "BBBBBBBBBB"))
    issues = detect_text_overlap(svg)
    assert len(issues) == 1
    assert issues[0].level == "warn"
    assert issues[0].kind == "text_overlap"
    assert "text[0]×text[1]" in issues[0].locator
    assert "AAAAAAAAAA" in issues[0].message and "BBBBBBBBBB" in issues[0].message


def test_text_overlap_anchor_aware_box_shift():
    # middle 锚点=中心对齐：x=100 与 x=120 各 10 字符（半宽≈40.3）→ 盒重叠
    mid = _svg(_text(100, 100, "AAAAAAAAAA", anchor="middle")
               + _text(120, 100, "BBBBBBBBBB", anchor="middle"))
    assert any(i.kind == "text_overlap" for i in detect_text_overlap(mid))
    # end 锚点=右对齐：右端 100 与 start 左端 200 相距远 → 不重叠
    far = _svg(_text(100, 100, "AAAAAAAAAA", anchor="end")
               + _text(200, 100, "BBBBBBBBBB"))
    assert detect_text_overlap(far) == ()


def test_text_out_of_bounds_reports_warn():
    svg = _svg(_text(380, 290, "AAAAAAAAAAAAAAAAAAAA"))  # 右下越界
    issues = detect_text_overlap(svg)
    assert any(i.kind == "text_out_of_bounds" and i.level == "warn"
               for i in issues)


def test_text_out_of_bounds_uses_viewbox_when_canvas_omitted():
    svg = _svg(_text(380, 290, "AAAAAAAAAAAAAAAAAAAA"), w=400, h=300,
               viewBox="0 0 400 300")
    assert any(i.kind == "text_out_of_bounds"
               for i in detect_text_overlap(svg))  # 无 canvas_wh 亦可判


# ─── rotate 文本盒识别（Q-R3R 排版修复配套钉） ────────────────────────────────

def _rtext(x: float, y: float, s: str, *, size: int = 13,
           transform: str | None = "rotate(-90 {x} {y})") -> str:
    """rotate 文本 fixture（transform 缺省=内核 ylabel 同款绕自身锚点 −90°）。"""
    tf = transform.format(x=x, y=y) if transform is not None else ""
    tattr = f' transform="{tf}"' if tf else ""
    return (f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="middle"'
            f'{tattr}>{s}</text>')


def test_rotated_ylabel_long_text_in_bounds_clean():
    # 修复缺陷同款形态：16 字符 middle 文本横排盒 [-33.7, 65.7] 越出左缘+压
    # tick 列；绕自身锚点 rotate(-90) 后盒宽=字号量级 [6.6, 19.6]、恒在画幅内
    rot = _svg(_rtext(16, 150, "cost (best-so-far)"), w=400, h=300)
    assert detect_text_overlap(rot) == ()
    # 负例对照：同位置同文本不旋转 → 横排盒越界 warn（检测器未被钝化的证据）
    raw = _svg(_rtext(16, 150, "cost (best-so-far)", transform=None), w=400, h=300)
    kinds = {i.kind for i in detect_text_overlap(raw)}
    assert "text_out_of_bounds" in kinds


def test_rotated_ylabel_no_overlap_with_tick_column():
    # y-tick（end 锚右缘 56 同款位）与旋转 ylabel 竖排盒 x∈[6.6,19.6] 脱接；
    # 不旋转则横排盒左伸入 tick 盒 → 重叠 warn
    tick = _text(56, 150, "-10", anchor="end")
    rot = _svg(tick + _rtext(16, 150, "|S| (dB)"), w=400, h=300)
    assert detect_text_overlap(rot) == ()
    raw = _svg(tick + _rtext(16, 150, "|S| (dB)", transform=None), w=400, h=300)
    assert any(i.kind == "text_overlap" for i in detect_text_overlap(raw))


def test_rotated_text_overlap_still_detected_when_true():
    # 旋转盒识别不豁免真挤压：两条同 x 竖排长文本（y 中心同点）盒必交
    svg = _svg(_rtext(16, 150, "AAAAAAAAAAAAAAAA") + _rtext(17, 150,
                                                            "BBBBBBBBBBBBBBBB"))
    issues = detect_text_overlap(svg)
    assert any(i.kind == "text_overlap" and i.level == "warn" for i in issues)


def test_rotated_text_out_of_bounds_vertical_still_detected():
    # 超长旋转文本纵向越出画幅 → 竖向越界 warn 仍在（旋转只改盒方向，
    # 不豁免真越界）
    svg = _svg(_rtext(16, 150, "A" * 80), w=400, h=300)
    assert any(i.kind == "text_out_of_bounds" for i in detect_text_overlap(svg))


def test_unparsable_transform_falls_back_to_unrotated_box():
    # 不可解析 transform（复合 transform 链）→ 未旋转盒保守回退（宁多报
    # 不放过，#316 同向）：横排盒越界 warn 保持
    svg = _svg(_rtext(16, 150, "cost (best-so-far)",
                      transform="translate(5) rotate(-90 16 150)"), w=400, h=300)
    assert any(i.kind == "text_out_of_bounds" for i in detect_text_overlap(svg))


def test_cartesian_axes_ylabel_emitted_rotated_and_selfcheck_clean(tmp_path):
    # 内核产出面：cartesian_axes ylabel 带 rotate(-90 x y)（绕自身锚点）；
    # 真渲染（sparam_evolution 缺省 fixture）self_check 全净（见
    # test_render_animation_self_check_attaches_report_and_subtype 终态钉）
    import re as _re

    from rfauto.service.animation.renderers.base import PlotBox, cartesian_axes
    box = PlotBox.from_canvas(960, 540)
    axes = cartesian_axes(box, [0.0, 1.0], [0.0, 1.0], xlabel="freq_hz",
                          ylabel="|S| (dB)", font_size=13,
                          x_domain=(0.0, 1.0), y_domain=(0.0, 1.0))
    m = _re.search(
        r'<text x="16" y="([\d.]+)" font-size="13" fill="#333333" '
        r'text-anchor="middle" font-weight="normal" '
        r'transform="rotate\(-90 16 [\d.]+\)">\|S\| \(dB\)</text>', axes)
    assert m is not None, axes
    # 旋转盒估算在画幅内（y=box 中点、盒宽=字号量级）
    report = run_animation_self_check(_svg(axes, w=960, h=540), canvas_wh=(960, 540))
    assert report.ok and report.n_warnings == 0


# ─── detect_frame_order ───────────────────────────────────────────────────────

_DESC3 = "rfauto animation chart_type=demo frame_count=3 duration_s=0.375000"


def test_frame_order_ok_discrete_chain_clean():
    body = (f"<desc>{_DESC3}</desc>"
            + _discrete_animate("0;10;20", "0;0.333333;0.666667"))
    assert detect_frame_order(_svg(body), expected_frames=3) == ()


def test_frame_order_keytimes_non_monotone_error():
    body = _discrete_animate("0;10;20", "0;0.666667;0.333333")
    issues = detect_frame_order(_svg(body))
    assert any(i.kind == "frame_order" and "非单调" in i.message
               and i.level == "error" for i in issues)


def test_frame_order_keytimes_count_mismatch_error():
    body = _discrete_animate("0;10;20", "0;0.5")
    issues = detect_frame_order(_svg(body))
    assert any(i.kind == "frame_keytimes_mismatch" for i in issues)


def test_frame_order_keytimes_first_not_zero_error():
    body = _discrete_animate("0;10", "0.5;1.0")
    issues = detect_frame_order(_svg(body))
    assert any("首值" in i.message and i.kind == "frame_order"
               for i in issues)


def test_frame_order_keytimes_out_of_range_error():
    body = _discrete_animate("0;10", "0;1.5")
    issues = detect_frame_order(_svg(body))
    assert any("越界" in i.message for i in issues)


def test_frame_order_begin_chain_monotone_ok_vs_violation():
    # 同父双 animate begin 升序=合法插值链（filter_morphing 同构）
    ok = _svg(_discrete_animate("1;2", "0;0.5", begin="0.125000s")
              + _discrete_animate("2;3", "0;0.5", begin="0.250000s"))
    assert detect_frame_order(ok) == ()
    # 同父 begin 降序=帧序倒退
    bad = _svg(_discrete_animate("1;2", "0;0.5", begin="0.250000s")
               + _discrete_animate("2;3", "0;0.5", begin="0.125000s"))
    issues = detect_frame_order(bad)
    assert any(i.kind == "frame_order" and "begin 链非单调" in i.message
               for i in issues)


def test_frame_order_begin_chain_per_parent_not_global():
    # filter_morphing 形态：两条独立插值链（不同父）各自升序，跨链文档序
    # 不单调=设计内（探针实测口径）——不报
    body = ('<g><rect width="1" height="1">'
            + _discrete_animate("1;2", "0;0.5", begin="0.500000s")
            + "</rect></g>"
            '<g><rect width="1" height="1">'
            + _discrete_animate("1;2", "0;0.5", begin="0.125000s")
            + "</rect></g>")
    assert detect_frame_order(body and _svg(body)) == ()


def test_frame_order_expected_frames_mismatch_error():
    body = f"<desc>{_DESC3}</desc>"
    issues = detect_frame_order(_svg(body), expected_frames=5)
    assert any(i.kind == "frame_count" and i.level == "error"
               and "3" in i.message and "5" in i.message for i in issues)


def test_frame_order_missing_desc_warns_not_errors():
    issues = detect_frame_order(_svg(""), expected_frames=3)
    assert any(i.kind == "frame_count" and i.level == "warn"
               for i in issues)
    assert not any(i.level == "error" for i in issues)


def test_frame_order_unparseable_begin_error():
    body = _discrete_animate("1;2", "0;0.5", begin="indefinite")
    issues = detect_frame_order(_svg(body))
    assert any(i.kind == "frame_begin_parse" for i in issues)


# ─── run_animation_self_check + AnimationSelfCheckReport ─────────────────────

def test_report_issue_order_structure_frame_text_and_fields():
    # 结构坏 + 帧序坏 + 文字挤压三问题并存：issue 序固定 structure→frame→text
    bad = _svg(_text(10, 100, "AAAAAAAAAA") + _text(50, 100, "BBBBBBBBBB"),
               viewBox="0 0 400 300")[:-len("</svg>\n")]  # 吞闭标签=XML 坏
    bad += "</g>\n"  # 错误闭标签（仍是坏 XML）
    report = run_animation_self_check(bad)
    assert report.issues, "坏输入必须出 issue"
    assert report.issues[0].kind == "structure"  # 解析失败=单结构 error
    assert report.n_errors >= 1 and report.ok is False


def test_report_to_dict_json_serializable_shape():
    svg = _svg(_text(10, 100, "AAAAAAAAAA") + _text(50, 100, "BBBBBBBBBB"))
    report = run_animation_self_check(svg)
    d = report.to_dict()
    assert set(d) == {"ok", "n_errors", "n_warnings", "issues"}
    assert set(d["issues"][0]) == {"level", "kind", "locator", "message"}
    assert json.loads(json.dumps(d)) == d
    assert d["ok"] is True and d["n_errors"] == 0
    assert d["n_warnings"] == len(d["issues"])


def test_report_ok_means_zero_errors_warns_allowed():
    svg = _svg(_text(380, 290, "AAAAAAAAAAAAAAAAAAAA"))
    report = run_animation_self_check(svg)
    assert report.ok is True  # warn 级不拦路
    assert report.n_warnings >= 1


# ─── render_animation 接线（缺省零变化钉） ────────────────────────────────────

def _spec(tmp_path, **overrides):
    csv = fx.make_sparams_csv(tmp_path)
    spec = {"chart_type": "sparam_evolution",
            "source": {"kind": "sparams_csv", "path": str(csv)}}
    spec.update(overrides)
    return spec


def test_render_animation_default_has_no_self_check_attribute(tmp_path):
    result = render_animation(_spec(tmp_path))
    assert isinstance(result, AnimationResult)
    assert not isinstance(result, AnimationSelfCheckedResult)
    with pytest.raises(AttributeError):
        _ = result.self_check  # 缺省路径无该字段（零变化钉）


def test_render_animation_self_check_true_svg_byte_identical(tmp_path):
    spec = _spec(tmp_path)
    plain = render_animation(spec)
    checked = render_animation(spec, self_check=True)
    assert plain.svg_str == checked.svg_str  # 开关不影响输出（逐字节）
    assert plain.sha256 == checked.sha256


def test_render_animation_self_check_attaches_report_and_subtype(tmp_path):
    # 预声明例外（Q-R3R 排版修复席）：修复前本钉=「真渲染含 ylabel 边缘
    # warn（诚实检出）」（n_warnings>=1 + text_out_of_bounds 存在）——该 warn
    # 是内核直角坐标 ylabel 横排既有排版缺陷的诚实检出（qw41 ex1/ex2 证据
    # runs/aurora_q/qw41_examples/*/selfcheck.json）。修复=cartesian_axes
    # ylabel 绕锚点 rotate(-90) 竖排+检测器 rotate 盒识别（base.py），修复后
    # 缺省渲染三检测器**全净**——本钉改钉「缺陷已修」终态（==0 强于旧
    # >=1 不属放松）；缺陷形态的诚实检出能力由
    # test_text_out_of_bounds_reports_warn / test_text_overlap_* 负例钉保障。
    checked = render_animation(_spec(tmp_path), self_check=True)
    assert isinstance(checked, AnimationSelfCheckedResult)
    assert isinstance(checked, AnimationResult)  # isinstance 链成立
    report = checked.self_check
    assert isinstance(report, AnimationSelfCheckReport)
    assert report.ok is True and report.n_errors == 0
    assert report.n_warnings == 0  # 排版修复后：ylabel 越界/重叠 warn 根治
    assert not any(i.kind == "text_out_of_bounds" for i in report.issues)


def test_render_animation_self_check_desc_frames_match_plan(tmp_path):
    checked = render_animation(_spec(tmp_path), self_check=True)
    # 帧数契约：desc 声明=plan 值（接线传参核对路径零红）
    assert checked.frame_count == 3
    assert not any(i.kind == "frame_count" for i in checked.self_check.issues)

"""C6/C7 过渡几何修正 followUp 单测（2026-09-21）。

C6：msl_slot_transition/marchand_balun 开路支节 Δl 符号修正——物理长=
λg/4−Δl（开路端边缘场使电长比物理长长 Δl，电长取 λg/4；Pozar
《Microwave Engineering》eq.4.23 口径，与仓内 _open_end_delta_mm 消费者
"物理长=电长−Δl" 同口径；旧 +Δl 系符号反，历史观察项收口）。
钉：符号公式、设计点数值、f0 电路级往返（开路端模型下新符号残抗→0、
旧符号 +j·Z0·tan(2βΔl)≈+j5.54Ω 感性残差）、自谐振方向（旧符号 −6.57%）、
渲染链单源（design→layout→render 同值）。

C7：gysel `_jog_miter_mm` mitered-jog 切角旋钮（排空五轮 followUps
"gysel 弯折等效长度/mitered-jog"）——缺省 0=未切角基线渲染逐字节不变
（缓存/锁定测试零波及）；c>0 每侧 jog 转角外上角 c×c 台阶缺口（45° 切角
的阶梯网格单步近似），金属并集=原 jog 段减两缺口、竖直段/桥带不动；
守卫 0≤c<W_F；缺口缘精确入网（#198）。
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

C0 = 299792458.0
F0 = 2.5
H, ER, TAND, W_SLOT = 1.524, 3.66, 0.0037, 1.0
BAND = (2.25, 2.75)
GYS_NOM = {"w_arm_mm": 0.6035, "w_feed_mm": 1.1134,
           "arm_len_mm": 18.162, "iso_len_mm": 17.75}


class TestC6OpenStubSign:
    """开路支节 Δl 符号：物理长=λg/4−Δl（电长 λg/4）。"""

    def test_sign_convention_and_design_value(self):
        from rfauto.core.slotline_transitions import (
            microstrip_open_end_delta_l_mm,
            transition_design,
        )

        d = transition_design(F0, H, ER, W_SLOT, TAND)
        lam_g = C0 / (F0 * 1e9) / math.sqrt(d.eps_eff_msl) * 1e3
        lam_q = lam_g / 4.0
        # 物理长 = λg/4 − Δl（旧 +Δl 符号已修正；#325 钉更新语义）
        assert d.l_stub_mm == pytest.approx(lam_q - d.dl_open_mm, abs=1e-9)
        assert d.l_stub_mm < lam_q
        assert d.dl_open_mm == pytest.approx(
            microstrip_open_end_delta_l_mm(d.w_msl_mm, H, d.eps_eff_msl))
        # 设计点数值锚：Δl=0.6236、λg/4=17.7489 → 17.1253（旧 +Δl=18.3725）
        assert d.dl_open_mm == pytest.approx(0.6236, abs=5e-4)
        assert d.l_stub_mm == pytest.approx(17.1253, abs=5e-4)

    def test_marchand_shares_corrected_stub(self):
        from rfauto.core.slotline_transitions import marchand_design

        m = marchand_design(F0, H, ER, W_SLOT, TAND)
        assert m.l_stub_mm == pytest.approx(17.1253, abs=5e-4)

    def test_f0_circuit_roundtrip_open_end_model(self):
        """电路级往返：Zin=−jZ0·cot(β(l_phys+Δl))，开路端等效延长计入口径。

        新符号（l=λg/4−Δl）：β(l+Δl)=π/2 → 虚短路精确（|Zin|→浮点 0）；
        旧符号（l=λg/4+Δl）：β(l+Δl)=π/2+2βΔl → +jZ0·tan(2βΔl)≈+j5.54Ω
        （感性残差，两倍 Δl 过冲——修正方向与量级的闭式证据）。
        """
        from rfauto.core.slotline_transitions import transition_design

        d = transition_design(F0, H, ER, W_SLOT, TAND)
        lam_q = d.l_stub_mm + d.dl_open_mm            # λg/4（新符号自洽）
        beta = 2.0 * math.pi / (4.0 * lam_q)          # rad/mm

        def zin_stub(l_phys_mm: float) -> complex:
            return complex(0.0, -50.0 / math.tan(beta * l_phys_mm))

        z_new = zin_stub(d.l_stub_mm + d.dl_open_mm)  # = cot(β·λg/4)
        assert abs(z_new) < 1e-6
        # 旧符号：物理长 λg/4+Δl，加开路端等效延长 → 电长 λg/4+2Δl
        z_old = zin_stub(lam_q + 2.0 * d.dl_open_mm)
        assert z_old.imag == pytest.approx(
            50.0 * math.tan(2.0 * beta * d.dl_open_mm), rel=1e-9)
        assert z_old.imag > 0.0                       # 感性
        assert z_old.imag == pytest.approx(5.5417, abs=2e-3)

    def test_stub_self_resonance_shift_direction(self):
        """自谐振方向：旧符号支节在 f0 下方谐振（−6.57%），新符号对齐 f0。"""
        from rfauto.core.slotline_transitions import transition_design

        d = transition_design(F0, H, ER, W_SLOT, TAND)
        lam_q = d.l_stub_mm + d.dl_open_mm
        # 电长 λg/4 的支节恰在 f0 谐振（β(f0)·(l+Δl)=π/2）
        beta_f0 = 2.0 * math.pi / (4.0 * lam_q)
        assert beta_f0 * (d.l_stub_mm + d.dl_open_mm) == pytest.approx(
            math.pi / 2.0, rel=1e-12)
        # 旧符号反证：l_old=λg/4+Δl → 谐振点 f_res=f0·λg/4/(λg/4+2Δl)
        f_res_old = F0 * lam_q / (lam_q + 2.0 * d.dl_open_mm)
        assert f_res_old == pytest.approx(2.33586, abs=2e-5)
        assert (f_res_old / F0 - 1.0) == pytest.approx(-0.06566, abs=2e-5)

    def test_render_layout_single_source_value(self):
        """渲染链单源：layout/渲染脚本 Y_TIP 与修正后 design 同值（米）。"""
        from rfauto.adapters.openems_templates import render_script
        from rfauto.adapters.slotline_transitions_template import (
            msl_slot_transition_layout,
        )
        from rfauto.core.slotline_transitions import transition_design

        d = transition_design(F0, H, ER, W_SLOT, TAND)
        lay = msl_slot_transition_layout({}, BAND)
        assert lay.l_stub_m == pytest.approx(d.l_stub_mm * 1e-3, rel=1e-12)
        assert lay.y_stub_tip_m == pytest.approx(
            (W_SLOT / 2 + d.l_stub_mm) * 1e-3, rel=1e-12)
        text = render_script("msl_slot_transition", {}, BAND,
                             substrate={"h_mm": H, "er": ER, "tan_d": TAND})
        m_ytip = re.search(r"^Y_TIP = ([0-9.eE+-]+)", text, re.M)
        assert m_ytip is not None
        assert float(m_ytip.group(1)) == pytest.approx(lay.y_stub_tip_m)


class TestC7GyselJogMiter:
    """gysel `_jog_miter_mm` mitered-jog 切角旋钮（opt-in，缺省 0）。"""

    def _jog_boxes(self, text: str) -> list[tuple[float, float, float, float]]:
        """切角档渲染文本中的具体数字 jog 盒（其余盒为符号式，跳过）。"""
        boxes = []
        for m in re.finditer(r"gysel\.AddBox\(\(([^)]+)\),\s*\n\s*\(([^)]+)\),",
                             text):
            try:
                x0, y0 = (float(v) for v in m.group(1).split(",")[:2])
                x1, y1 = (float(v) for v in m.group(2).split(",")[:2])
            except ValueError:
                continue
            boxes.append((x0, y0, x1, y1))
        return boxes

    def _union_len(self, ivs: list[tuple[float, float]]) -> float:
        ivs = sorted(ivs)
        total, lo, hi = 0.0, ivs[0][0], ivs[0][1]
        for a, b in ivs[1:]:
            if a > hi:
                total += hi - lo
                lo, hi = a, b
            else:
                hi = max(hi, b)
        return total + hi - lo

    def test_default_render_byte_invariant(self):
        from rfauto.adapters.openems_templates import render_script

        t_absent = render_script("gysel", dict(GYS_NOM), BAND)
        t_zero = render_script("gysel", dict(GYS_NOM, _jog_miter_mm=0.0), BAND)
        assert t_absent == t_zero                       # 缺省=显式 0 逐字节一致
        assert t_absent.count("gysel.AddBox") == 6      # 未切角基线 6 盒
        assert "min(-XA, -XB) - W_F / 2" in t_absent    # 原始符号式 jog 盒
        assert "_jog_miter_mm" not in t_absent          # 渲染零旋钮痕迹
        from rfauto.adapters.openems_templates import _gysel_layout
        assert _gysel_layout(dict(GYS_NOM))["miter"] == 0.0

    def test_miter_notch_geometry_inward(self):
        """内移档（nominal）：转角外上角 c×c 缺口；带并集=原 jog 减两缺口。

        2026-09-21 C7 A/B 审计重钉：渲染盒坐标=米（脚本主体同单位；初版
        mm 字面量直排越域 1000×，exec 金属原语实测抓出）。
        """
        from rfauto.adapters.openems_templates import _gysel_layout, render_script

        c, wf, yj = 0.4e-3, GYS_NOM["w_feed_mm"] * 1e-3, 17.338e-3
        lay = _gysel_layout(dict(GYS_NOM, _jog_miter_mm=0.4))
        assert lay["miter"] == 0.4
        text = render_script("gysel", dict(GYS_NOM, _jog_miter_mm=0.4), BAND)
        compile(text, "gen", "exec")
        assert text.count("gysel.AddBox") == 8          # 6 盒 + 每侧 jog 拆 +1
        boxes = self._jog_boxes(text)
        assert len(boxes) == 4                          # 两侧 jog 主段+缺口段
        lo_full = (min(GYS_NOM["arm_len_mm"], GYS_NOM["iso_len_mm"])
                   - GYS_NOM["w_feed_mm"] / 2) * 1e-3
        hi_full = (max(GYS_NOM["arm_len_mm"], GYS_NOM["iso_len_mm"])
                   + GYS_NOM["w_feed_mm"] / 2) * 1e-3
        # 缺口以下带（全高覆盖区）：x 并集=两侧 jog 全 span（线宽不变）
        band_lo = self._union_len([(b[0], b[2]) for b in boxes
                                   if b[1] <= yj - wf / 2 + 1e-9
                                   and b[3] >= yj + wf / 2 - c - 1e-9])
        assert band_lo == pytest.approx(2.0 * (hi_full - lo_full), abs=1e-9)
        # 顶带（缺口带）：x 并集=全 span−2c（两侧各削 c）
        band_top = self._union_len([(b[0], b[2]) for b in boxes
                                    if b[1] <= yj + wf / 2 - c + 1e-9
                                    and b[3] >= yj + wf / 2 - 1e-9])
        assert band_top == pytest.approx(2.0 * (hi_full - lo_full - c),
                                         abs=1e-9)
        # 缺口贴齐竖直段外缘（内移档：与 XA+W_F/2 齐平端）
        flush = GYS_NOM["arm_len_mm"] * 1e-3 + wf / 2
        for x0, _y0, x1, _y1 in boxes:
            if abs(x1 - flush) < 1e-9:                  # 右侧缺口段
                assert abs(x0 - (flush - c)) < 1e-9
                assert abs(_y1 - (yj + wf / 2 - c)) < 1e-9

    def test_miter_notch_geometry_outward(self):
        """外移档（arm_len<iso_len）：缺口翻到与竖直段内缘齐平端。"""
        from rfauto.adapters.openems_templates import render_script

        c = 0.4e-3
        text = render_script("gysel", dict(GYS_NOM, arm_len_mm=17.0,
                                           _jog_miter_mm=0.4), BAND)
        compile(text, "gen", "exec")
        flush = (17.0 - GYS_NOM["w_feed_mm"] / 2) * 1e-3   # 内缘齐平端（米）
        boxes = [b for b in self._jog_boxes(text)
                 if abs(b[0] - flush) < 1e-9 or abs(b[1 + 2] - flush) < 1e-9]
        assert boxes                                    # 缺口段贴内缘端存在
        # 右侧缺口段：x∈[flush, flush+c]、降高 y1=yj+W_F/2−c
        right = [b for b in boxes if b[0] > 0]
        assert any(abs(b[2] - (flush + c)) < 1e-9 and b[0] == pytest.approx(flush)
                   for b in right)

    def test_near_points_notch_edges_and_default_identity(self):
        from rfauto.adapters.openems_templates import _near_points

        nx0, ny0 = _near_points("gysel", dict(GYS_NOM))
        nxz, nyz = _near_points("gysel", dict(GYS_NOM, _jog_miter_mm=0.0))
        nx1, ny1 = _near_points("gysel", dict(GYS_NOM, _jog_miter_mm=0.4))
        # 缺省与显式 0：近点集一致（逐字节不变性的近点面）
        assert (sorted(nx0), sorted(ny0)) == (sorted(nxz), sorted(nyz))
        # 旋钮开：新增两侧缺口缘 x=±(XA+W_F/2−c) 与缺口顶缘 y=YJ+W_F/2−c
        c, wf, yj = 0.4, GYS_NOM["w_feed_mm"], 17.338
        edge = GYS_NOM["arm_len_mm"] + wf / 2 - c
        assert min(abs(v - edge * 1e-3) for v in nx1) < 1e-12
        assert min(abs(v - (-(edge)) * 1e-3) for v in nx1) < 1e-12
        assert min(abs(v - (yj + wf / 2 - c) * 1e-3) for v in ny1) < 1e-12

    def test_guard_rejects_out_of_domain(self):
        from rfauto.adapters.openems_templates import _gysel_layout

        with pytest.raises(ValueError, match="_jog_miter_mm"):
            _gysel_layout(dict(GYS_NOM, _jog_miter_mm=-0.1))
        with pytest.raises(ValueError, match="_jog_miter_mm"):
            _gysel_layout(dict(GYS_NOM, _jog_miter_mm=GYS_NOM["w_feed_mm"]))
        with pytest.raises(ValueError, match="_jog_miter_mm"):
            _gysel_layout(dict(GYS_NOM, _jog_miter_mm=float("nan")))

    def test_meta_documents_knob(self):
        from rfauto.adapters.openems_templates import TEMPLATE_META

        topo = TEMPLATE_META["gysel"]["topology"]
        assert "_jog_miter_mm" in topo and "mitered-jog" in topo
        # 旋钮不入参数表（schema/缓存零波及，#304 消费者面不变）
        assert "_jog_miter_mm" not in TEMPLATE_META["gysel"]["params"]

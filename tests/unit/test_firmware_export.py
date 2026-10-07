"""PT-6 固件工件三出口锚树（规格书 规格深案 §B-6）。

裁判口径（#118，独立来源/独立路径不自证）：
- ①波束：已知相位码字回代相位误差 ≤量化步/2（取整性质）；码字回代 ΔGain
  （error-only 相干因子 |Σe^{jε}|²/N²，独立实现在本测试内联重算）落
  quantization_loss_db 公式带 ±0.2dB（规格原文判据）；CSV 列序逐位+
  C 头语法断言（stdint/static const/括号平衡/code 数组正则解析回读逐位）；
- ②varactor：链路恒等式逐行对拍（独立调用 varactor_load_capacitance_pf /
  bias_for_capacitance_v——与内核同源闭式但独立调用路径）；单调性审计恒
  真例+饱和例（v_ref=10V/bw=6 时 V=19.9V 满量程溢出，码序列 [6,16,33,63,63]
  预声明钉）；乱序/窗外/正偏域显式拒绝；
- ③DPD：合成系数（ILA 综合回收，固定种子）定点回代 NMSE 门内（Q16.12
  实测 −67dB）+溢出告警触发例（Q6.3 字域超限钳位+verdict FAIL）+恒等
  零误差例（1.0 精确可表示 → NMSE=−inf、级联零劣化）；
- CLI：CliRunner 驱动真实入口（test_manufacturing_stats 同款），注册面+
  三命令 happy path/坏载荷退出码。
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import firmware_export as fe
from rfauto.core.dpd_static import MemoryPolyModel, apply_memory_polynomial, synthesize_dpd_postinverse
from rfauto.core.metasurface_lut import quantization_loss_db, quantize_phase_deg
from rfauto.core.varactor import bias_for_capacitance_v, loaded_line_f0_limits_ghz, varactor_load_capacitance_pf

# varactor 表锚参数（预探 runs/pt6 实测窗 (2.650, 5.300)GHz，cj0=2pF 可行域
# f≥3.53GHz；f=4.4GHz → V=19.9V 供饱和例）
_VAR_KW = dict(line_len_mm=20.0, z0_ohm=50.0, ereff=2.0,
               cj0_pf=2.0, phi_v=0.9)
_F_ASC = [3.6, 3.8, 4.0, 4.2, 4.4]


def _beam_rows(n: int, bits: int, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    return fe.beam_codeword_table(
        list(range(n)), rng.uniform(-50.0, 50.0, n), rng.uniform(-50.0, 50.0, n),
        rng.uniform(0.0, 360.0, n), bits=bits)


# ════════════════════════════ ① 波束码字表 ══════════════════════════════════


class TestBeamCodewordTable:
    """PT-6① 波束码字表：量化单源/回代相位误差/CSV 列序/C 头语法。"""

    @pytest.mark.parametrize("bits", [2, 3, 4])
    def test_phase_roundtrip_within_half_step(self, bits):
        # 锚：已知相位码字回代相位误差 ≤量化步/2（规格 §B-6①锚树原文）
        n = 512
        table = _beam_rows(n, bits)
        step = 360.0 / (2 ** bits)
        assert table["quant_step_deg"] == step
        for row in table["rows"]:
            err = abs((row["phase_target_deg"] - row["phase_quant_deg"]
                       + 180.0) % 360.0 - 180.0)
            assert err <= step / 2.0 + 1e-9
            # 规范域 + 与内核 quantize_phase_deg mod 360 逐点相等（单源对拍）
            assert 0.0 <= row["phase_quant_deg"] < 360.0
            q = quantize_phase_deg(row["phase_target_deg"], bits)
            assert abs((row["phase_quant_deg"] - q + 180.0) % 360.0 - 180.0) \
                <= 1e-9
            assert 0 <= row["code_word"] < 2 ** bits
            assert row["phase_quant_deg"] == pytest.approx(
                row["code_word"] * step, abs=1e-9)

    def test_columns_exact(self):
        table = _beam_rows(8, 2)
        assert table["columns"] == [
            "element_id", "x_mm", "y_mm", "u0", "phase_target_deg",
            "phase_quant_deg", "code_word", "bits", "quant_loss_db",
            "temp_comp_channel",
        ]
        assert fe.beam_table_csv(table).splitlines()[0].split(",") \
            == table["columns"]

    def test_quant_loss_column_equals_kernel_formula(self):
        table = _beam_rows(8, 3)
        expect = quantization_loss_db(3)
        for row in table["rows"]:
            assert row["quant_loss_db"] == expect  # 逐位（同源闭式）
        assert table["quant_loss_db"] == expect

    def test_backsub_audit_gain_in_formula_band(self):
        # 锚（规格原文判据）：码字回代 ΔGain 落 quantization_loss_db 带 ±0.2dB。
        # ΔGain=error-only 相干因子，本测试内联独立重算（不调 audit 的实现）。
        for bits, n in ((1, 4096), (2, 4096), (3, 1024)):
            table = _beam_rows(n, bits)
            eps = np.array([
                (r["phase_target_deg"] - r["phase_quant_deg"] + 180.0) % 360.0
                - 180.0 for r in table["rows"]])
            realized = 10.0 * math.log10(
                abs(np.sum(np.exp(1j * np.deg2rad(eps)))) ** 2 / n ** 2)
            formula = -quantization_loss_db(bits)
            assert abs(realized - formula) <= 0.2, (bits, n, realized, formula)
            audit = fe.beam_backsub_audit(table)
            assert audit["verdict"] == "PASS"
            assert audit["phase_ok"] is True
            assert audit["gain_loss_db"] == pytest.approx(realized, abs=1e-12)
            assert audit["formula_loss_db"] == formula

    def test_backsub_audit_fails_small_aligned_array(self):
        # 负锚：4 元全对准（0° 目标恰在码栅格上）→ 零量化误差 → 实得 ΔGain=0
        # 与公式 0.912dB 差 0.91 > 0.2 → FAIL（门会咬人，非恒绿装饰）
        table = fe.beam_codeword_table(
            [0, 1, 2, 3], [-15.0, -5.0, 5.0, 15.0], [0, 0, 0, 0],
            [0.0, 0.0, 0.0, 0.0], bits=2)
        audit = fe.beam_backsub_audit(table)
        assert audit["verdict"] == "FAIL"
        assert audit["max_phase_err_deg"] == pytest.approx(0.0, abs=1e-12)
        assert audit["delta_db"] == pytest.approx(
            quantization_loss_db(2), abs=1e-12)

    def test_temp_comp_channels_assignment(self):
        rng = np.random.default_rng(3)
        t4 = fe.beam_codeword_table(
            list(range(10)), rng.uniform(-9, 9, 10), rng.uniform(-9, 9, 10),
            rng.uniform(0, 360, 10), bits=2, temp_comp_channels=4)
        assert [r["temp_comp_channel"] for r in t4["rows"]] \
            == [k % 4 for k in range(10)]
        t1 = fe.beam_codeword_table(
            list(range(3)), [0, 1, 2], [0, 0, 0], [10, 20, 30], bits=2,
            temp_comp_channels=1)
        assert {r["temp_comp_channel"] for r in t1["rows"]} == {0}

    def test_u0_taper_declared_in_notes(self):
        table = fe.beam_codeword_table(
            [0, 1, 2, 3], [0, 1, 2, 3], [0, 0, 0, 0],
            [11.0, 100.0, 200.0, 305.0], bits=2, u0=[1.0, 1.0, 0.3, 0.3])
        audit = fe.beam_backsub_audit(table)
        assert any("锥削" in note for note in audit["notes"])

    def test_csv_roundtrip(self):
        table = _beam_rows(16, 2)
        text = fe.beam_table_csv(table)
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        assert header == table["columns"]
        for row_dict, parsed in zip(table["rows"], reader, strict=True):
            assert int(parsed[0]) == row_dict["element_id"]
            assert float(parsed[1]) == row_dict["x_mm"]
            assert float(parsed[5]) == row_dict["phase_quant_deg"]
            assert int(parsed[6]) == row_dict["code_word"]
            assert float(parsed[8]) == row_dict["quant_loss_db"]
            assert int(parsed[9]) == row_dict["temp_comp_channel"]

    def test_c_header_syntax_and_code_array_parseback(self):
        # C 头语法断言：stdint include、4 个 const 数组、宏定义、括号平衡、
        # code_word 数组正则解析回读逐位等于表行（文本层独立裁判）
        table = _beam_rows(12, 3)
        text = fe.beam_table_c_header(table, array_name="fw_beam")
        assert "#include <stdint.h>" in text
        assert "#define FW_BEAM_N_ELEMENTS 12u" in text
        assert "#define FW_BEAM_PHASE_BITS 3u" in text
        assert text.count("static const") == 4
        assert text.count("{") == text.count("}")
        for array in ("fw_beam_code_word", "fw_beam_x_mm", "fw_beam_y_mm",
                      "fw_beam_u0"):
            decl = re.search(
                rf"static const \w+ {array}\[FW_BEAM_N_ELEMENTS\] = \{{\n(.*?)\}};",
                text, re.DOTALL)
            assert decl is not None, array
            for line in decl.group(1).strip().splitlines():
                body = line.strip()
                assert re.fullmatch(
                    r"[-\d.]+, /\* element_id=\d+ \*/"
                    r"|\d+u, /\* element_id=\d+ \*/", body), body
        codes = re.search(
            r"static const uint16_t fw_beam_code_word\[FW_BEAM_N_ELEMENTS\]"
            r" = \{\n(.*?)\};", text, re.DOTALL).group(1)
        parsed = [int(m) for m in re.findall(r"(\d+)u,", codes)]
        assert parsed == [r["code_word"] for r in table["rows"]]
        assert "nan" not in text.lower() and "inf" not in text.lower()

    def test_c_header_rejects_bad_identifier(self):
        table = _beam_rows(4, 2)
        with pytest.raises(ValueError, match="标识符"):
            fe.beam_table_c_header(table, array_name="1bad name")

    def test_input_validation(self):
        rng = np.random.default_rng(5)
        x = rng.uniform(-1, 1, 4)
        with pytest.raises(ValueError, match="长度不等"):
            fe.beam_codeword_table([0, 1, 2], x, x, [0.0, 0.0], bits=2)
        with pytest.raises(ValueError, match="bits"):
            fe.beam_codeword_table([0, 1], x[:2], x[:2], [0.0, 10.0], bits=0)
        with pytest.raises(ValueError, match="bool"):
            fe.beam_codeword_table([0, 1], x[:2], x[:2], [0.0, 10.0], bits=True)
        with pytest.raises(ValueError, match="u0"):
            fe.beam_codeword_table([0, 1], x[:2], x[:2], [0.0, 10.0], bits=2,
                                   u0=[1.0, -0.5])
        with pytest.raises(ValueError, match="element_ids"):
            fe.beam_codeword_table([0.5, 1], x[:2], x[:2], [0.0, 10.0], bits=2)
        with pytest.raises(ValueError, match="temp_comp_channels"):
            fe.beam_codeword_table([0, 1], x[:2], x[:2], [0.0, 10.0], bits=2,
                                   temp_comp_channels=0)
        with pytest.raises(ValueError, match="缺 rows"):
            fe.beam_backsub_audit({"bits": 2, "quant_step_deg": 90.0,
                                   "rows": []})
        with pytest.raises(ValueError, match="band_db"):
            fe.beam_backsub_audit(_beam_rows(4, 2), band_db=0.0)


# ════════════════════════════ ② varactor DAC 表 ═════════════════════════════


class TestVaractorDacTable:
    """PT-6② 变容管 DAC 表：链路恒等式/单调审计/饱和例/域守卫。"""

    def test_chain_identity_per_row(self):
        # 逐行独立调用消费内核对拍（同源闭式、独立调用路径）
        table = fe.varactor_dac_table(_F_ASC, v_ref_v=64.0, bit_width=8, **_VAR_KW)
        lsb = 64.0 / 256
        for row, f in zip(table["rows"], _F_ASC, strict=True):
            c_ref = varactor_load_capacitance_pf(
                f, _VAR_KW["line_len_mm"], _VAR_KW["z0_ohm"], _VAR_KW["ereff"])
            v_ref = bias_for_capacitance_v(
                c_ref, _VAR_KW["cj0_pf"], _VAR_KW["phi_v"])
            assert row["c_req_pf"] == c_ref
            assert row["v_bias_v"] == v_ref
            expect_code = min(round(v_ref / lsb), 255)
            assert row["dac_code"] == expect_code
            assert row["saturated"] is (expect_code == 255 and v_ref / lsb > 255)
            assert row["v_dac_v"] == expect_code * lsb
            if not row["saturated"]:
                assert abs(row["v_residual_v"]) <= lsb / 2.0 + 1e-12
        assert table["lsb_v"] == lsb
        assert table["full_scale_v"] == 255 * lsb

    def test_monotonic_audit_true(self):
        # 锚：单调性审计恒真例（主谐振方程链 f↑⇒C↓⇒V↑ 的物理单调性）
        table = fe.varactor_dac_table(_F_ASC, v_ref_v=64.0, bit_width=8, **_VAR_KW)
        assert table["audit"] == {
            "bit_width": 8, "monotonic_v": True, "monotonic_c": True,
            "saturation_count": 0,
        }
        cs = [r["c_req_pf"] for r in table["rows"]]
        vs = [r["v_bias_v"] for r in table["rows"]]
        assert all(cs[i] > cs[i + 1] for i in range(len(cs) - 1))   # 严格递减
        assert all(vs[i] < vs[i + 1] for i in range(len(vs) - 1))   # 严格递增

    def test_saturation_example(self):
        # 锚：饱和例——v_ref=10V/bw=6 LSB=0.15625V 满量程 63 码；
        # f=4.2GHz 需 ~9.8V → round 恰 63 码未越界（未饱和），f=4.4GHz 需
        # ~19.9V → 127 码越界钳于 63（唯一饱和点）；码序列 [6,16,33,63,63]
        # 预声明钉
        table = fe.varactor_dac_table(_F_ASC, v_ref_v=10.0, bit_width=6, **_VAR_KW)
        assert table["audit"]["saturation_count"] == 1
        assert [r["dac_code"] for r in table["rows"]] == [6, 16, 33, 63, 63]
        assert [r["saturated"] for r in table["rows"]] == [
            False, False, False, False, True]
        assert table["rows"][3]["saturated"] is False  # 63=满码可达，未越界
        assert table["full_scale_v"] == pytest.approx(63 * 10.0 / 64)
        assert table["rows"][-1]["v_dac_v"] == table["full_scale_v"]

    def test_unordered_frequencies_fail(self):
        with pytest.raises(ValueError, match="严格递增"):
            fe.varactor_dac_table([4.0, 3.8], v_ref_v=10.0, bit_width=6, **_VAR_KW)
        with pytest.raises(ValueError, match="严格递增"):
            fe.varactor_dac_table([4.0, 4.0], v_ref_v=10.0, bit_width=6, **_VAR_KW)
        with pytest.raises(ValueError, match="至少 2 点"):
            fe.varactor_dac_table([4.0], v_ref_v=10.0, bit_width=6, **_VAR_KW)

    def test_out_of_window_fail(self):
        lo, hi = loaded_line_f0_limits_ghz(_VAR_KW["line_len_mm"],
                                           _VAR_KW["ereff"])
        with pytest.raises(ValueError, match="装载窗"):
            fe.varactor_dac_table([lo - 0.5, lo - 0.4], v_ref_v=10.0,
                                  bit_width=6, **_VAR_KW)
        with pytest.raises(ValueError, match="装载窗"):
            fe.varactor_dac_table([hi + 0.1, hi + 0.2], v_ref_v=10.0,
                                  bit_width=6, **_VAR_KW)

    def test_forward_bias_domain_fail(self):
        # f=3.0GHz 需 C≈5.3pF > cj0=2pF → 正偏域显式拒绝（不造假行）
        with pytest.raises(ValueError, match="正偏域"):
            fe.varactor_dac_table([3.0, 3.1], v_ref_v=10.0, bit_width=6,
                                  **_VAR_KW)

    def test_input_validation(self):
        with pytest.raises(ValueError, match="bit_width"):
            fe.varactor_dac_table(_F_ASC, v_ref_v=10.0, bit_width=True, **_VAR_KW)
        with pytest.raises(ValueError, match="bit_width"):
            fe.varactor_dac_table(_F_ASC, v_ref_v=10.0, bit_width=0, **_VAR_KW)
        with pytest.raises(ValueError, match="v_ref_v"):
            fe.varactor_dac_table(_F_ASC, v_ref_v=0.0, bit_width=6, **_VAR_KW)
        with pytest.raises(ValueError, match=r"bool|数值序列"):
            fe.varactor_dac_table(True, v_ref_v=10.0, bit_width=6, **_VAR_KW)

    def test_csv_roundtrip(self):
        table = fe.varactor_dac_table(_F_ASC, v_ref_v=10.0, bit_width=6, **_VAR_KW)
        text = fe.varactor_table_csv(table)
        reader = csv.reader(io.StringIO(text))
        assert next(reader) == list(fe.VARACTOR_COLUMNS)
        for row_dict, parsed in zip(table["rows"], reader, strict=True):
            assert float(parsed[0]) == row_dict["f_target_ghz"]
            assert int(parsed[3]) == row_dict["dac_code"]
            assert parsed[6] == ("1" if row_dict["saturated"] else "0")


# ════════════════════════════ ③ DPD 定点表 ══════════════════════════════════


def _ila_dpd(n: int = 4000, seed: int = 42):
    """合成 PA → ILA 综合回收 DPD（固定种子，锚数字可复现）。"""
    rng = np.random.default_rng(seed)
    x = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / math.sqrt(2.0)
    pa = np.array([[1.0 + 0j], [0.15 + 0.02j], [-0.02 + 0.01j]])
    y = apply_memory_polynomial(x, pa)
    dpd = synthesize_dpd_postinverse(x, y, 3, 1)
    return x, pa, dpd


class TestDpdFixedPointTable:
    """PT-6③ DPD 定点表：Q 定标/回代 NMSE 门/级联劣化/溢出告警。"""

    def test_fine_q_nmse_within_gate(self):
        # 锚：合成系数定点回代 NMSE 门内——Q16.12 实测 −67dB（预探 runs/pt6）
        x, pa, dpd = _ila_dpd()
        table = fe.dpd_fixed_point_table(dpd, x, pa_coeffs=pa)
        assert table["verdict"] == "PASS"
        assert table["word_bits"] == 16 and table["frac_bits"] == 12
        assert table["q_format"] == "Q3.12"
        assert table["nmse_db"] <= -40.0          # 门（−0.5dB）的裕量面
        assert table["nmse_db"] <= -table["nmse_gate_db"]
        assert table["warnings_count"] == 0 and table["overflow"] == []
        assert table["gain_delta_db"] <= 0.01
        # 级联劣化门2（规格 ≤0.5dB）
        assert table["cascade"]["degradation_db"] <= 0.5
        # 定点整数在字域内且反算浮点≈原系数（舍入 ≤0.5 LSB）
        for ki, row in enumerate(table["coeffs_int"]):
            for mi, pair in enumerate(row):
                assert -32768 <= pair["re"] <= 32767
                assert abs(pair["re"] / 4096.0 - dpd.coeffs[ki, mi].real) \
                    <= 0.5 / 4096.0 + 1e-12

    def test_cascade_degradation_fine_q(self):
        # 级联劣化门2的裕量档：Q16.14 量化噪声再降 4 倍 → 劣化 ~0.04dB
        x, pa, dpd = _ila_dpd()
        table = fe.dpd_fixed_point_table(dpd, x, frac_bits=14, pa_coeffs=pa)
        assert table["verdict"] == "PASS"
        assert table["cascade"]["degradation_db"] <= 0.1

    def test_overflow_warning_and_fail(self):
        # 锚：溢出告警触发例——Q6.3（字域 [−32,31]，scale=8）：5.0→40 溢出
        # 钳位于 31；溢出+粗量化双面：verdict FAIL（级联劣化 >0.5dB）
        x, pa, _ = _ila_dpd()
        coeffs = [[5.0 + 1.0j, 0.1 + 0.0j], [-2.0 + 0.0j, 0.05 + 0.0j]]
        table = fe.dpd_fixed_point_table(coeffs, x, word_bits=6, frac_bits=3,
                                         pa_coeffs=pa)
        assert table["warnings_count"] >= 1
        ov = table["overflow"][0]
        assert (ov["k"], ov["m"], ov["part"]) == (0, 0, "re")
        assert ov["value"] == 40.0 and ov["clamped"] == 31.0
        assert table["coeffs_int"][0][0]["re"] == 31      # 钳位落账
        assert table["verdict"] == "FAIL"
        assert table["cascade"]["degradation_db"] > 0.5
        assert any("溢出告警" in note for note in table["notes"])

    def test_identity_zero_nmse(self):
        # 恒等例：1.0 在任何合理 Q 下精确 → NMSE=−inf、级联零劣化（−inf−(−inf)
        # 恒等退化为 0，不产 nan——边缘语义钉）
        x, _, _ = _ila_dpd(n=500)
        table = fe.dpd_fixed_point_table([[1.0 + 0j]], x, pa_coeffs=[[1.0 + 0j]])
        assert table["verdict"] == "PASS"
        assert table["nmse_db"] == -math.inf
        assert table["cascade"]["degradation_db"] == 0.0
        assert table["gain_delta_db"] == 0.0

    def test_coarse_q_gate1_bite(self):
        # 门1（NMSE ≤ −0.5dB 字面下限）的咬合面：Q3.1 字域 [−4,3]、scale=2，
        # 100.0 溢出钳位 3 → 系数误差 97/100 → NMSE≈−0.1dB > −0.5 → FAIL
        x, _, _ = _ila_dpd(n=500)
        table = fe.dpd_fixed_point_table([[100.0 + 0j]], x, word_bits=3,
                                         frac_bits=1)
        assert table["verdict"] == "FAIL"
        assert table["warnings_count"] == 1
        assert table["nmse_db"] > -0.5
        assert any("门1 FAIL" in note for note in table["notes"])

    def test_memory_polynomial_model_input(self):
        # MemoryPolyModel（dpd_static:143 同构）鸭子接收 ≡ 裸数组
        x, _pa, dpd = _ila_dpd()
        assert isinstance(dpd, MemoryPolyModel)
        t_model = fe.dpd_fixed_point_table(dpd, x)
        t_array = fe.dpd_fixed_point_table(dpd.coeffs, x)
        assert t_model["nmse_db"] == t_array["nmse_db"]
        assert t_model["coeffs_int"] == t_array["coeffs_int"]

    def test_csv_roundtrip(self):
        x, _, _ = _ila_dpd(n=200)
        table = fe.dpd_fixed_point_table([[5.0 + 1.0j, 0.1], [-2.0, 0.05]],
                                         x, word_bits=6, frac_bits=3)
        text = fe.dpd_table_csv(table)
        reader = csv.reader(io.StringIO(text))
        assert next(reader) == list(fe.DPD_COLUMNS)
        rows = list(reader)
        assert len(rows) == 4
        assert rows[0] == ["0", "0", "31", "8", "3.875", "1.0", "1"]  # 溢出行
        assert rows[1][6] == "0"
        for row_dict, parsed in zip(
                (r for row in table["coeffs_int"] for r in row), rows,
                strict=True):
            assert int(parsed[2]) == row_dict["re"]
            assert float(parsed[4]) == row_dict["re"] / table["scale"]

    def test_input_validation(self):
        x, _, _ = _ila_dpd(n=100)
        with pytest.raises(ValueError, match="word_bits"):
            fe.dpd_fixed_point_table([[1.0]], x, word_bits=True)
        with pytest.raises(ValueError, match="frac_bits"):
            fe.dpd_fixed_point_table([[1.0]], x, word_bits=8, frac_bits=8)
        with pytest.raises(ValueError, match="nmse_gate_db"):
            fe.dpd_fixed_point_table([[1.0]], x, nmse_gate_db=0.0)
        with pytest.raises(ValueError, match="有限"):
            fe.dpd_fixed_point_table([[float("nan")]], x)
        with pytest.raises(ValueError, match="不能为空"):
            fe.dpd_fixed_point_table([[1.0]], [])
        with pytest.raises(ValueError, match="形状"):
            fe.dpd_fixed_point_table(np.zeros((0, 2)), x)
        with pytest.raises(ValueError, match="零功率"):
            fe.dpd_fixed_point_table([[0.0 + 0j]], x)

    def test_json_serializable(self):
        x, pa, dpd = _ila_dpd()
        table = fe.dpd_fixed_point_table(dpd, x, pa_coeffs=pa)
        json.dumps(table, ensure_ascii=False)  # 不抛即通过（−inf 面除外，此处无）


# ════════════════════════════ CLI firmware 子应用 ═══════════════════════════


class TestFirmwareCli:
    """rfauto firmware 子应用薄壳（CliRunner 驱动真实入口）。"""

    def _invoke(self, *args: str):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        return CliRunner().invoke(app, list(args))

    def _beam_payload(self, tmp_path: Path) -> Path:
        rng = np.random.default_rng(7)
        payload = {
            "element_ids": list(range(8)),
            "x_mm": list(rng.uniform(-20, 20, 8)),
            "y_mm": list(rng.uniform(-20, 20, 8)),
            "phase_target_deg": list(rng.uniform(0, 360, 8)),
        }
        p = tmp_path / "elements.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def _var_payload(self, tmp_path: Path) -> Path:
        payload = {"f_targets_ghz": _F_ASC, "v_ref_v": 10.0, "bit_width": 6,
                   **_VAR_KW}
        p = tmp_path / "varactor.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def _dpd_payload(self, tmp_path: Path) -> Path:
        rng = np.random.default_rng(11)
        payload = {
            "coeffs": [[{"re": 1.0, "im": 0.0}], [{"re": 0.098, "im": 0.01}]],
            "x": [[float(a), float(b)] for a, b in zip(
                rng.standard_normal(400), rng.standard_normal(400),
                strict=True)],
            "word_bits": 16, "frac_bits": 12,
        }
        p = tmp_path / "dpd.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_registered_in_top_level(self):
        from typer.main import get_command

        from rfauto.cli.main import app

        cmd = get_command(app)
        assert "firmware" in set(cmd.commands)
        fw = cmd.commands["firmware"]
        assert {"beam", "varactor", "dpd"} <= set(fw.commands)

    def test_beam_happy_path(self, tmp_path):
        csv_out = tmp_path / "beam.csv"
        ch_out = tmp_path / "beam.h"
        result = self._invoke(
            "firmware", "beam", "--bits", "2",
            "--file", str(self._beam_payload(tmp_path)),
            "--csv", str(csv_out), "--ch", str(ch_out),
        )
        assert result.exit_code == 0, result.output
        env = json.loads(result.output)
        assert env["ok"] is True
        assert env["audit"]["verdict"] == "PASS"
        assert env["csv_path"] == str(csv_out) and env["ch_path"] == str(ch_out)
        # 落盘面显式 UTF-8 且内容=内核文本（#89 家族：编码抽查）
        csv_text = csv_out.read_text(encoding="utf-8")
        assert csv_text.splitlines()[0] == ",".join(fe.BEAM_COLUMNS)
        ch_text = ch_out.read_text(encoding="utf-8")
        assert "#include <stdint.h>" in ch_text

    def test_beam_rows_flag_off_by_default(self, tmp_path):
        result = self._invoke(
            "firmware", "beam", "--bits", "2",
            "--file", str(self._beam_payload(tmp_path)))
        env = json.loads(result.output)
        assert "rows" not in env
        result2 = self._invoke(
            "firmware", "beam", "--bits", "2", "--rows",
            "--file", str(self._beam_payload(tmp_path)))
        assert len(json.loads(result2.output)["rows"]) == 8

    def test_beam_missing_file_fails(self):
        result = self._invoke("firmware", "beam", "--bits", "2",
                              "--file", "no_such.json")
        assert result.exit_code != 0

    def test_beam_bad_payload_fails(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"x_mm": [1.0]}), encoding="utf-8")
        result = self._invoke("firmware", "beam", "--bits", "2",
                              "--file", str(p))
        assert result.exit_code == 1
        env = json.loads(result.output)
        assert env["ok"] is False and "error" in env

    def test_varactor_happy_path_with_saturation(self, tmp_path):
        csv_out = tmp_path / "var.csv"
        result = self._invoke("firmware", "varactor",
                              "--file", str(self._var_payload(tmp_path)),
                              "--csv", str(csv_out))
        assert result.exit_code == 0, result.output
        env = json.loads(result.output)
        assert env["ok"] is True
        assert env["audit"]["saturation_count"] == 1
        assert [r["dac_code"] for r in env["rows"]] == [6, 16, 33, 63, 63]
        assert csv_out.exists()

    def test_varactor_bad_payload_fails(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"f_targets_ghz": [4.0]}), encoding="utf-8")
        result = self._invoke("firmware", "varactor", "--file", str(p))
        assert result.exit_code == 1
        assert json.loads(result.output)["ok"] is False

    def test_dpd_happy_path(self, tmp_path):
        csv_out = tmp_path / "dpd.csv"
        result = self._invoke("firmware", "dpd",
                              "--file", str(self._dpd_payload(tmp_path)),
                              "--csv", str(csv_out))
        assert result.exit_code == 0, result.output
        env = json.loads(result.output)
        assert env["ok"] is True and env["verdict"] == "PASS"
        assert env["q_format"] == "Q3.12"
        assert env["warnings_count"] == 0
        assert env["nmse_db"] <= -40.0
        assert csv_out.read_text(encoding="utf-8").splitlines()[0] \
            == ",".join(fe.DPD_COLUMNS)

    def test_dpd_overflow_reports_warnings(self, tmp_path):
        payload = {
            "coeffs": [[{"re": 5.0, "im": 1.0}, {"re": 0.1, "im": 0.0}]],
            "x": [[float(a), float(b)] for a, b in zip(
                np.random.default_rng(3).standard_normal(200),
                np.random.default_rng(4).standard_normal(200), strict=True)],
            "word_bits": 6, "frac_bits": 3,
        }
        p = tmp_path / "ovf.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        result = self._invoke("firmware", "dpd", "--file", str(p))
        assert result.exit_code == 0  # 溢出=告警面，非命令失败
        env = json.loads(result.output)
        assert env["warnings_count"] >= 1
        assert env["overflow"][0]["clamped"] == 31.0
        assert any("溢出告警" in note for note in env["notes"])

    def test_dpd_bad_complex_payload_fails(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"coeffs": [["oops"]], "x": [1.0]}),
                     encoding="utf-8")
        result = self._invoke("firmware", "dpd", "--file", str(p))
        assert result.exit_code == 1
        assert json.loads(result.output)["ok"] is False

"""均匀槽线段附加模板（adapters/slotline_template.py）单测：渲染结构 + #212 离线几何审计。

#212 纪律：字符串存在性/compile() 抓不住画法错误——渲染→exec 几何段→CSXCAD
实测金属原语（DC 两组隔离=槽真断开）、端口/探针属性、网格线含槽缘与基板界面。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.adapters.slotline_template import (
    N_PROBE_STATIONS,
    render_slotline_script,
    slotline_layout,
)

W_MM, H_MM, L_MM = 1.0, 1.524, 93.4624
PARAMS = {"w_mm": W_MM, "h_mm": H_MM, "line_len_mm": L_MM, "er": 3.66}
BAND = (2.25, 2.75)


def _render(tmp_path, **kw) -> str:
    return render_slotline_script(
        {**PARAMS, **kw.pop("params", {})}, BAND,
        e_mode_file=str(tmp_path / "mode_E.h5"),
        h_mode_file=str(tmp_path / "mode_H.h5"),
        kc=complex(0.0, 136.0), z_mode_ohm=107.4,
        beta_ref_rad_m=67.22687889224117, **kw)


class TestRenderStructure:
    def test_compiles_and_carries_port_contract(self, tmp_path):
        text = _render(tmp_path)
        compile(text, "gen", "exec")  # 语法门（#201）
        # 端口契约：文件模式 E/H + kc + 交叉参考两遍 CalcPort + excite_port 参数化
        assert text.count("WaveguidePort(CSX") == 2
        assert "E_WG_file=E_FILE" in text and "H_WG_file=H_FILE" in text
        assert "local_origin=None" in text and "excite_type=0" in text
        assert "excite=1 if EXCITE_PORT == 1 else 0" in text
        assert text.count("CalcPort(SIM_PATH, f, ZL=Z_MODE)") == 2
        # 度量常数处置（pt2 实证 γ≈2.71）：交叉参考（port1 取 −z2_raw，不含 Γ1）
        assert "ref_impedance=_z_ref1" in text and "ref_impedance=_z_ref2" in text
        assert "_z_ref1 = -_z2_raw" in text
        assert "complex(0.0, 136.0)" in text
        assert '"PML_8", "PML_8", "MUR", "MUR", "MUR", "MUR"' in text
        # β 独立提取：槽跨压探针（循环生成）+ 自实现工程 DFT 相位斜率（+β）
        assert 'CSX.AddProbe("vslot_%02d" % _k, p_type=0)' in text
        assert "beta_probe = np.polyfit(PROBE_X, _phases, 1)[0]" in text
        assert "2j * np.pi * np.asarray(f)[:, None] * _t[None, :]" in text
        assert "slotline_summary.json" in text and "slotline_beta.csv" in text
        assert "67.22687889224117" in text  # 闭式 β 进 meta 对照

    def test_excite_port_param(self, tmp_path):
        t1 = _render(tmp_path, excite_port=1)
        t2 = _render(tmp_path, excite_port=2)
        compile(t2, "gen2", "exec")
        assert "EXCITE_PORT = 1" in t1 and "EXCITE_PORT = 2" in t2
        assert "excite=1 if EXCITE_PORT == 2 else 0" in t2


class TestLayout:
    def test_station_symmetry_and_spacing(self):
        lay = slotline_layout(PARAMS, BAND)
        assert len(lay.probe_x_m) == N_PROBE_STATIONS
        assert np.all(np.diff(lay.probe_x_m) > 0)
        assert lay.probe_x_m[0] == pytest.approx(-lay.probe_x_m[-1])
        assert lay.x_meas1_m == pytest.approx(lay.x_exc1_m + lay.port_len_m)
        assert lay.x_meas2_m - lay.x_meas1_m == pytest.approx(L_MM * 1e-3)
        # 激励面内移须显著大于 PML_8 厚度（≈8·BASE；16·BASE 设计）
        assert lay.port_inset_m > 12 * lay.base_m
        assert lay.x_exc1_m > -lay.dom_x_m  # 激励面在域内、不在边界上

    def test_layout_rejects_bad_params(self):
        with pytest.raises(ValueError):
            slotline_layout({"w_mm": -1.0, "h_mm": 1.5}, BAND)
        with pytest.raises(ValueError):
            slotline_layout({"w_mm": 200.0, "h_mm": 1.5, "y_half_mm": 60.0}, BAND)


class TestGeometryAudit:
    """#212 离线审计：exec 脚本头 → CSXCAD 实测。"""

    @pytest.fixture(scope="class")
    def sim(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp("slotline_audit")
        text = _render(tmp)
        head = text[: text.index("FDTD.Run(")]
        g = {"__name__": "__main__", "__file__": str(tmp / "simulation.py")}
        exec(compile(head, "sim", "exec"), g)
        return g, text, tmp

    def _metal_boxes_mm(self, csx):
        boxes = []
        for pi in range(csx.GetQtyProperties()):
            prop = csx.GetProperty(pi)
            if str(prop.GetTypeString()) != "Metal":
                continue
            for prim in prop.GetAllPrimitives():
                s = np.array(prim.GetStart(), dtype=float)
                e = np.array(prim.GetStop(), dtype=float)
                boxes.append((min(s[0], e[0]), max(s[0], e[0]), min(s[1], e[1]),
                              max(s[1], e[1]), min(s[2], e[2]), max(s[2], e[2])))
        return boxes

    def test_slot_metal_two_isolated_groups(self, sim):
        """槽 DC 断开：z=h 面金属恰两盒、|y|<w/2 无金属、两组互不相交。"""
        g, _text, _tmp = sim
        boxes = [b for b in self._metal_boxes_mm(g["CSX"]) if abs(b[4] - 1.524e-3) < 1e-12]
        assert len(boxes) == 2
        for b in boxes:
            # 金属盒边必须停在槽缘（y ≤ −w/2 或 y ≥ +w/2，盒缘恰在槽缘）
            assert b[3] <= -W_MM / 2 * 1e-3 + 1e-12 or b[2] >= W_MM / 2 * 1e-3 - 1e-12
        gap = min(b[3] for b in boxes), max(b[2] for b in boxes)
        assert gap[0] == pytest.approx(-W_MM / 2 * 1e-3, abs=1e-12)
        assert gap[1] == pytest.approx(+W_MM / 2 * 1e-3, abs=1e-12)

    def test_substrate_spans_domain(self, sim):
        g, _text, _tmp = sim
        mats = []
        for pi in range(g["CSX"].GetQtyProperties()):
            prop = g["CSX"].GetProperty(pi)
            if str(prop.GetTypeString()) == "Material":
                for prim in prop.GetAllPrimitives():
                    s = np.array(prim.GetStart(), dtype=float)
                    e = np.array(prim.GetStop(), dtype=float)
                    mats.append((min(s[0], e[0]), max(s[0], e[0]),
                                 min(s[2], e[2]), max(s[2], e[2])))
        assert len(mats) == 1
        x0, x1, z0, z1 = mats[0]
        mesh = g["CSX"].GetGrid()
        assert x0 == pytest.approx(min(mesh.GetLines("x")), abs=1e-12)
        assert x1 == pytest.approx(max(mesh.GetLines("x")), abs=1e-12)
        assert z0 == pytest.approx(0.0) and z1 == pytest.approx(1.524e-3)

    def test_ports_and_probes_properties(self, sim):
        g, _text, _tmp = sim
        csx = g["CSX"]
        exc, probes = [], []
        for pi in range(csx.GetQtyProperties()):
            prop = csx.GetProperty(pi)
            ts = str(prop.GetTypeString())
            if ts == "Excitation":
                exc.append(prop)
            elif ts == "ProbeBox":
                probes.append(prop)
        # 单激励（excite_port=1）：恰一份激励、带 E 权重文件与 +x 传播方向
        assert len(exc) == 1
        assert exc[0].GetWeightFile().endswith("mode_E.h5")
        np.testing.assert_allclose(exc[0].GetPropagationDir(), [1, 0, 0])
        # 探针：2 端口 × (U=10 + I=11) + 9 槽跨压（p_type=0）
        wg = [p for p in probes if p.GetProbeType() in (10, 11)]
        vs = [p for p in probes if p.GetProbeType() == 0]
        assert len(wg) == 4 and sorted(p.GetProbeType() for p in wg) == [10, 10, 11, 11]
        assert len(vs) == N_PROBE_STATIONS
        h_files = {p.GetModeFile() for p in wg}
        assert any(f.endswith("mode_E.h5") for f in h_files)
        assert any(f.endswith("mode_H.h5") for f in h_files)
        # 槽跨压探针盒：x 单点、y 跨槽、z=h
        for p in vs:
            s = np.array(p.GetAllPrimitives()[0].GetStart(), dtype=float)
            e = np.array(p.GetAllPrimitives()[0].GetStop(), dtype=float)
            assert s[0] == e[0]
            assert s[1] == pytest.approx(-W_MM / 2 * 1e-3) and e[1] == pytest.approx(W_MM / 2 * 1e-3)
            assert s[2] == pytest.approx(1.524e-3) and e[2] == pytest.approx(1.524e-3)

    def test_port_box_inset_avoids_mur_overlap(self, sim):
        """pt1 首跑实证：盒跨满截面 → MUR 延迟开启瞬态激起 DC 漂移。盒必须内缩
        ≥2·BASE 出 MUR 边界胞层（激励与 U/I 模式探针同盒）。"""
        g, _text, _tmp = sim
        lay = slotline_layout(PARAMS, BAND)
        assert lay.box_inset_m >= 2 * lay.base_m - 1e-15
        p1 = g["_port1"]
        assert float(p1.start[1]) == pytest.approx(-lay.y_half_m + lay.box_inset_m)
        assert float(p1.stop[1]) == pytest.approx(lay.y_half_m - lay.box_inset_m)
        assert float(p1.start[2]) == pytest.approx(-lay.z_bot_m + lay.box_inset_m)
        assert float(p1.stop[2]) == pytest.approx(
            lay.h_m + lay.z_top_m - lay.box_inset_m)

    def test_mesh_carries_slot_edges_and_substrate_faces(self, sim):
        g, _text, _tmp = sim
        mesh = g["CSX"].GetGrid()
        ly = np.asarray(mesh.GetLines("y"), dtype=float)
        for v in (-W_MM / 2 * 1e-3, 0.0, W_MM / 2 * 1e-3):
            assert np.any(np.abs(ly - v) < 1e-12), f"y 网格缺 {v}"
        lz = np.asarray(mesh.GetLines("z"), dtype=float)
        for v in (0.0, 1.524e-3):
            assert np.any(np.abs(lz - v) < 1e-12), f"z 网格缺 {v}"
        lx = np.asarray(mesh.GetLines("x"), dtype=float)
        lay = slotline_layout(PARAMS, BAND)
        for v in (lay.x_exc1_m, lay.x_meas1_m, lay.x_meas2_m, lay.x_exc2_m):
            assert np.any(np.abs(lx - v) < 1e-12), f"x 网格缺端口面 {v}"
        # #152 守卫已跑：全轴最小间距 ≥1µm
        for ax, ls in (("x", lx), ("y", ly), ("z", lz)):
            assert np.min(np.diff(ls)) > 1e-6, f"{ax} 轴存在近重合线"
        # 激励面出 PML：内移量 > 8·边界区网格
        assert lay.x_exc1_m - min(lx) > 8 * 1.1 * lay.base_m

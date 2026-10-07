"""COMSOL 6.3 RF 真跑集成测试（**opt-in 双门**，照 xyce/palace 先例）。

双门（缺一即 skip，unit 门保持封闭 #139/#df4⑥）：
1. 意图门：env ``RFAUTO_COMSOL_IT=1`` 显式启用（真机求解不进缺省门；
   每次求解占一个 RF license 席位且适配器模块级串行锁——勿与其他 COMSOL
   作业并发触发本用例，#215/#217 纪律）；
2. 机器状态门：MPh 可导入 + COMSOL 安装根存在（RFAUTO_COMSOL_ROOT >
   默认 E:\\COMSOL\\COMSOL_63\\COMSOL63\\Multiphysics，缺席 skip 不红）。

用例语义（#215 首案例锚复刻，runs/comsol_smoke/run_smoke_parallel_plate.py
同判据）：平行板 TEM 传输线 2 端口，connect → build_geometry → solve
（COMSOL 6.3 显式钉版，频域 5 点）→ get_sparams vs 闭式精确解
（TEM：εeff=εr 精确、Z0=η0/√εr·(H/W)，tl_section_sparams ABCD→S）。

判据预声明（缺省几何 W=6/H=1.154/εr=2.1/L=20mm ⇒ Z0≈50.00Ω 匹配线）：
- 闭式一致性：S21 相位偏差 ≤3°（#298 峰位歧义教训——用相位而非 argmax）；
  复数 S 逐点线性幅度误差 |ΔS11|、|ΔS21| ≤ 0.01（2026-09-11 真机实测
  max |ΔS11|=8.09e-08，0.01 已是宽松门）；
- εeff 门：S21 解缠相位斜率反推 εeff 对 εr=2.1 偏差 ≤3%（匹配线前提成立；
  #195 判据匹配响应形态——失配下该提取器不适用，本用例固定 Zref=50 匹配）；
- 传输健康门（transmission_health）：无源性 max|S|≤1.02、|S21|min≥0.95、
  |S11|worst≤−20dB。

预算：FEM 5 频点实测求解 13.6s + comsolmphserver 启动数十秒，分钟级内。
绿记录：2026-09-11 runs/comsol_smoke/smoke_summary_parallel_plate.json 全门 PASS。
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.real_edt

_INTENT_ENV = "RFAUTO_COMSOL_IT"

_FREQS = [2.2, 2.3, 2.4, 2.5, 2.6]
_MESH_MM = 1.0
_PARAMS = {"length_mm": 20.0, "width_mm": 6.0, "height_mm": 1.154,
           "eps_r": 2.1, "z_ref_ohm": 50.0, "freq_ghz": _FREQS}


@pytest.mark.skipif(
    os.environ.get(_INTENT_ENV, "") != "1",
    reason=(f"真跑集成测试 opt-in：设 {_INTENT_ENV}=1 启用（RF license 串行"
            "占用，真机求解不进缺省门 #139/#df4⑥）。"),
)
class TestComsolIntegration:
    def test_parallel_plate_closed_form(self, tmp_path):
        from rfauto.adapters import comsol_adapter as ca
        from rfauto.adapters.comsol_adapter import (
            ComsolAdapter,
            extract_eps_eff,
            parallel_plate_closed_form,
            transmission_health,
        )
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType

        if not ca.mph_installed() or not Path(ca.DEFAULT_COMSOL_ROOT).exists():
            pytest.skip("COMSOL/MPh 不可达（真机验收需 COMSOL 6.3 + MPh 桥）")

        cfg = EMSolverConfig(
            solver_type=EMSolverType.COMSOL,
            working_dir=str(tmp_path),
            freq_range_ghz=(_FREQS[0], _FREQS[-1]),
            mesh_resolution_mm=_MESH_MM,
            extra_params={"cores": 2},
        )
        adapter = ComsolAdapter(cfg)
        assert adapter.connect(), "COMSOL 可用性确认失败"
        assert adapter.build_geometry(
            {"template": "parallel_plate", "params": _PARAMS}), "build 失败"
        result = adapter.solve()
        assert result.success, result.message
        print(f"[comsol] {result.message} wall={result.wall_time_s:.1f}s")
        # 产物门：spec 证据落位（solve 的建模证据链）
        assert (tmp_path / "comsol_spec.json").is_file()

        freq, s = adapter.get_sparams()
        assert len(freq) == len(_FREQS)
        spec = dict(_PARAMS)
        s_ref = parallel_plate_closed_form(spec, freq)

        # 闭式一致性（TEM 精确解）
        phase_err = np.degrees(np.unwrap(
            np.angle(s[:, 1, 0]) - np.angle(s_ref[:, 1, 0])))
        max_phase_err = float(np.abs(phase_err).max())
        max_s11_err = float(np.abs(s[:, 0, 0] - s_ref[:, 0, 0]).max())
        max_s21_err = float(np.abs(s[:, 1, 0] - s_ref[:, 1, 0]).max())
        # εeff 门（S21 相位斜率，匹配线前提）
        eps_eff = extract_eps_eff(freq, s[:, 1, 0], spec["length_mm"])
        eps_err = abs(eps_eff - spec["eps_r"]) / spec["eps_r"]
        # 传输健康门（确定性内核）
        health = transmission_health(freq, s, s21_min_lin=0.95,
                                     s11_max_db=-20.0)
        print(f"[comsol] max phase err={max_phase_err:.4f}°, "
              f"max|ΔS11|={max_s11_err:.3e}, max|ΔS21|={max_s21_err:.3e}, "
              f"eps_eff={eps_eff:.5f} (ref {spec['eps_r']}, "
              f"err {eps_err * 100:.3f}%), health={health['checks']}")
        assert max_phase_err <= 3.0, "S21 相位对闭式偏差 >3°"
        assert max_s11_err <= 0.01 and max_s21_err <= 0.01, "复数 S 超差"
        assert eps_err <= 0.03, f"εeff 偏差 {eps_err * 100:.2f}% > 3%"
        assert health["ok"], health["checks"]

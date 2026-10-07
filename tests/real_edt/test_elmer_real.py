"""Elmer 26.1 真跑集成测试（**opt-in 双门**，照 xyce/palace 先例）。

双门（缺一即 skip，unit 门保持封闭 #139/#df4⑥）：
1. 意图门：env ``RFAUTO_ELMER_IT=1`` 显式启用（真机求解不进缺省门，
   RFAUTO_XYCE_IT/RFAUTO_PALACE_ITEST 同款口径）；
2. 机器状态门：ElmerSolver.exe 可达（resolve_elmer_bin：RFAUTO_ELMER_BIN >
   ELMER_HOME > 默认安装根 > PATH，缺席 skip 不红）。

用例语义（#233 锚复刻，heat_slab_1d 模板全适配器链）：
connect → build_geometry（Gmsh v2.2 结构化四边形网格 + SIF，ElmerGrid 14 2
转换）→ solve（子进程 ElmerSolver）→ line.dat 中线温度剖面 vs 独立解析解。

判据预声明（模板缺省参数：L=100mm、q=1000 W/m³、k=1 W/(m·K)、T0=300K）：
- 闭式 T(x) = T0 + q/(2k)·(2Lx − x²)，峰值温升 qL²/2k = 5.0 K（数值整齐）；
- 稳态热传导 + 线性解析解在结构化网格上是线性元精确问题——#233 真机实测
  max|ΔT| = 0.0 K；验收门取 scripts/elmer_plate_case.py 的 WP4.4d 口径
  （相对偏差 ≤1%），实测值随行打印；
- 物理方向门：温度沿 x 单调非降（左端 Dirichlet T0、右端绝热）；
- 点数门：SaveLine 沿中线输出 n_x+1 = 41 点；
- 产物门：case.sif / mesh/ / line.dat 在 working_dir 落位。

预算：稳态 40×2 四边形网格，求解秒-分钟级（solve_timeout_s=600 兜底）。
绿记录：2026-09-29 本机首跑（#233 同款 A4 锚，max|ΔT| 实测见用例打印）。
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.real_edt

_INTENT_ENV = "RFAUTO_ELMER_IT"


@pytest.mark.skipif(
    os.environ.get(_INTENT_ENV, "") != "1",
    reason=(f"真跑集成测试 opt-in：设 {_INTENT_ENV}=1 启用（真机求解不进缺省 "
            "门 #139/#df4⑥，xyce/palace 同款口径）。"),
)
class TestElmerIntegration:
    def test_heat_slab_1d_closed_form(self, tmp_path):
        from rfauto.adapters.elmer_adapter import (
            ElmerAdapter,
            normalize_slab_params,
            resolve_elmer_bin,
            slab_temperature_closed_form,
        )
        from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType

        solver_exe = resolve_elmer_bin(None)
        if solver_exe is None:
            pytest.skip("ElmerSolver 不可达（真机验收需 Elmer 26.1+）")

        spec = normalize_slab_params(None)  # 缺省：qL²/2k = 5.0 K 锚值
        cfg = EMSolverConfig(
            solver_type=EMSolverType.ELMER,
            exe_path=str(solver_exe),
            working_dir=str(tmp_path),
            extra_params={"solve_timeout_s": 600.0},
        )
        adapter = ElmerAdapter(cfg)
        assert adapter.connect(), adapter.last_message
        assert adapter.build_geometry(spec), adapter.last_message
        result = adapter.solve(timeout_s=600.0)
        assert result.success, result.message
        print(f"[elmer] {result.message} wall={result.wall_time_s:.1f}s")

        # 产物门
        assert (tmp_path / "case.sif").is_file()
        assert (tmp_path / "mesh").is_dir()
        assert (tmp_path / "line.dat").is_file()

        # 闭式对照（裁判=独立解析解，#118）
        x_m = result.field_data["x_m"]
        t_num = result.field_data["temperature_k"]
        t_ref = slab_temperature_closed_form(
            x_m,
            length_m=spec["thickness_mm"] / 1000.0,
            heat_source_w_m3=spec["heat_source_w_m3"],
            heat_conductivity_w_mk=spec["heat_conductivity_w_mk"],
            t0_k=spec["t0_k"],
        )
        # 点数门：SaveLine 沿中线 n_x+1 点
        assert x_m.size == int(spec["n_x"]) + 1, x_m.size
        # 物理方向门：左端定温、右端绝热 → 温度单调非降
        assert bool((t_num[1:] >= t_num[:-1] - 1e-9).all()), (
            "温度剖面应沿 x 单调非降（左 Dirichlet / 右绝热）")
        # 验收门：WP4.4d ≤1%（scripts/elmer_plate_case.py 口径；#233 实测 0.0K）
        rise = spec["heat_source_w_m3"] * (spec["thickness_mm"] / 1000.0) ** 2 / (
            2.0 * spec["heat_conductivity_w_mk"])
        max_err = float(abs(t_num - t_ref).max())
        rel = max_err / rise
        print(f"[elmer] 峰值温升闭式 qL^2/2k={rise:.6g} K, "
              f"max|ΔT|={max_err:.3e} K, 相对偏差={rel * 100:.4g}%")
        assert rel <= 0.01, f"max|ΔT|={max_err:.3e} K 超出 1% 验收门"
        # Dirichlet 端温度=环境温度（定温边界落位）
        assert t_num[0] == pytest.approx(spec["t0_k"], abs=1e-6 * rise)

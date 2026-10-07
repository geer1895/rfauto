"""openEMS 真跑集成测试（**opt-in 双门 + #261 互斥预检**，xyce/palace 先例）。

双门（缺一即 skip，unit 门保持封闭 #139/#df4⑥）：
1. 意图门：env ``RFAUTO_OPENEMS_IT=1`` 显式启用（FDTD 真跑分钟级且本机
   常有长跑战役占轨，绝不进缺省门）；
2. 机器状态门：openEMS exe 可达（resolve_openems_exe：solvers.yaml >
   RFAUTO_OPENEMS_BIN > 本机默认路径）；CSXCAD/openEMS Python 绑定经
   conftest `_CSXCAD_TEST_MODULES` 登记（子进程同解释器 import，传递依赖
   按 df4⑤ 口径）。

#261 互斥预检（发射前必过）：本仓 openEMS 是 python 子进程内 FDTD.Run
（`python _rfauto_runner.py simulation.py`），真跑前探测他轨在跑的 openEMS
python 命令行——命中即 skip（窗口未开，不代杀）；探测**自身失败 fail-closed**
（拒绝盲发）。探测标记 `_rfauto_runner|simulation\\.py` **不含本用例文件名**
（#261 自锁教训：互斥标记含自身名→自身进程被命中恒 skip）。

用例语义（mline 锚单点冒烟，scripts/engine_benchmark_mline.py auto 档同参）：
OpenEMSSolver 全链 connect → build_geometry(template=mline, w=1.113mm
50Ω HJ 锚标称, line_len=40mm) → solve（auto 网格 λ_sub/50 官方口径，
子进程 FDTD）→ sparams.csv + port_beta.csv 判读。

判据预声明（绿记录 runs/benchmark/mline_mesh_convergence.json auto 档：
wall 46s、|S11|max=−23.93dB、εeff=2.91836 对 HJ 闭式 2.85264 偏 +2.30%）：
- 健康门：全带 max|S11| < −10dB（50Ω 匹配线；显著非零=端口/网格判废信号，
  benchmark criteria.s11_max_db_lt）；
- β 金标准门：CalcPort β→εeff 对 HJ 闭式（core.synthesis.forward_z0，
  #118 独立解析锚）偏差 ≤3%（benchmark criteria.delta_vs_hj_pct_abs_le）；
- 传输门：带内 |S21|_dB 中位 ∈ (−1.0, 0.1]（匹配线插损近 0；绿记录
  ≈−0.18dB）；
- 产物门：sparams.csv / port_beta.csv / simulation.py 落位。

预算：auto 档真跑 ~46s（绿记录），solve_timeout_s=1800 兜底（细网格/慢机
余量）。发射时机：须 varactor 等长跑战役让出 openEMS 轨后（#261 预检会
自动 skip，不会撞车）。
"""

from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.real_edt

_INTENT_ENV = "RFAUTO_OPENEMS_IT"

# mline 锚标称点（权威口径表 §1；50Ω @rogers4350b = 1.113mm skrf HJ 精算）
_W_MM = 1.113
_LINE_LEN_MM = 40.0
_FREQ_RANGE = (2.25, 2.75)
_F_TARGET_HZ = 2.5e9
_SUBSTRATE = "rogers4350b_h0.508"

#: #261 探测标记：只匹配真机 FDTD 子进程（_rfauto_runner 引导脚本 /
#: 模板脚本 simulation.py），不得含本用例文件名（自锁，见模块 docstring）
_OE_PROC_PATTERN = "_rfauto_runner|simulation\\.py"


def _oe_foreign_running(tmp_path: Path) -> list[str]:
    """#261 互斥查：python CommandLine 含 FDTD 子进程标记（fail-closed 抛）。

    c3_fullcurve_runner.oe_foreign_running 同款：临时 .ps1 经
    powershell -NoProfile -ExecutionPolicy Bypass -File（#289 内联 $_ 被
    shell 层展开/引号嵌套不可过）。
    """
    ps1 = tmp_path / "_oe_proc_check.ps1"
    ps1.write_text(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        f"Where-Object {{ $_.CommandLine -match '{_OE_PROC_PATTERN}' }} | "
        "ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.CommandLine }\n",
        encoding="ascii")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1)],
            capture_output=True, text=True, timeout=120)
    finally:
        ps1.unlink(missing_ok=True)
    if out.returncode != 0:
        raise RuntimeError(
            f"#261 进程查询失败 rc={out.returncode}: {out.stderr[:300]}")
    return [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]


def _beta_eps(work: Path) -> float:
    """读 CalcPort port_beta.csv → εeff（金标准口径，#162/#364②）。

    取对照频点 ±4% 窗内 β 中位（窗缘 ulp 不敏感）。
    """
    with open(work / "port_beta.csv", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    bf = np.array([float(r[0]) for r in rows])
    bb = np.array([float(r[1]) for r in rows])
    sel = (bf >= 0.96 * _F_TARGET_HZ) & (bf <= 1.04 * _F_TARGET_HZ)
    beta = float(np.median(bb[sel]))
    f_med = float(np.median(bf[sel]))
    return (beta * 299792458.0 / (2 * np.pi * f_med)) ** 2


@pytest.mark.skipif(
    os.environ.get(_INTENT_ENV, "") != "1",
    reason=(f"真跑集成测试 opt-in：设 {_INTENT_ENV}=1 启用（FDTD 真跑分钟级"
            "且须 varactor 等长跑让轨，不进缺省门 #139/#df4⑥/#261）。"),
)
class TestOpenEMSIntegration:
    def test_mline_anchor_smoke(self, tmp_path):
        from rfauto.adapters.em_solver_base import (
            EMSolverConfig,
            EMSolverType,
            resolve_openems_exe,
        )
        from rfauto.adapters.openems_solver import OpenEMSSolver

        exe = resolve_openems_exe()
        if not Path(exe).exists():
            pytest.skip(f"openEMS 不可达（{exe} 不存在，真机验收需 openEMS）")

        # #261 互斥预检：他轨在跑→skip；探测自身坏→fail（拒绝盲发）
        try:
            foreign = _oe_foreign_running(tmp_path)
        except RuntimeError as exc:
            pytest.fail(str(exc))
        if foreign:
            pytest.skip(f"#261 互斥：他轨 openEMS 在跑，窗口未开：{foreign[:3]}")

        work = tmp_path / "run"
        solver = OpenEMSSolver(EMSolverConfig(
            solver_type=EMSolverType.OPENEMS,
            exe_path=exe,
            working_dir=str(work),
            freq_range_ghz=_FREQ_RANGE,
            mesh_resolution_mm=0.0,  # auto λ_sub/50 官方口径（benchmark 同参）
            # 真跑用例禁缓存命中（缓存秒回不物化产物→产物门必红，ge6 ME-24 实证）：
            extra_params={"solve_timeout_s": 1800.0, "cache": False},
        ))
        assert solver.connect(), "openEMS exe 不可用"
        assert solver.build_geometry(
            {"template": "mline",
             "params": {"w_mm": _W_MM, "line_len_mm": _LINE_LEN_MM}}), (
            "mline build 失败")
        result = solver.solve()
        assert result.success, result.message

        # 产物门
        assert (work / "simulation.py").is_file()
        assert (work / "sparams.csv").is_file()
        assert (work / "port_beta.csv").is_file()

        # 健康门：全带 max|S11| < −10dB（50Ω 匹配线）
        s11 = result.s_params[:, 0, 0]
        s21 = result.s_params[:, 1, 0]
        s11_max_db = float(np.max(20 * np.log10(np.abs(s11) + 1e-12)))
        s21_med_db = float(np.median(20 * np.log10(np.abs(s21) + 1e-12)))

        # β 金标准门：εeff 对 HJ 闭式 ≤3%（#118 独立解析锚）
        from rfauto.core.synthesis import Stackup, forward_z0

        stackup = Stackup.from_materials_yaml(_SUBSTRATE)
        _, eps_hj = forward_z0(_W_MM, _F_TARGET_HZ / 1e9, stackup)
        eps_eff = _beta_eps(work)
        delta_pct = (eps_eff / eps_hj - 1.0) * 100.0

        print(f"[openems] |S11|max={s11_max_db:.2f}dB, "
              f"|S21|med={s21_med_db:.3f}dB, eps_eff={eps_eff:.5f} "
              f"(HJ {eps_hj:.5f}, Δ={delta_pct:+.2f}%), "
              f"wall={result.wall_time_s:.1f}s")
        assert s11_max_db < -10.0, (
            f"|S11|max={s11_max_db:.2f}dB：50Ω 匹配线显著反射=端口/网格判废信号")
        assert delta_pct <= 3.0, (
            f"εeff={eps_eff:.5f} 对 HJ {eps_hj:.5f} 偏 {delta_pct:+.2f}% > 3%")
        assert -1.0 < s21_med_db <= 0.1, (
            f"|S21|med={s21_med_db:.3f}dB 超出匹配线传输窗")

"""F-L.2 Xyce-WSL 真跑集成测试（**opt-in 双门**，照 palace 先例）。

双门（缺一即 skip，unit 门保持封闭 #139 / #df4⑥）：
1. 意图门：env ``RFAUTO_XYCE_IT=1`` 显式启用（wsl.exe 在套件并发/PATH 泄漏
   下可能 9009 假红，不进缺省门——palace RFAUTO_PALACE_ITEST 同款口径）；
2. 机器状态门：win32 + WSL 发行版内 Xyce 可执行可达（缺席 skip 不红）。

判据预声明（与 scripts/xyce_smoke_threeway.py 同源电路）：
- AC：V1-R(10)-L(1m)-C(100n) 低通 1kHz–1MHz DEC 49 = 148 点；频轴端点
  1e3/1e6；逐点 |dB(H)-dB(H_analytic)| ≤ 1e-4（引擎双精度与闭式一致到
  ~1e-7 dB，2026-09-29 预跑实测 max 2.29e-7；1e-4 留打印频率 9 位有效
  数字舍入余量）；传函 CSV 产物在位。
- .tran：RC 阶步（τ=1us），末点 t=10us 闭式 1-exp(-10)=0.9999546，
  容差 5e-4（引擎自适应步长截断误差量级）。
- .DC：分压器扫描末点 = 半压 5.0V（线性直流精确，容差 1e-9）。

绿记录：2026-09-29 首跑全 3 用例（Xyce DEVELOPMENT-202609290042 +
ngspice-45.2，WSL Ubuntu）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

pytestmark = pytest.mark.real_edt

_INTENT_ENV = "RFAUTO_XYCE_IT"


def _xyce_imports():
    from rfauto.adapters import xyce_adapter as mod
    from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType

    return mod, EMSolverConfig, EMSolverType


def _require_reachable(mod) -> None:
    try:
        mod.verify_xyce_reachable(mod.resolve_xyce_exe())
    except FileNotFoundError as exc:
        pytest.skip(f"WSL Xyce 不可达（真机验收需 Xyce-WSL）: {exc}")


@pytest.mark.skipif(sys.platform != "win32",
                    reason="Xyce-WSL 桥仅 Windows 宿主面")
@pytest.mark.skipif(
    os.environ.get(_INTENT_ENV, "") != "1",
    reason=(f"真跑集成测试 opt-in：设 {_INTENT_ENV}=1 启用（依赖宿主 WSL VM "
            "状态，套件内并发/PATH 泄漏可致 wsl.exe 假红；unit 门保持封闭 "
            "#139/#df4⑥）。绿记录 2026-09-29 三用例全过。"),
)
class TestXyceWslIntegration:
    def test_ac_rlc_end_to_end(self, tmp_path):
        mod, EMSolverConfig, EMSolverType = _xyce_imports()
        _require_reachable(mod)
        solver = mod.XyceAdapter(EMSolverConfig(
            solver_type=EMSolverType.XYCE, working_dir=str(tmp_path / "run")))
        assert solver.connect(), solver._last_error
        assert solver.build_geometry({"template": "rlc_lowpass"})
        result = solver.solve(timeout_s=300)
        assert result.success, result.message
        f_hz = result.field_data["freq_hz"]
        h = result.field_data["transfer_h"]
        assert len(f_hz) == 148
        assert f_hz[0] == pytest.approx(1e3) and f_hz[-1] == pytest.approx(1e6)
        h_analytic = mod.rlc_lowpass_transfer(
            f_hz, **mod.RLC_ANCHOR_DEFAULTS)
        db_diff = np.abs(20 * np.log10(np.abs(h))
                         - 20 * np.log10(np.abs(h_analytic)))
        assert float(db_diff.max()) <= 1e-4, f"max|dB diff|={db_diff.max():.3e}"
        assert (Path(solver._config.working_dir) / "xyce_rlc_transfer.csv").is_file()

    def test_tran_rc_step_closed_form(self, tmp_path):
        mod, _cfg, _t = _xyce_imports()
        _require_reachable(mod)
        cir = tmp_path / "rc_it.cir"
        cir.write_bytes(mod.render_rc_tran_netlist().encode("ascii"))
        run = mod.run_xyce(cir, timeout_s=300.0)
        assert run.rc == 0 and not run.timed_out, run.stderr
        prn = mod.read_prn(mod.prn_path_for(cir, ac=False))
        assert prn["indep"] == "TIME"
        t = prn["data"]["TIME"].real
        v = prn["data"]["V(2)"].real
        expected = 1.0 - np.exp(-t / 1e-6)  # τ=RC=1us
        # 末点判读（引擎自适应步长，逐步对照含截断误差，取末点稳态）
        assert v[-1] == pytest.approx(expected[-1], abs=5e-4)
        assert v[-1] < 1.0  # 未到源稳态 1.0 的物理上界

    def test_dc_divider_exact(self, tmp_path):
        mod, _cfg, _t = _xyce_imports()
        _require_reachable(mod)
        cir = tmp_path / "div_it.cir"
        cir.write_bytes(mod.render_divider_dc_netlist().encode("ascii"))
        run = mod.run_xyce(cir, timeout_s=300.0)
        assert run.rc == 0 and not run.timed_out, run.stderr
        prn = mod.read_prn(mod.prn_path_for(cir, ac=False))
        assert prn["indep"] is None
        assert prn["data"]["V(2)"].real[-1] == pytest.approx(5.0, abs=1e-9)

"""P3: ADS 网表生成（B 档, 无 license, skrf 驱动）。

覆盖 generate_netlist 的占位符注入 / SnP 语法 / 无 BOM / 契约端口校验。
parse_dataset 需 ADS 自带 python + 真机 .ds, 放 real_edt。
"""

from pathlib import Path

import numpy as np
import pytest
import skrf

from rfauto.adapters import ads_netlist as an
from rfauto.core.contracts import AdsExchangeContract, TouchstoneContract
from rfauto.core.errors import ContractViolationError

_TPL = Path(__file__).parent.parent.parent / "src" / "rfauto" / "linkage" / "templates" / "ads" / "wilkinson_snp.net"


def _write_snp(tmp_path, n_ports, freq_ghz=(1.5, 3.5, 41)):
    f = skrf.Frequency(freq_ghz[0], freq_ghz[1], freq_ghz[2], "GHz")
    s = np.zeros((f.npoints, n_ports, n_ports), dtype=complex)
    for k in range(f.npoints):
        for i in range(n_ports):
            s[k, i, i] = 0.1
        for i in range(1, n_ports):
            s[k, i, 0] = 1 / np.sqrt(2)
            s[k, 0, i] = 1 / np.sqrt(2)
    net = skrf.Network(frequency=f, s=s, z0=50)
    p = tmp_path / f"t{n_ports}.s{n_ports}p"
    net.write_touchstone(str(p), form="db")
    return p


def _contract(port_order):
    return AdsExchangeContract(touchstone=TouchstoneContract(port_order=port_order))


class TestGenerateNetlist:
    def test_3port_generates_snp_and_ports(self, tmp_path):
        snp = _write_snp(tmp_path, 3)
        out = tmp_path / "nl" / "netlist.txt"
        an.generate_netlist(_TPL, snp, out, _contract(["input", "output_1", "output_2"]))
        text = out.read_text(encoding="ascii")
        assert out.read_bytes()[:3] != b"\xef\xbb\xbf"
        assert "SnP:SNP1  P1 P2 P3 NumPorts=3" in text
        assert 'Type="touchstone"' in text
        assert 'File="' + str(snp.resolve()) + '"' in text
        for i in (1, 2, 3):
            assert f"Port:P{i}  P{i} 0 Num={i} Z=50 Ohm Noise=yes" in text
        assert "Start=1.5 GHz Stop=3.5 GHz Lin=41" in text

    def test_contract_port_mismatch_rejected(self, tmp_path):
        snp = _write_snp(tmp_path, 2)
        out = tmp_path / "nl" / "netlist.txt"
        with pytest.raises(ContractViolationError):
            an.generate_netlist(_TPL, snp, out, _contract(["input", "output_1", "output_2"]))

    def test_2port_contract_ok(self, tmp_path):
        snp = _write_snp(tmp_path, 2)
        out = tmp_path / "nl2" / "netlist.txt"
        an.generate_netlist(_TPL, snp, out, _contract(["input", "output_1"]))
        text = out.read_text(encoding="ascii")
        assert "SnP:SNP1  P1 P2 NumPorts=2" in text
        assert "Port:P1  P1 0 Num=1 Z=50 Ohm" in text
        assert "Port:P2  P2 0 Num=2 Z=50 Ohm" in text
        assert "Port:P3" not in text

    def test_missing_template_raises(self, tmp_path):
        snp = _write_snp(tmp_path, 3)
        out = tmp_path / "nl3" / "netlist.txt"
        with pytest.raises(FileNotFoundError):
            an.generate_netlist(tmp_path / "nope.net", snp, out)


_HB_PAYLOAD = {
    "ok": True, "key": "HB1.HB",
    "harmonics": [
        {"freq_hz": 0.0, "mix": 0, "nodes": {"N_IN": [0.0, 0.0], "N_OUT": [0.0, 0.0]}},
        {"freq_hz": 2e9, "mix": 1, "nodes": {"N_IN": [5.7, -1.78], "N_OUT": [-1.97, -0.26]}},
    ],
    "measurements": {"Pout_W": 0.0994, "Pout_dBm": 19.97, "Gain_dB": -0.03},
    "keys": ["HB1.HB", "aele_0.HB1.HB", "aele_1.HB1.HB", "aele_2.HB1.HB"],
}


class TestParseHbDataset:
    """parse_hb_dataset 的 JSON 管线与诚实报错（ADS 子进程以 monkeypatch 替身,
    真机 .ds 读取由 runs/rm_ads_c14/loadpull_hb/ 与 real_edt 承载）。"""

    @pytest.fixture
    def fake_ads(self, monkeypatch, tmp_path):
        import json
        import subprocess
        from types import SimpleNamespace

        ads_dir = tmp_path / "ADS"
        (ads_dir / "tools" / "python").mkdir(parents=True)
        calls = {}
        state = {"rc": 0, "stdout": json.dumps(_HB_PAYLOAD), "stderr": ""}

        def _run(cmd, **kw):
            calls["cmd"] = [str(c) for c in cmd]
            calls["env"] = kw.get("env", {})
            return SimpleNamespace(returncode=state["rc"], stdout=state["stdout"],
                                   stderr=state["stderr"])

        monkeypatch.setattr(an, "_resolve_ads_dir", lambda _d=None: ads_dir)
        monkeypatch.setattr(subprocess, "run", _run)
        ds = tmp_path / "lp.txt.ds"
        ds.write_bytes(b"\x00")
        return SimpleNamespace(ads_dir=ads_dir, calls=calls, state=state, ds=ds)

    def test_probe_script_is_valid_python(self):
        compile(an._HB_PROBE, "<hb_probe>", "exec")

    def test_payload_roundtrip_and_env(self, fake_ads):
        payload = an.parse_hb_dataset(fake_ads.ds)
        assert payload["key"] == "HB1.HB"
        assert payload["harmonics"][1]["mix"] == 1
        assert payload["measurements"]["Pout_dBm"] == 19.97
        cmd = fake_ads.calls["cmd"]
        assert cmd[0].endswith("python.exe") and cmd[1].endswith(".py")
        assert cmd[2] == str(fake_ads.ds) and cmd[3] == str(fake_ads.ads_dir)
        env = fake_ads.calls["env"]
        assert env["HPEESOF_DIR"] == str(fake_ads.ads_dir)
        assert env["PATH"].startswith(str(fake_ads.ads_dir / "bin"))

    def test_missing_dataset_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            an.parse_hb_dataset(tmp_path / "nope.ds")

    def test_nonzero_exit_is_simulation_error(self, fake_ads):
        from rfauto.core.errors import SimulationFailedError

        fake_ads.state.update(rc=3, stderr="ImportError: keysight")
        with pytest.raises(SimulationFailedError, match="exit 3"):
            an.parse_hb_dataset(fake_ads.ds)

    def test_no_hb_block_is_simulation_error(self, fake_ads):
        import json

        from rfauto.core.errors import SimulationFailedError

        fake_ads.state.update(stdout=json.dumps({"ok": False, "error": "no HB block"}))
        with pytest.raises(SimulationFailedError, match="no HB block"):
            an.parse_hb_dataset(fake_ads.ds)

    def test_non_json_output_is_simulation_error(self, fake_ads):
        from rfauto.core.errors import SimulationFailedError

        fake_ads.state.update(stdout="Traceback garbage")
        with pytest.raises(SimulationFailedError, match="非 JSON"):
            an.parse_hb_dataset(fake_ads.ds)

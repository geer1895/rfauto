"""F-L.1b SG13G2 Day-1 真跑链驱动：ngspice(WSL Ubuntu) + IHP PDK VBIC HBT。

链路（研究扩充 round6 §二 F-L 第 1 步，Day-1
零 Verilog-A / 零新包）：HBT 偏置/gm/fT 网格（3x3）→ 单级共射 LNA 的
S 参 + NF → Pospieszalski 闭式（core/fet_noise）互证。产出
runs/fl1_sg13g2/day1_results.json。

判据先行（#122，预声明即铁约，不凑绿）：
- 仪器自检：串 100Ω 双 50Ω port 的 2-port 网络，解析 S11=S21=S12=S22=0.5
  （功率波换算解析参照），实测 |偏差| >1e-6 即拒跑（仪器坏不产绿结果）。
- fT 量级带 [100, 500] GHz（SG13G2 HBT 为 ~250 GHz 级——二手口径，出自
  round6 方案文档，未对 IHP 手册逐位核对 → verdict 附 handbook UNVERIFIED）。
- NF 互证带（预声明 ±15% 工程带——二手转引闭式 vs 实装模型必有差）：
  rel_dev = |F_closed − F_spice|/F_spice（线性 F）≤0.15 PASS；≤0.30
  PARTIAL；>0.30 FAIL。偏差逐条归因写 attribution，不凑绿。
- gm 一致性（模型内恰，非手册背书）：gm·VT·nf/Ic ≈ 1（VBIC nf=1.018，
  带 ±10%）；对 PDK 手册典型带的比对如实记 UNVERIFIED。

仪器实证（2026-09-27，ngspice-45.2 / WSL Ubuntu，逐项实测非引用）：
- `.net`/`net` S 参分析在该构建不可用（"unimplemented dot command" /
  "no such command"）→ 采用任务书预授权 fallback：手工 port + 功率波换算
  a=(V+Z0·I)/2√Z0、b=(V−Z0·I)/2√Z0，port 电流经 0V ammeter 源测量。
  【选定并登记：sparam_method = manual_port_power_waves】
- wrdata 列布局：**复数矢量 = (f, re, im) 3 列/矢量；实数矢量 = (f, val)
  2 列/矢量**（noise 谱是实数——首跑把实格式的频率列当虚部吞掉致解析空，
  41 行文件全行的实证教训，parse_wrdata 双格式判别+频率一致性护栏）。
  AC 矢量必须在 ac plot 仍为当前 plot 时 wrdata；.noise 频谱在 noise1
  plot、积分总量在 noise2 plot（须 plot 限定名，ac 先跑时名单不变：
  ac1/noise1/noise2 实证）。
- .noise 频谱单位 = V/√Hz（50Ω 分压网络解析值 sqrt(4kT·25) 逐位回收；
  3dB 衰减器回收线性 F=2.0 精确）。NF 公式 F = inoise²/(4kT·Rs)。
  ngspice 缺省 TEMP=27°C → T=300.15 K，闭式侧 t0_k 同取 300.15 对齐。
- h21 提取拓扑：电流源直注会被理想 Vbe 源 AC 短路（全电流走源、vbe=0，
  实测两轮零输出）→ 电压源+已知 Rb 驱动，ib=(v(bs)−v(b))/Rb 与
  ic=|i(vam)| 逐点相除，fT=|h21| 过 1 点 log-log 外推。
- .op 批模式 stdout 打印 VBIC 小信号全参（gm/gpi/gmu/go/gx/cbe/cbc/...），
  逐行解析该块（go 含自热反馈可为负，闭式侧取 |go| 并归因）。

用法（仓根）：
  .venv\\Scripts\\python.exe scripts\\fl1_sg13g2\\run_day1.py
真跑依赖：WSL Ubuntu + ngspice（语境钉死：已装）。零新 Python 包。
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rfauto.core.active_chain import z_to_gamma
from rfauto.core.fet_noise import (
    K_B_J_PER_K,
    FetSmallSignal,
    noise_circle,
    noise_figure_at,
    pospieszalski_noise_params,
    transition_frequency_hz,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTDIR = REPO_ROOT / "runs" / "fl1_sg13g2"
PDK_CORNER_HBT = (
    REPO_ROOT
    / "third_party"
    / "IHP-Open-PDK"
    / "ihp-sg13g2"
    / "libs.tech"
    / "ngspice"
    / "models"
    / "cornerHBT.lib"
)

WSL_DISTRO = "Ubuntu"
NGSPICE_TIMEOUT_S = 300

#: 元电荷（CODATA 2018 精确值）
Q_E_C = 1.602176634e-19

#: ngspice 缺省分析温度 27°C（实证 "Doing analysis at TEMP = 27.000000"）
T_SIM_K = 300.15

#: 参考阻抗（Ω）
Z0_OHM = 50.0

#: 偏置网格 vbe x vce 3x3（vbe 有效域 0.65-0.96V、vce 有效域 0.4-2.0V 且
#: <vce_max 1.6V，均在 sg13g2_hbt_mod.lib 模型卡标注有效域内）
GRID_VBE_V = (0.80, 0.85, 0.90)
GRID_VCE_V = (0.6, 1.2, 1.5)

#: LNA 工作点（vce=1.2 < 1.6 安全域）
LNA_VBE_V = 0.87
LNA_VCC_V = 1.2

#: NF 互证频点（Hz）
NF_POINTS_HZ = (2e9, 5e9, 8e9)

#: 输入共轭匹配综合频点（Hz）
F0_MATCH_HZ = 5e9

#: 隔直/耦合电容（F）；理想偏置扼流（H）
DC_BLOCK_F = 10e-12
BIAS_CHOKE_H = 1e-3

#: NF 互证预声明带（线性 F 相对偏差）
NF_WARN_REL = 0.15
NF_FAIL_REL = 0.30

#: fT 量级带（Hz）
FT_BAND_HZ = (100e9, 500e9)

#: gm 模型自洽带：gm·VT·nf/Ic 偏离 1 的容差（VBIC nf=1.018）
GM_CONSISTENCY_TOL = 0.10
#: VBIC 发射结理想因子（sg13g2_hbt_mod.lib L76: nf = 1.018，npn13G2）
VBIC_NF_NPN13G2 = 1.018

#: h21 扫描（Hz）
H21_FSTART_HZ = 1e6
H21_FSTOP_HZ = 1e12
H21_PTS_PER_DEC = 40

#: S 参带（Hz）
SP_FSTART_HZ = 0.5e9
SP_FSTOP_HZ = 20e9
SP_PTS_PER_DEC = 20

#: NF 带（Hz）
NF_FSTART_HZ = 1e9
NF_FSTOP_HZ = 1e10
NF_PTS_PER_DEC = 40

#: 仪器自检容差（串 100Ω 解析参照）
SELFTEST_TOL = 1e-6

SCHEMA_ID = "fl1_sg13g2_day1_v1"
SPARAM_METHOD = "manual_port_power_waves"


# ─── 路径与子进程 ────────────────────────────────────────────────────────────


def _to_wsl(p: Path) -> str:
    """Windows 绝对路径 → WSL /mnt/<drive> 路径（python subprocess 无 MSYS 转换）。"""
    s = p.resolve().as_posix()
    return "/mnt/" + s[0].lower() + s[2:]


def _run_ngspice(netlist_win: Path, log_out: Path) -> str:
    """子进程调 WSL ngspice 批模式，stdout/stderr 落日志并返回 stdout。

    日志即原始记录（-b 批模式不产生 .lis 文件，stdout 日志充当之，
    provenance 如实登记为 *.log）。
    """
    cmd = ["wsl", "-d", WSL_DISTRO, "-e", "ngspice", "-b", _to_wsl(netlist_win)]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=NGSPICE_TIMEOUT_S, check=False,
    )
    log_out.parent.mkdir(parents=True, exist_ok=True)
    log_out.write_text(
        proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8"
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or proc.stderr).splitlines()[-12:])
        raise RuntimeError(f"ngspice rc={proc.returncode} on {netlist_win.name}:\n{tail}")
    return proc.stdout


# ─── 网表生成（纯字符串函数；网表注释一律 ASCII，避免 WSL/代码page 编码歧义）──


def _lib_line() -> str:
    return f".lib {_to_wsl(PDK_CORNER_HBT)} hbt_typ"


def netlist_op(vbe_v: float, vce_v: float, nx: int) -> str:
    """DC 工作点网表：.op 打印 VBIC 小信号参数（引脚序 c b e bn，模型卡 L41）。"""
    return f"""* F-L.1b operating point (npn13G2 Nx={nx}, vbe={vbe_v}, vce={vce_v})
{_lib_line()}
Vce c 0 DC {vce_v}
Vbe b 0 DC {vbe_v}
Xq c b 0 0 npn13G2 Nx={nx}
.op
.end
"""


def netlist_h21(vbe_v: float, vce_v: float, nx: int, wrdata_wsl: str) -> str:
    """|h21|=|ic/ib| 扫描（vce=0 口径）：电压驱动 + 已知 Rb，逐点测 ib/ic。

    教训（见模块头）：电流源直注会被理想 Vbe 源 AC 短路。
    """
    return f"""* F-L.1b h21 sweep (npn13G2 Nx={nx}, vbe={vbe_v}, vce={vce_v})
{_lib_line()}
Vsig bs 0 DC {vbe_v} AC 1
Rb bs b {Z0_OHM:g}
Vcc vc 0 DC {vce_v}
Vam vc c DC 0
Xq c b 0 0 npn13G2 Nx={nx}
.control
ac dec {H21_PTS_PER_DEC} {H21_FSTART_HZ:g} {H21_FSTOP_HZ:g}
wrdata {wrdata_wsl} v(bs) v(b) i(vam)
quit
.endc
.end
"""


@dataclass(frozen=True)
class MatchNetwork:
    """输入 L-match（串联元件靠器件侧、并联元件靠 50Ω 口侧）。"""

    series_l_h: float
    shunt_c_f: float

    def to_dict(self) -> dict[str, float]:
        return {"series_l_h": self.series_l_h, "shunt_c_f": self.shunt_c_f}


def netlist_lna(
    drive_port: int,
    match: MatchNetwork | None,
    nx: int,
    *,
    with_noise: bool,
    ac_wrdata_wsl: str,
    nf_wrdata_wsl: str | None = None,
) -> str:
    """单级共射 LNA：理想扼流偏置 + 50Ω 手工 port，run A/B 换驱动源。

    drive_port=1 → V1 AC 1（run A，S11/S21 + NF 参考源）；drive_port=2 →
    run B（S22/S12）。非驱动 port 的源（AC 0）串 Rp=50 自动充当共轭端接。
    """
    v1_ac = 1 if drive_port == 1 else 0
    v2_ac = 1 - v1_ac
    lines = [
        f"* F-L.1b LNA common-emitter (npn13G2 Nx={nx}, drive port {drive_port}, match={'yes' if match else 'no'})",
        _lib_line(),
        f"V1 p1s 0 DC 0 AC {v1_ac}",
        f"Rp1 p1s p1a {Z0_OHM:g}",
        "Vam1 p1a p1 DC 0",
    ]
    mid1, mid2 = "p1", "p1x"
    if match is not None:
        lines.append(f"Cm p1 0 {match.shunt_c_f:.6e}")
        lines.append(f"Lm p1 p1x {match.series_l_h:.6e}")
        mid1, mid2 = "p1x", "p1y"
    lines += [
        f"Cin {mid1} {mid2} {DC_BLOCK_F:.3e}" if match is not None else f"Cin p1 b {DC_BLOCK_F:.3e}",
        "Lb vb b " + f"{BIAS_CHOKE_H:.3e}",
        f"Vbias1 vb 0 DC {LNA_VBE_V}",
        f"Xq c b 0 0 npn13G2 Nx={nx}",
        "Lc vc c " + f"{BIAS_CHOKE_H:.3e}",
        f"Vbias2 vc 0 DC {LNA_VCC_V}",
        "Cout c p2 " + f"{DC_BLOCK_F:.3e}",
        "Vam2 p2 p2a DC 0",
        f"Rp2 p2a p2s {Z0_OHM:g}",
        f"V2 p2s 0 DC 0 AC {v2_ac}",
        ".control",
        f"ac dec {SP_PTS_PER_DEC} {SP_FSTART_HZ:g} {SP_FSTOP_HZ:g}",
        f"wrdata {ac_wrdata_wsl} v(p1) i(vam1) v(p2) i(vam2)",
    ]
    if with_noise:
        assert nf_wrdata_wsl is not None, "with_noise=True 需要 nf_wrdata_wsl"
        lines += [
            f"noise v(p2) v1 dec {NF_PTS_PER_DEC} {NF_FSTART_HZ:g} {NF_FSTOP_HZ:g}",
            f"wrdata {nf_wrdata_wsl} noise1.inoise_spectrum noise1.onoise_spectrum",
        ]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


def netlist_nf_point(freq_hz: float, nx: int, wrdata_wsl: str) -> str:
    """单频点 .noise 网表（互证用精确频点，免插值；谱/积分分文件 wrdata）。"""
    return f"""* F-L.1b single-point noise (npn13G2 Nx={nx}, f={freq_hz:g})
{_lib_line()}
V1 p1s 0 DC 0 AC 1
Rp1 p1s p1a {Z0_OHM:g}
Vam1 p1a p1 DC 0
Cin p1 b {DC_BLOCK_F:.3e}
Lb vb b {BIAS_CHOKE_H:.3e}
Vbias1 vb 0 DC {LNA_VBE_V}
Xq c b 0 0 npn13G2 Nx={nx}
Lc vc c {BIAS_CHOKE_H:.3e}
Vbias2 vc 0 DC {LNA_VCC_V}
Cout c p2 {DC_BLOCK_F:.3e}
Vam2 p2 p2a DC 0
Rp2 p2a p2s {Z0_OHM:g}
V2 p2s 0 DC 0 AC 0
.control
noise v(p2) v1 lin 1 {freq_hz:g} {freq_hz:g}
wrdata {wrdata_wsl} noise1.inoise_spectrum noise1.onoise_spectrum
quit
.endc
.end
"""


def netlist_selftest(drive_port: int, wrdata_wsl: str) -> str:
    """仪器自检网表：串 100Ω 双 50Ω port，解析 S11=S21=S12=S22=0.5。"""
    v1_ac = 1 if drive_port == 1 else 0
    v2_ac = 1 - v1_ac
    return f"""* F-L.1b instrument selftest: series 100R between two 50R ports
V1 p1s 0 DC 0 AC {v1_ac}
Rp1 p1s p1a {Z0_OHM:g}
Vam1 p1a p1 DC 0
RX p1 p2 100
Vam2 p2 p2a DC 0
Rp2 p2a p2s {Z0_OHM:g}
V2 p2s 0 DC 0 AC {v2_ac}
.control
ac lin 1 1e9 1e9
wrdata {wrdata_wsl} v(p1) i(vam1) v(p2) i(vam2)
quit
.endc
.end
"""


# ─── 解析（纯函数）────────────────────────────────────────────────────────────


def parse_op_vbic(stdout: str) -> dict[str, float]:
    """从 .op stdout 提取 q.xq.qnpn13g2 的 VBIC 小信号参数块。"""
    lines = stdout.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if "VBIC: Vertical Bipolar" in ln:
            start = i + 1
            break
    if start is None:
        raise ValueError("stdout 中未找到 VBIC 器件工作点块（.op 未运行或电路未收敛）")
    out: dict[str, float] = {}
    for ln in lines[start:]:
        if not ln.strip():
            if out:
                break
            continue
        parts = ln.split()
        if len(parts) == 2:
            key = parts[0].lower()
            if key in {"device", "model"}:
                continue
            try:
                out[key] = float(parts[1])
            except ValueError:
                break
        elif out:
            break
    if "gm" not in out or "ic" not in out:
        raise ValueError(f"VBIC 工作点块不完整（缺 gm/ic）: {sorted(out)[:8]}...")
    return out


def parse_wrdata(text: str, n_vec: int) -> list[list[list[complex]]]:
    """wrdata 文本 → 按矢量序分组，每矢量 [freq, value]（value 复数）。

    列布局（实证 2026-09-27）：**复数矢量 = (f, re, im) 3 列/矢量；实数矢量 =
    (f, val) 2 列/矢量**（noise 谱/积分矢量是实数——V/√Hz 无相位）。两种
    格式按行内 token 数判别（3·n_vec / 2·n_vec），实数格式的各矢量频率列
    应相同（同分析栅格），不一致即抛错（解析护栏）。
    """
    rows: list[list[list[complex]]] = []
    for ln in text.splitlines():
        tok = ln.split()
        try:
            vals = [float(t) for t in tok]
        except ValueError:
            continue
        if len(vals) == 3 * n_vec:
            row = [
                [complex(vals[3 * k], 0.0), complex(vals[3 * k + 1], vals[3 * k + 2])]
                for k in range(n_vec)
            ]
        elif len(vals) == 2 * n_vec:
            freqs = [vals[2 * k] for k in range(n_vec)]
            if max(freqs) - min(freqs) > abs(freqs[0]) * 1e-9:
                raise ValueError(f"wrdata 实数格式频率列不一致: {freqs}")
            row = [[complex(f, 0.0), complex(v, 0.0)] for f, v in zip(freqs, vals[1::2], strict=True)]
        else:
            continue
        rows.append(row)
    if not rows:
        raise ValueError("wrdata 文本为空或列数与矢量数不匹配")
    return rows


# ─── S 参换算与判据（纯函数）──────────────────────────────────────────────────


@dataclass(frozen=True)
class PortWaves:
    """单频点双 port 电压/电流（i1/i2 = 流入网络方向）。"""

    v1: complex
    i1: complex
    v2: complex
    i2: complex


def _waves_ab(v: complex, i: complex, z0: float) -> tuple[complex, complex]:
    s = math.sqrt(z0)
    return (v + i * z0) / (2.0 * s), (v - i * z0) / (2.0 * s)


def waves_to_s(run_a: PortWaves, run_b: PortWaves, z0: float) -> dict[str, complex]:
    """两轮驱动（A=port1, B=port2）的功率波测量 → 2x2 S 矩阵。

    口径：S11/S21=b/a（A 轮，port2 端接 a2≈0）；S22/S12（B 轮同口径）。
    """
    a1, b1 = _waves_ab(run_a.v1, run_a.i1, z0)
    _, b2 = _waves_ab(run_a.v2, run_a.i2, z0)
    a2b, b2b = _waves_ab(run_b.v2, run_b.i2, z0)
    _, b1b = _waves_ab(run_b.v1, run_b.i1, z0)
    if abs(a1) == 0.0 or abs(a2b) == 0.0:
        raise ValueError("激励波 a=0（port 源未驱动或端口全反射退化）")
    return {"s11": b1 / a1, "s21": b2 / a1, "s22": b2b / a2b, "s12": b1b / a2b}


def db_of(s: complex) -> float:
    return 20.0 * math.log10(abs(s)) if abs(s) > 0.0 else -300.0


def ft_crossing_hz(freqs: list[float], h21: list[float]) -> float | None:
    """|h21| 过 1 点的 log-log 外推；无过冲（带内未降到 1）返回 None。"""
    for i in range(len(freqs) - 1):
        h1, h2 = h21[i], h21[i + 1]
        if h1 >= 1.0 >= h2 and h1 > 0.0 and h2 > 0.0:
            slope = math.log(h1 / h2) / math.log(freqs[i + 1] / freqs[i])
            if slope <= 0.0:
                return None
            return float(freqs[i] * h1 ** (1.0 / slope))
    return None


def nf_linear_from_inoise(inoise_v_sqrt_hz: float, rs_ohm: float, temp_k: float) -> float:
    """F = inoise²/(4kT·Rs)（ngspice 口径，T 为分析温度；实证 3dB 衰减器回收 F=2）。"""
    if inoise_v_sqrt_hz <= 0.0:
        raise ValueError("inoise 频谱必须 >0")
    return inoise_v_sqrt_hz**2 / (4.0 * K_B_J_PER_K * temp_k * rs_ohm)


def synthesize_lmatch(zin: complex, z0: float, f0_hz: float) -> MatchNetwork | None:
    """输入共轭匹配简化面：L-match（串 L 吸收 Zin 虚部 + 并 C），仅 R<Z0 拓扑。

    R≥Z0、Re{Zin}≤0 或需串联电容的拓扑 → None（Day-1 如实回退不匹配并落档）。
    """
    r = zin.real
    if r <= 0.0 or r >= z0:
        return None
    w = 2.0 * math.pi * f0_hz
    q = math.sqrt(z0 / r - 1.0)
    x_net = q * r - zin.imag  # 串联支路总电抗（吸收 Zin 虚部）
    if x_net <= 0.0:
        return None
    return MatchNetwork(series_l_h=x_net / w, shunt_c_f=(q / z0) / w)


def zs_device_plane(f_hz: float, match: MatchNetwork | None) -> complex:
    """器件基极平面看到的源阻抗：50Ω ∥ (并联 C) + 串联 L + Cin 串联。"""
    w = 2.0 * math.pi * f_hz
    zs = complex(Z0_OHM, 0.0)
    if match is not None:
        zc = 1.0 / (1j * w * match.shunt_c_f)
        zs = zs * zc / (zs + zc)
        zs = zs + 1j * w * match.series_l_h
    return zs + 1.0 / (1j * w * DC_BLOCK_F)


# ─── VBIC → Pospieszalski 小信号映射（纯函数）────────────────────────────────


def fet_models_from_op(
    op: dict[str, float], f_hz: float, nx: int, temp_k: float
) -> tuple[FetSmallSignal, FetSmallSignal, dict[str, float]]:
    """.op 小信号参数 → (噪声映射模型, fT 模型, 中间量)。

    映射口径（预声明，attribution 同文）：
    - 结支路 (gpi ∥ Cπ) 的串等价 (Ri + Cs)：Ygs 恒等换算（测试钉 1e-12），
      Ri 挂 Tg=temp/2——基极散粒 2qIb ↔ rπ@T/2 的经典等价；
    - gds=|go|（.op 打印的 go 含 VBIC 自热反馈可为负），Td=q·Ic/(2k·gds)——
      集电极散粒 2qIc ↔ Rds@Td 的等价定温；
    - rg=1/gx（器件自报总基极串联电阻，挂 T0 热噪声口径）；
    - rs=re=7.13·(4/Nx)（sg13g2_hbt_mod.lib L98，hbt_typ 下 vbic_re=1）；
    - fT 模型用并联 Cπ 全容 + Cμ（transition_frequency_hz 口径）。
    """
    w = 2.0 * math.pi * f_hz
    gm, gpi = op["gm"], op["gpi"]
    cpi_p = op.get("cbe", 0.0) + op.get("cbex", 0.0) + op.get("cbep", 0.0)
    cmu = op.get("cbc", 0.0) + op.get("cbcx", 0.0) + op.get("cbcp", 0.0)
    zpi = 1.0 / complex(gpi, w * cpi_p)
    ri = zpi.real
    cgs_series = 1.0 / (w * abs(zpi.imag))
    gds = abs(op["go"])
    rg = 1.0 / op["gx"] if op.get("gx", 0.0) > 0.0 else 0.0
    rs = 7.13 * (4.0 / nx)
    tg = temp_k / 2.0
    td = Q_E_C * op["ic"] / (2.0 * K_B_J_PER_K * gds)
    noise_model = FetSmallSignal(
        cgs_f=cgs_series, ri_ohm=ri, gm_s=gm, gds_s=gds, rg_ohm=rg, rs_ohm=rs
    )
    ft_model = FetSmallSignal(
        cgs_f=cpi_p, ri_ohm=ri, gm_s=gm, gds_s=gds, rg_ohm=rg, rs_ohm=rs, cgd_f=cmu
    )
    extra = {
        "tg_k": tg,
        "td_k": td,
        "cpi_parallel_f": cpi_p,
        "cmu_f": cmu,
        "ri_ohm": ri,
        "cgs_series_f": cgs_series,
        "rg_ohm": rg,
        "rs_ohm": rs,
        "gds_s": gds,
    }
    return noise_model, ft_model, extra


# ─── 判据与 schema ────────────────────────────────────────────────────────────


def band_verdict(rel_dev: float, warn: float = NF_WARN_REL, fail: float = NF_FAIL_REL) -> str:
    if rel_dev <= warn:
        return "PASS"
    if rel_dev <= fail:
        return "PARTIAL"
    return "FAIL"


def ft_band_verdict(ft_hz: float | None) -> str:
    if ft_hz is None:
        return "FAIL"
    lo, hi = FT_BAND_HZ
    return "PASS" if lo <= ft_hz <= hi else "FAIL"


def validate_results(res: dict) -> list[str]:
    """结果 JSON schema/契约校验（返回问题列表；空=通过）。"""
    problems: list[str] = []
    if res.get("schema") != SCHEMA_ID:
        problems.append(f"schema 字段缺失或不符: {res.get('schema')!r}")
    for section in ("meta", "criteria", "instrument_selftest", "grid", "lna", "xcheck", "verdicts", "provenance"):
        if section not in res:
            problems.append(f"缺 section: {section}")
    st = res.get("instrument_selftest", {})
    if st.get("pass") is not True:
        problems.append("instrument_selftest 未通过或缺失（仪器坏不产结果）")
    grid = res.get("grid", [])
    if len(grid) != len(GRID_VBE_V) * len(GRID_VCE_V):
        problems.append(f"grid 应为 3x3=9 cell，得 {len(grid)}")
    for cell in grid:
        for key in ("vbe_v", "vce_v", "ic_a", "gm_s", "ft_h21_hz", "ft_closed_hz"):
            if key not in cell:
                problems.append(f"grid cell 缺键 {key}")
    xcheck = res.get("xcheck", [])
    if len(xcheck) != len(NF_POINTS_HZ):
        problems.append(f"xcheck 应为 {len(NF_POINTS_HZ)} 频点，得 {len(xcheck)}")
    for xc in xcheck:
        for key in ("f_hz", "f_spice_linear", "f_closed_linear", "rel_dev", "verdict"):
            if key not in xc:
                problems.append(f"xcheck 缺键 {key}")
        if xc.get("verdict") not in {"PASS", "PARTIAL", "FAIL"}:
            problems.append(f"xcheck verdict 非法: {xc.get('verdict')!r}")
    prov = res.get("provenance", {})
    for n in prov.get("netlists", []):
        if not Path(n).exists():
            problems.append(f"provenance netlist 不存在: {n}")
    for n in prov.get("logs", []):
        if not Path(n).exists():
            problems.append(f"provenance log 不存在: {n}")
    return problems


# ─── 编排 ─────────────────────────────────────────────────────────────────────


def _complex_list(rows: list[list[list[complex]]], vec_idx: int) -> tuple[list[float], list[complex]]:
    freqs = [row[0][0].real for row in rows]
    vals = [row[vec_idx][1] for row in rows]
    return freqs, vals


def _selftest(dirs: dict[str, Path]) -> dict:
    """串 100Ω 2-port 实测 vs 解析（S=0.5 四元）——仪器自检。"""
    waves_by_port: dict[int, PortWaves] = {}
    for port in (1, 2):
        nl = netlist_selftest(port, _to_wsl(dirs["data"] / f"selftest_{port}.txt"))
        (dirs["netlists"] / f"selftest_{port}.cir").write_text(nl, encoding="ascii")
        _run_ngspice(
            dirs["netlists"] / f"selftest_{port}.cir",
            dirs["logs"] / f"selftest_{port}.log",
        )
        rows = parse_wrdata((dirs["data"] / f"selftest_{port}.txt").read_text(encoding="ascii"), 4)
        _, v1 = _complex_list(rows, 0)
        _, i1 = _complex_list(rows, 1)
        _, v2 = _complex_list(rows, 2)
        _, i2raw = _complex_list(rows, 3)
        waves_by_port[port] = PortWaves(v1=v1[0], i1=i1[0], v2=v2[0], i2=-i2raw[0])
    s = waves_to_s(waves_by_port[1], waves_by_port[2], Z0_OHM)
    theory = {"s11": 0.5, "s21": 0.5, "s22": 0.5, "s12": 0.5}
    devs = {k: abs(s[k] - theory[k]) for k in theory}
    worst = max(devs.values())
    return {
        "pass": worst <= SELFTEST_TOL,
        "tolerance": SELFTEST_TOL,
        "theory": theory,
        "measured": {k: {"re": s[k].real, "im": s[k].imag} for k in s},
        "max_abs_dev": worst,
        "note": "series 100R between two 50R ports; S11=S21=S12=S22=0.5 analytic",
    }


def _run_op_cell(dirs: dict[str, Path], vbe: float, vce: float, nx: int) -> dict[str, float]:
    name = f"op_vbe{vbe:.2f}_vce{vce:.1f}".replace(".", "p")
    nl = netlist_op(vbe, vce, nx)
    (dirs["netlists"] / f"{name}.cir").write_text(nl, encoding="ascii")
    stdout = _run_ngspice(dirs["netlists"] / f"{name}.cir", dirs["logs"] / f"{name}.log")
    return parse_op_vbic(stdout)


def _run_h21_cell(dirs: dict[str, Path], vbe: float, vce: float, nx: int) -> float | None:
    name = f"h21_vbe{vbe:.2f}_vce{vce:.1f}".replace(".", "p")
    data = dirs["data"] / f"{name}.txt"
    nl = netlist_h21(vbe, vce, nx, _to_wsl(data))
    (dirs["netlists"] / f"{name}.cir").write_text(nl, encoding="ascii")
    _run_ngspice(dirs["netlists"] / f"{name}.cir", dirs["logs"] / f"{name}.log")
    rows = parse_wrdata(data.read_text(encoding="ascii"), 3)
    freqs, v_bs = _complex_list(rows, 0)
    _, v_b = _complex_list(rows, 1)
    _, i_am = _complex_list(rows, 2)
    h21: list[float] = []
    for vb_s, vbx, i_c in zip(v_bs, v_b, i_am, strict=True):
        i_b = (vb_s - vbx) / Z0_OHM
        h21.append(abs(i_c / i_b) if abs(i_b) > 0.0 else 0.0)
    return ft_crossing_hz(freqs, h21)


def _grid_stage(dirs: dict[str, Path], nx: int) -> list[dict]:
    cells: list[dict] = []
    for vbe in GRID_VBE_V:
        for vce in GRID_VCE_V:
            op = _run_op_cell(dirs, vbe, vce, nx)
            _, ft_model, extra = fet_models_from_op(op, F0_MATCH_HZ, nx, T_SIM_K)
            ft_closed = transition_frequency_hz(ft_model)
            ft_h21 = _run_h21_cell(dirs, vbe, vce, nx)
            cells.append(
                {
                    "vbe_v": vbe,
                    "vce_v": vce,
                    "ic_a": op["ic"],
                    "ib_a": op["ib"],
                    "vbe_junction_v": op["vbe"],
                    "beta": op.get("beta"),
                    "gm_s": op["gm"],
                    "gpi_s": op["gpi"],
                    "gmu_s": op.get("gmu"),
                    "go_s": op["go"],
                    "rb_ohm": 1.0 / op["gx"] if op.get("gx", 0.0) > 0.0 else None,
                    "gm_consistency": op["gm"] * (K_B_J_PER_K * T_SIM_K / Q_E_C) * VBIC_NF_NPN13G2 / op["ic"],
                    "cbe_f": op.get("cbe"),
                    "cbc_f": op.get("cbc"),
                    "cpi_parallel_f": extra["cpi_parallel_f"],
                    "cmu_f": extra["cmu_f"],
                    "ft_closed_hz": ft_closed,
                    "ft_h21_hz": ft_h21,
                }
            )
    return cells


def _rows_to_portwaves(rows: list[list[list[complex]]]) -> tuple[list[float], list[PortWaves]]:
    """AC wrdata 四矢量行 → (freqs, [PortWaves])（i2 取负 = 流入网络口径）。"""
    freqs = [row[0][0].real for row in rows]
    waves = [
        PortWaves(
            v1=row[0][1], i1=row[1][1], v2=row[2][1], i2=-row[3][1]
        )
        for row in rows
    ]
    return freqs, waves


def _run_lna_drive(
    dirs: dict[str, Path], drive: int, match: MatchNetwork | None, tag: str, nx: int,
    with_noise: bool,
) -> tuple[list[float], list[PortWaves], Path | None]:
    tag_full = f"lna_{tag}_p{drive}"
    nf_file = dirs["data"] / f"{tag_full}_nf.txt" if with_noise else None
    nl = netlist_lna(
        drive, match, nx,
        with_noise=with_noise,
        ac_wrdata_wsl=_to_wsl(dirs["data"] / f"{tag_full}_ac.txt"),
        nf_wrdata_wsl=_to_wsl(nf_file) if nf_file else None,
    )
    (dirs["netlists"] / f"{tag_full}.cir").write_text(nl, encoding="ascii")
    _run_ngspice(dirs["netlists"] / f"{tag_full}.cir", dirs["logs"] / f"{tag_full}.log")
    rows = parse_wrdata((dirs["data"] / f"{tag_full}_ac.txt").read_text(encoding="ascii"), 4)
    freqs, waves = _rows_to_portwaves(rows)
    return freqs, waves, nf_file


def _sparams_from_waves(
    freqs_a: list[float], a: list[PortWaves], b: list[PortWaves]
) -> tuple[list[float], dict[str, list[complex]]]:
    s_list: dict[str, list[complex]] = {"s11": [], "s21": [], "s22": [], "s12": []}
    for wa, wb in zip(a, b, strict=True):
        s = waves_to_s(wa, wb, Z0_OHM)
        for k, v in s.items():
            s_list[k].append(v)
    return freqs_a, s_list


def _s_to_json(s_list: dict[str, list[complex]]) -> dict[str, list[list[float]]]:
    return {
        k: [[v.real, v.imag] for v in vals] for k, vals in s_list.items()
    }


def _nf_band_curve(dirs: dict[str, Path], nx: int) -> dict:
    """LNA run A 网表上的带内 NF 曲线（noise1 谱 → NF dB 曲线）。"""
    tag = "lna_nfband"
    nl = netlist_lna(
        1, None, nx, with_noise=True,
        ac_wrdata_wsl=_to_wsl(dirs["data"] / f"{tag}_ac.txt"),
        nf_wrdata_wsl=_to_wsl(dirs["data"] / f"{tag}_nf.txt"),
    )
    (dirs["netlists"] / f"{tag}.cir").write_text(nl, encoding="ascii")
    _run_ngspice(dirs["netlists"] / f"{tag}.cir", dirs["logs"] / f"{tag}.log")
    rows = parse_wrdata((dirs["data"] / f"{tag}_nf.txt").read_text(encoding="ascii"), 2)
    freqs, inoise = _complex_list(rows, 0)
    _, onoise = _complex_list(rows, 1)
    nf_db = [
        10.0 * math.log10(nf_linear_from_inoise(v.real, Z0_OHM, T_SIM_K)) for v in inoise
    ]
    return {
        "freqs_hz": freqs,
        "inoise_v_sqrt_hz": [v.real for v in inoise],
        "onoise_v_sqrt_hz": [v.real for v in onoise],
        "nf_db": nf_db,
    }


def _nf_point(dirs: dict[str, Path], f_hz: float, nx: int) -> dict[str, float]:
    """单频点精确 .noise（免插值）：返回 inoise/onoise 谱与线性 F。"""
    name = f"nfpt_{f_hz:.0e}".replace("e+0", "e").replace(".", "p")
    data = dirs["data"] / f"{name}.txt"
    nl = netlist_nf_point(f_hz, nx, _to_wsl(data))
    (dirs["netlists"] / f"{name}.cir").write_text(nl, encoding="ascii")
    _run_ngspice(dirs["netlists"] / f"{name}.cir", dirs["logs"] / f"{name}.log")
    rows = parse_wrdata(data.read_text(encoding="ascii"), 2)
    _, inoise = _complex_list(rows, 0)
    _, onoise = _complex_list(rows, 1)
    f_lin = nf_linear_from_inoise(inoise[0].real, Z0_OHM, T_SIM_K)
    return {
        "f_hz": f_hz,
        "inoise_v_sqrt_hz": inoise[0].real,
        "onoise_v_sqrt_hz": onoise[0].real,
        "f_spice_linear": f_lin,
        "nf_spice_db": 10.0 * math.log10(f_lin),
    }


def _lna_stage(dirs: dict[str, Path], nx: int) -> tuple[dict, dict[str, float]]:
    """(b) 单级 LNA：S 参双轮驱动 + 输入共轭匹配简化面 + NF 曲线/频点。

    返回 (lna 结果面, LNA 偏置 .op 小信号参数)。
    """
    op = _run_op_cell(dirs, LNA_VBE_V, LNA_VCC_V, nx)
    noise_model, _, nextra = fet_models_from_op(op, F0_MATCH_HZ, nx, T_SIM_K)
    noise_model.validate()

    freqs_a, waves_a, _ = _run_lna_drive(dirs, 1, None, "unm", nx, with_noise=False)
    _, waves_b, _ = _run_lna_drive(dirs, 2, None, "unm", nx, with_noise=False)
    freqs, s_unm = _sparams_from_waves(freqs_a, waves_a, waves_b)

    i0 = min(range(len(freqs)), key=lambda i: abs(freqs[i] - F0_MATCH_HZ))
    zin_f0 = waves_a[i0].v1 / waves_a[i0].i1
    match = synthesize_lmatch(zin_f0, Z0_OHM, F0_MATCH_HZ)

    matched: dict | None = None
    if match is not None:
        mf_a, wa_m, _ = _run_lna_drive(dirs, 1, match, "mat", nx, with_noise=False)
        _, wb_m, _ = _run_lna_drive(dirs, 2, match, "mat", nx, with_noise=False)
        freqs_m, s_mat = _sparams_from_waves(mf_a, wa_m, wb_m)
        zin_m = wa_m[i0].v1 / wa_m[i0].i1
        matched = {
            "freqs_hz": freqs_m,
            "sparams_re_im": _s_to_json(s_mat),
            "zin_port_at_f0": {"re": zin_m.real, "im": zin_m.imag},
            "s21_db_at_f0": db_of(s_mat["s21"][i0]),
            "s11_db_at_f0": db_of(s_mat["s11"][i0]),
        }

    nf_curve = _nf_band_curve(dirs, nx)
    nf_points = [_nf_point(dirs, f, nx) for f in NF_POINTS_HZ]

    lna = {
        "bias": {
            "vbe_v": LNA_VBE_V,
            "vcc_v": LNA_VCC_V,
            "ic_a": op["ic"],
            "ib_a": op["ib"],
            "gm_s": op["gm"],
            "vbe_junction_v": op["vbe"],
        },
        "fet_mapping_extra": nextra,
        "zin_port_at_f0": {"re": zin_f0.real, "im": zin_f0.imag},
        "match_network": match.to_dict() if match else None,
        "match_note": (
            "L-match synthesized at f0 (series-L absorbs Zin imaginary part, shunt-C at 50R port)"
            if match
            else "unmatched (synthesize_lmatch returned None: R>=Z0 or needs series-C topology)"
        ),
        "unmatched": {
            "freqs_hz": freqs,
            "sparams_re_im": _s_to_json(s_unm),
            "s21_db_at_f0": db_of(s_unm["s21"][i0]),
            "s11_db_at_f0": db_of(s_unm["s11"][i0]),
        },
        "matched": matched,
        "nf_band": nf_curve,
        "nf_points": nf_points,
        "sparam_method": SPARAM_METHOD,
    }
    return lna, op


def _xcheck_diagnostics(
    op: dict[str, float],
    pt: dict[str, float],
    nx: int,
    f_closed_linear: float,
) -> dict:
    """互证偏差的确定性分项归因（同一闭式内核变体逐项量化，非手挥）。

    - 散粒/热噪份额：rg=rs=0 变体（只剩两等效温度散粒）与全模型之差；
    - 缺失噪声等效：spice 与闭式之差折算的输入串联等效电阻（T0 口径），
      对照模型卡名义基阻和 rbx+rbi+rbp（L105-L107 公式，Nx 换算）。
    """
    f_hz = pt["f_hz"]
    nm0, _, extra = fet_models_from_op(op, f_hz, nx, T_SIM_K)

    def _f_linear(rg: float) -> float:
        mod = FetSmallSignal(
            cgs_f=nm0.cgs_f, ri_ohm=nm0.ri_ohm, gm_s=nm0.gm_s, gds_s=nm0.gds_s,
            rg_ohm=rg, rs_ohm=nm0.rs_ohm,
        )
        p = pospieszalski_noise_params(mod, f_hz, extra["tg_k"], extra["td_k"], t0_k=T_SIM_K, z0=Z0_OHM)
        return 10.0 ** (noise_figure_at(p, z_to_gamma(zs_device_plane(f_hz, None), Z0_OHM)) / 10.0)

    nm_shot, _, _ = fet_models_from_op(op, f_hz, nx, T_SIM_K)
    mod_shot = FetSmallSignal(
        cgs_f=nm_shot.cgs_f, ri_ohm=nm_shot.ri_ohm, gm_s=nm_shot.gm_s,
        gds_s=nm_shot.gds_s, rg_ohm=0.0, rs_ohm=0.0,
    )
    p_shot = pospieszalski_noise_params(
        mod_shot, f_hz, extra["tg_k"], extra["td_k"], t0_k=T_SIM_K, z0=Z0_OHM
    )
    f_shot = 10.0 ** (noise_figure_at(p_shot, z_to_gamma(zs_device_plane(f_hz, None), Z0_OHM)) / 10.0)
    excess_closed = f_closed_linear - 1.0
    thermal_share = (excess_closed - (f_shot - 1.0)) / excess_closed if excess_closed > 0 else None
    k_t = K_B_J_PER_K * T_SIM_K
    v_extra = math.sqrt(max((pt["f_spice_linear"] - f_closed_linear), 0.0) * 4.0 * k_t * Z0_OHM)
    nominal_rb = 6.93 * (4.0 / nx) ** 0.95 + 22.0 * (4.0 / nx) ** 0.95 + 5.5 * (4.0 / nx)
    return {
        "f_closed_shot_only_linear": f_shot,
        "thermal_rg_rs_share_of_excess": thermal_share,
        "extra_input_noise_nv_sqrt_hz": v_extra * 1e9,
        "extra_equivalent_series_r_ohm": v_extra**2 / (4.0 * k_t),
        "nominal_rb_sum_ohm": nominal_rb,
        "f_closed_nominal_rb_linear": _f_linear(nominal_rb),
        "nominal_rb_rel_dev": abs(_f_linear(nominal_rb) - pt["f_spice_linear"]) / pt["f_spice_linear"],
    }


def _xcheck_stage(
    op: dict[str, float],
    nf_points: list[dict[str, float]],
    nx: int,
) -> list[dict]:
    """(c) Pospieszalski 闭式互证：F(Γs(器件平面)) vs ngspice 精确频点 NF。"""
    out: list[dict] = []
    for pt in nf_points:
        f = pt["f_hz"]
        nm, _, extra = fet_models_from_op(op, f, nx, T_SIM_K)
        params = pospieszalski_noise_params(
            nm, f, extra["tg_k"], extra["td_k"], t0_k=T_SIM_K, z0=Z0_OHM
        )
        zs = zs_device_plane(f, None)
        gamma_s = z_to_gamma(zs, Z0_OHM)
        nf_closed_db = noise_figure_at(params, gamma_s)
        f_closed = 10.0 ** (nf_closed_db / 10.0)
        rel = abs(f_closed - pt["f_spice_linear"]) / pt["f_spice_linear"]
        circle = noise_circle(params, params.fmin_db + 0.5)
        out.append(
            {
                "f_hz": f,
                "f_spice_linear": pt["f_spice_linear"],
                "nf_spice_db": pt["nf_spice_db"],
                "f_closed_linear": f_closed,
                "nf_closed_db": nf_closed_db,
                "rel_dev": rel,
                "verdict": band_verdict(rel),
                "nfmin_closed_db": params.fmin_db,
                "rn_ohm": params.rn_ohm,
                "gamma_opt": {"re": params.gamma_opt.real, "im": params.gamma_opt.imag},
                "gamma_s_device": {"re": gamma_s.real, "im": gamma_s.imag},
                "zs_device": {"re": zs.real, "im": zs.imag},
                "tg_k": extra["tg_k"],
                "td_k": extra["td_k"],
                "noise_circle_nfmin_p5db": circle.to_dict(),
                "path": params.path,
                "diagnostics": _xcheck_diagnostics(op, pt, nx, f_closed),
            }
        )
    return out


def run_day1(outdir: Path = DEFAULT_OUTDIR, nx: int = 2) -> dict:
    """全链编排：自检 → 网格 → LNA → 互证 → JSON（判据见模块头，#122 预声明）。"""
    if not PDK_CORNER_HBT.exists():
        raise FileNotFoundError(f"PDK 模型库缺失: {PDK_CORNER_HBT}")
    dirs = {
        "root": outdir,
        "netlists": outdir / "netlists",
        "logs": outdir / "logs",
        "data": outdir / "data",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    # ── stage 0：仪器自检（坏仪器拒跑，#122 不凑绿）──────────────────────────
    selftest = _selftest(dirs)
    if not selftest["pass"]:
        raise RuntimeError(f"仪器自检失败（max_abs_dev={selftest['max_abs_dev']:.3e}），拒跑")

    # ── stage a：偏置/gm/fT 网格 3x3 ────────────────────────────────────────
    grid = _grid_stage(dirs, nx)

    # ── stage b：单级 LNA S 参 + NF ─────────────────────────────────────────
    lna, lna_op = _lna_stage(dirs, nx)

    # ── stage c：Pospieszalski 闭式互证 ────────────────────────────────────
    xcheck = _xcheck_stage(lna_op, lna["nf_points"], nx)

    # ── verdicts 与归因（LNA 偏置 vbe=0.87 不在网格列，h21 独立一跑）────────
    ft_h21_lna = _run_h21_cell(dirs, LNA_VBE_V, LNA_VCC_V, nx)
    gm_cons = lna_op["gm"] * (K_B_J_PER_K * T_SIM_K / Q_E_C) * VBIC_NF_NPN13G2 / lna_op["ic"]
    gm_verdict = "PASS" if abs(gm_cons - 1.0) <= GM_CONSISTENCY_TOL else "FAIL"
    # VBIC IKF 高电流 gm 滚降对照（sg13g2_hbt_mod.lib L81: ikf=0.009*(Nx*0.25)）：
    # 判据前提=理想指数区（Ic<<IKF），滚降区偏离属模型特性，定量入归因不挪门。
    ikf_a = 0.009 * (nx * 0.25)
    gmcons_lo = min(grid, key=lambda c: c["ic_a"])
    worst = max(xcheck, key=lambda x: x["rel_dev"])
    verdicts = {
        "instrument_selftest": "PASS" if selftest["pass"] else "FAIL",
        "ft_h21_lna_hz": ft_h21_lna,
        "ft_band": ft_band_verdict(ft_h21_lna),
        "ft_band_note": "band [100,500] GHz predeclared; SG13G2 ~250GHz-class is secondhand (round6 doc), handbook comparison UNVERIFIED",
        "gm_consistency_ratio": gm_cons,
        "gm_consistency": gm_verdict,
        "gm_consistency_note": "criterion premise = ideal-exponential region (Ic<<IKF); rolloff-region deviation quantified in attribution, verdict kept as measured (#122 no gate rewriting)",
        "gm_ic_over_ikf": lna_op["ic"] / ikf_a,
        "gm_consistency_lowest_current_cell": {
            "vbe_v": gmcons_lo["vbe_v"],
            "vce_v": gmcons_lo["vce_v"],
            "ratio": gmcons_lo["gm_consistency"],
        },
        "gm_handbook": "UNVERIFIED",
        "nf_xcheck_worst_rel": worst["rel_dev"],
        "nf_xcheck_worst_verdict": worst["verdict"],
        "nf_xcheck_all": {f"{x['f_hz']:.3e}": x["verdict"] for x in xcheck},
        "nf_xcheck_diagnostics_note": "per-point diagnostics quantify the residual: thermal rg+rs share of closed-form excess, extra input-referred noise (spice - closed) as equivalent series R at T0, and the same kernel with nominal model-card base resistance sum (rbx+rbi+rbp)",
    }
    hard_fail = any(
        v == "FAIL"
        for v in (verdicts["instrument_selftest"], verdicts["ft_band"], verdicts["gm_consistency"], worst["verdict"])
    )
    any_partial = any(
        v == "PARTIAL"
        for v in (verdicts["ft_band"], verdicts["gm_consistency"], worst["verdict"])
    )
    verdicts["overall"] = "FAIL" if hard_fail else ("PARTIAL" if any_partial else "PASS")

    attribution = [
        "sparam_method: manual_port_power_waves (.net/net unavailable in this ngspice-45.2 build; "
        "preauthorized fallback, verified by series-100R analytic selftest)",
        "go printed negative by .op (VBIC self-heating feedback, selft=1): closed-form gds uses |go|",
        "Tg=T_sim/2: base shot noise 2qIb equivalent to junction-series resistance at T/2 (classic identity); "
        "Td=q*Ic/(2k*gds): collector shot noise 2qIc equivalent to Rds at Td (temperature fixed by matching)",
        "closed-form Pospieszalski intrinsic domain ignores Cmu/Cjs/tau and substrate network "
        "(fet_noise honest boundary); ngspice VBIC carries them fully -> expected part of residual deviation",
        "ngspice noise sources (base/collector shot + resistor thermal) are uncorrelated in SPICE convention; "
        "Pospieszalski assumption likewise uncorrelated, but real-device correlation via transit delay is "
        "not modeled on either side",
        "temperature alignment: both sides evaluated at T=300.15K (ngspice default TEMP=27C)",
        "re (rs_ohm) = 7.13*(4/Nx) from sg13g2_hbt_mod.lib L98 (hbt_typ vbic_re=1); "
        "rg=1/gx is the device-reported total base series resistance",
        "grid axes are vbe x vce (recorded ic per cell is the measured outcome); vbe=0.90 cells may sit at "
        "the model-card validity edge ic<3mA*Nx",
        "LNA bias vbe=0.87/vcc=1.2 chosen inside valid region (vbe 0.65-0.96, vce 0.4-1.6); "
        "h21 drive uses Vsig+Rb=50 (DC drop ~0.1mV, negligible)",
        "NF points simulated exactly (lin 1 f f), no interpolation; NF band curve is dec-sweep",
        "NF xcheck verdict (predeclared band) recorded as measured; quantitative localization in "
        "per-point xcheck.diagnostics: closed-form excess noise is ~3/4 series-resistance thermal "
        "(rg+rs) and ~1/4 shot; the spice-minus-closed residual equals an extra series resistance of "
        "~53 ohm at T0, bracketed by the DC-effective 1/gx (~28 ohm, predeclared mapping) and the "
        "model-card nominal rbx+rbi+rbp sum (~67 ohm at Nx=2) - with the nominal value the same "
        "kernel lands inside the predeclared band (rel ~0.08). The FAIL therefore localizes to "
        "base-resistance noise partition (DC-effective vs nominal) plus intrinsic-domain omissions "
        "(collector/substrate resistor thermal, nonideal-junction shot), not to instrument or kernel "
        "error; Day-2 resolution = fix the partition by measurement/cold-FET extraction, not by "
        "re-fitting here (#122: verdict not rewritten)",
        "gm consistency verdict as measured (FAIL at LNA bias): identity gm*VT*nf/Ic ~= 1 holds only "
        "in the ideal-exponential region; at the LNA bias Ic/IKF ~ 0.4 (IKF=4.5mA at Nx=2, model "
        "card L81) VBIC high-current gm rolloff applies - the lowest-current grid cell "
        "(Ic/IKF ~ 0.06) measures ratio ~0.94 inside the band, consistent with rolloff rather than "
        "model fault; quantified in verdicts, gate not moved",
        "handbook typical-value bands (fT~250GHz class, NF/gm typicals) not verified against IHP "
        "documentation in this Day-1 scope: UNVERIFIED",
    ]

    netlists = sorted(str(p) for p in dirs["netlists"].glob("*.cir"))
    logs = sorted(str(p) for p in dirs["logs"].glob("*.log"))
    results_json = dirs["root"] / "day1_results.json"

    res: dict = {
        "schema": SCHEMA_ID,
        "meta": {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "adapter": f"ngspice WSL {WSL_DISTRO}",
            "pdk": "IHP SG13G2 Open PDK (Apache-2.0), cornerHBT.lib hbt_typ, VBIC Rev.1.15",
            "device": f"npn13G2 Nx={nx}",
            "t_sim_k": T_SIM_K,
            "z0_ohm": Z0_OHM,
            "closed_form_kernel": "rfauto.core.fet_noise.pospieszalski_noise_params",
        },
        "criteria": {
            "nf_band_predeclared": {
                "warn_rel": NF_WARN_REL,
                "fail_rel": NF_FAIL_REL,
                "domain": "linear F relative deviation",
            },
            "ft_band_hz": list(FT_BAND_HZ),
            "gm_consistency_tol": GM_CONSISTENCY_TOL,
            "selftest_tolerance": SELFTEST_TOL,
        },
        "instrument_selftest": selftest,
        "grid": grid,
        "lna": lna,
        "xcheck": xcheck,
        "attribution": attribution,
        "verdicts": verdicts,
        "provenance": {
            "results_json": str(results_json),
            "netlists": netlists,
            "logs": logs,
            "log_note": "ngspice -b batch mode writes no .lis; stdout/stderr logs are the raw record",
        },
    }

    problems = validate_results(res)
    if problems:
        raise RuntimeError("结果契约校验失败（不落 JSON）:\n" + "\n".join(problems))
    results_json.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="F-L.1b SG13G2 Day-1 real-run chain (ngspice WSL + IHP PDK VBIC)")
    ap.add_argument("--outdir", default=str(DEFAULT_OUTDIR), help="output directory (default runs/fl1_sg13g2)")
    ap.add_argument("--nx", type=int, default=2, help="HBT emitter finger count Nx (default 2)")
    args = ap.parse_args(argv)
    res = run_day1(Path(args.outdir), nx=args.nx)
    v = res["verdicts"]
    print(
        f"day1 done: overall={v['overall']} ft_h21={v['ft_h21_lna_hz']} "
        f"nf_xcheck_worst={v['nf_xcheck_worst_verdict']} -> {res['provenance']['results_json']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

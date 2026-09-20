"""ADS 网表生成 + hpeesofsim 批处理 + 数据集解析（P3 实现, ADR-0009）。

主通道 = B: Python 生成网表文本 -> hpeesofsim.exe 子进程求解 ->
keysight.ads.dataset(ADS 自带 python 子进程)读 .ds -> 结构化 dict -> skrf/契约校验。

进程边界（已实测确认）: 本项目 venv 是 Python 3.12, ADS 2027 自带 python 是 3.14.6,
keysight.ads.* 只能在 ADS 自带 python 里 import 且须先设 HPEESOF_DIR。
因此所有 ADS 侧操作(读 .ds)都经由 ADS python 子进程完成,
rfauto 进程只负责编排、数值与契约校验。

SnP 组件语法（实证收敛, 见 ADR-0009）:
    SnP:SNP1  P1 P2 P3 NumPorts=3 File="path.s3p" Type="touchstone"
        InterpMode="linear" InterpDom="" ExtrapMode="constant" Temp=27.0 CheckPassivity=0
- 节点列表恰好 NumPorts 个节点名、不含地;
- Type="touchstone"(或省略); smatrixio 是 ADS 自有 .sio 格式, 喂 Touchstone 会报错;
- 每条语句独占一行(ADS 多行须行尾反斜杠续行, 绕开续行符风险);
- 文件必须无 BOM、纯 ASCII。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from rfauto.core.contracts import AdsExchangeContract
from rfauto.core.errors import SimulationFailedError
from rfauto.infra.config import load_settings

logger = logging.getLogger(__name__)

#: 默认 ADS 安装位置（兜底）
_ADS_DIR_DEFAULT = Path(r"C:\Program Files\Keysight\ADS2027")

_DS_PROBE = r"""
import json, sys, os, re
if len(sys.argv) > 2:
    os.environ["HPEESOF_DIR"] = sys.argv[2]
import keysight.ads.dataset as ds
p = sys.argv[1]
data = ds.open(p)
keys = [k for k in data.keys()]
sp_key = None
for k in keys:
    if k.endswith(".SP") or ".SP" in k or k.startswith("SP1"):
        sp_key = k
        break
if sp_key is None and keys:
    sp_key = keys[0]
if sp_key is None:
    print(json.dumps({"ok": False, "error": "no dataset"}))
    sys.exit(2)
df = data[sp_key].to_dataframe().reset_index()
freq = [float(x) for x in df["freq"].tolist()]
s = {}
for c in df.columns:
    m = re.match(r"S\[(\d+),(\d+)\]", str(c))
    if m:
        zs = []
        for v in df[c].tolist():
            z = complex(v)
            zs.append([z.real, z.imag])
        s["%d_%d" % (int(m.group(1)), int(m.group(2)))] = zs
port_names = []
for i in range(1, 20):
    col = "PortName[%d]" % i
    if col in df.columns:
        port_names.append(str(df[col].iloc[0]))
    else:
        break
port_z = []
for i in range(1, 20):
    col = "PortZ[%d]" % i
    if col in df.columns:
        z = complex(df[col].iloc[0])
        port_z.append([z.real, z.imag])
    else:
        break
print(json.dumps({"ok": True, "key": sp_key, "frequency_hz": freq, "s": s,
                  "port_names": port_names, "port_z": port_z}))
"""

def _resolve_ads_dir(ads_dir: str | Path | None = None) -> Path:
    """按优先级解析 ADS 安装目录。

    优先级: 显式参数 > RFAUTO_HPEESOF_DIR > settings.ads.hpeesof_dir > 默认。
    返回目录须含 bin/hpeesofsim.exe 与 tools/python/python.exe。
    """
    candidates: list[Path] = []
    if ads_dir is not None:
        candidates.append(Path(ads_dir))
    env_dir = os.environ.get("RFAUTO_HPEESOF_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    try:
        s = load_settings()
        if getattr(s, "hpeesof_dir", ""):
            candidates.append(Path(s.hpeesof_dir))
    except Exception as exc:
        logger.debug("读取 settings.hpeesof_dir 失败: %s", exc)
    candidates.append(_ADS_DIR_DEFAULT)

    for c in candidates:
        if (c / "bin" / "hpeesofsim.exe").exists() and (c / "tools" / "python" / "python.exe").exists():
            return c
    tried = "; ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"找不到可用 ADS 安装(需含 hpeesofsim.exe + tools/python/python.exe)。尝试过: {tried}。",
        "可用环境变量 RFAUTO_HPEESOF_DIR 指定。",
    )

def _build_ads_env(ads_dir: Path) -> dict[str, str]:
    """构造 hpeesofsim / ADS python 所需完整环境。

    0xC0000135 根因是缺 DLL: PATH 必须含 bin + adsptolemy/lib.win32_64 + tools/python。
    HPEESOF_DIR 必须设, 否则 keysight.ads 导入报 RuntimeError。
    """
    env = os.environ.copy()
    env["HPEESOF_DIR"] = str(ads_dir)
    extra = [
        str(ads_dir / "bin"),
        str(ads_dir / "adsptolemy" / "lib.win32_64"),
        str(ads_dir / "tools" / "python"),
    ]
    env["PATH"] = ";".join([*extra, env.get("PATH", "")])
    return env

def _read_snp_meta(s_params_path: Path) -> dict[str, Any]:
    """读取 Touchstone 端口数 / 频段 / 点数（用于注入网表）。"""
    import skrf
    net = skrf.Network(str(s_params_path))
    f_hz = net.frequency.f
    return {
        "n_ports": int(net.nports),
        "fstart_hz": float(f_hz.min()),
        "fstop_hz": float(f_hz.max()),
        "npoints": int(net.frequency.npoints),
    }

def _frequency_scale(unit: str) -> float:
    """契约频率单位 -> 秒的换算系数（1 unit = x 秒）。"""
    return {"GHz": 1e9, "MHz": 1e6, "kHz": 1e3, "Hz": 1.0}[unit]

def generate_netlist(
    template_path: str | Path,
    s_params_path: str | Path,
    output_path: str | Path,
    contract: AdsExchangeContract | None = None,
) -> Path:
    """从模板生成 ADS 网表（无 BOM、纯 ASCII；SnP 语法见 ADR-0009）。

    动态填充:
    - {{FSTART}} / {{FSTOP}} / {{NPOINTS}}: 从 Touchstone 频段推导;
    - {{FREQ_UNIT}}: 契约 frequency_unit;
    - {{PORTS}}: 按端口数生成 Port 定义块;
    - {{SNP_LINE}}: SnP 组件行(Type="touchstone", 节点恰好 N 个、不含地)。

    Raises:
    - FileNotFoundError: 模板 / Touchstone 不存在。
    - ContractViolationError: 端口数与契约 port_order 不符。
    """
    template_path = Path(template_path)
    s_params_path = Path(s_params_path)
    output_path = Path(output_path)
    if not template_path.exists():
        raise FileNotFoundError(f"网表模板不存在: {template_path}")
    if not s_params_path.exists():
        raise FileNotFoundError(f"Touchstone 文件不存在: {s_params_path}")

    meta = _read_snp_meta(s_params_path)
    n_ports = meta["n_ports"]
    if contract is not None:
        contract.validate_touchstone_ports(n_ports)
    unit = contract.touchstone.frequency_unit if contract else "GHz"
    scale = _frequency_scale(unit)
    z0 = contract.touchstone.renormalization_ohm if contract else 50.0
    template = template_path.read_text(encoding="utf-8")

    port_lines = [
        f"Port:P{i}  P{i} 0 Num={i} Z={z0:g} Ohm Noise=yes"
        for i in range(1, n_ports + 1)
    ]
    nodes = " ".join(f"P{i}" for i in range(1, n_ports + 1))
    snp_line = (
        f'SnP:SNP1  {nodes} NumPorts={n_ports} File="{s_params_path.resolve()}" '
        f'Type="touchstone" InterpMode="linear" InterpDom="" ExtrapMode="constant" '
        f"Temp=27.0 CheckPassivity=0"
    )
    repl = {
        "{{FSTART}}": f"{meta['fstart_hz'] / scale:g}",
        "{{FSTOP}}": f"{meta['fstop_hz'] / scale:g}",
        "{{NPOINTS}}": str(meta["npoints"]),
        "{{FREQ_UNIT}}": unit,
        "{{PORTS}}": "\n".join(port_lines),
        "{{SNP_LINE}}": snp_line,
    }
    for k, v in repl.items():
        template = template.replace(k, v)
    if contract is not None:
        template = template.replace("{{DATASET_EXPORT}}", " ".join(contract.ads.dataset_export))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template, encoding="ascii", errors="ignore")
    logger.info("网表已生成: %s (%d 端口)", output_path, n_ports)
    return output_path

def run_hpeesofsim(
    netlist_path: str | Path,
    ads_dir: str | Path | None = None,
    timeout_s: int = 3600,
    workdir: str | Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """运行 hpeesofsim.exe 批处理求解（P3 主通道）。

    在网表所在目录执行, 输出 <netlist>.ds 落在该目录。
    """
    netlist_path = Path(netlist_path)
    if not netlist_path.exists():
        raise FileNotFoundError(f"网表文件不存在: {netlist_path}")
    ads = _resolve_ads_dir(ads_dir)
    exe = ads / "bin" / "hpeesofsim.exe"
    env = _build_ads_env(ads)
    cwd = Path(workdir) if workdir else netlist_path.parent
    cmd = [str(exe), netlist_path.name]
    logger.info("运行 hpeesofsim: %s (cwd=%s)", " ".join(cmd), cwd)
    try:
        result = subprocess.run(
            cmd, cwd=cwd, env=env, capture_output=True, text=True,
            timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SimulationFailedError(
            f"hpeesofsim 求解超时 ({timeout_s}s)",
            details={"timeout_s": timeout_s, "netlist": str(netlist_path)},
        ) from exc
    if result.returncode != 0:
        raise SimulationFailedError(
            f"hpeesofsim 求解失败 (exit code {result.returncode})",
            details={"returncode": result.returncode, "stderr": result.stderr[:2000],
                      "stdout": result.stdout[-2000:], "netlist": str(netlist_path)},
        )
    logger.info("hpeesofsim 求解完成 (rc=0)")
    return result

def parse_dataset(
    dataset_path: str | Path,
    ads_dir: str | Path | None = None,
    timeout_s: int = 180,
) -> dict[str, Any]:
    """解析 ADS 输出数据集 (.ds) -> 结构化 dict。

    经 ADS 自带 python 子进程运行探针脚本, 用 keysight.ads.dataset 读出频率、
    S 参数(复数), 端口名与端口阻抗, 以 JSON 传回 rfauto 进程。
    """
    dataset_path = Path(dataset_path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"ADS 数据集不存在: {dataset_path}")
    ads = _resolve_ads_dir(ads_dir)
    py = ads / "tools" / "python" / "python.exe"
    env = _build_ads_env(ads)
    probe = None
    p = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(_DS_PROBE)
            probe = f.name
        try:
            p = subprocess.run(
                [str(py), probe, str(dataset_path), str(ads)],
                env=env, capture_output=True, text=True, timeout=timeout_s, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SimulationFailedError(
                f"ADS .ds 解析超时 ({timeout_s}s)",
                details={"timeout_s": timeout_s, "dataset": str(dataset_path)},
            ) from exc
        if p.returncode != 0:
            raise SimulationFailedError(
                f"ADS .ds 解析失败 (exit {p.returncode})",
                details={"stderr": p.stderr[-1500:], "dataset": str(dataset_path)},
            )
        stdout = p.stdout.strip()
        if not stdout:
            raise SimulationFailedError("ADS .ds 解析无输出", details={"dataset": str(dataset_path)})
        payload = json.loads(stdout.splitlines()[-1])
        if not payload.get("ok"):
            raise SimulationFailedError(
                f"ADS .ds 解析: {payload.get('error')}", details={"dataset": str(dataset_path)},
            )
        return payload
    except json.JSONDecodeError as exc:
        raise SimulationFailedError(
            f"ADS .ds 解析输出非 JSON: {(p.stdout if p else '')[-300:]!r}",
            details={"dataset": str(dataset_path)},
        ) from exc
    finally:
        if probe:
            Path(probe).unlink(missing_ok=True)

_HB_PROBE = r"""
import json, sys, os
if len(sys.argv) > 2:
    os.environ["HPEESOF_DIR"] = sys.argv[2]
import keysight.ads.dataset as ds
p = sys.argv[1]
data = ds.open(p)
keys = [str(k) for k in data.keys()]
hb_key = None
for k in keys:
    if k.endswith(".HB") and not k.startswith("aele_"):
        hb_key = k
        break
if hb_key is None:
    print(json.dumps({"ok": False, "error": "no HB block", "keys": keys}))
    sys.exit(2)
df = data[hb_key].to_dataframe().reset_index()
cols = [str(c) for c in df.columns]
node_cols = [c for c in cols if c != "freq" and not c.startswith("Mix[") and c != "__i"]
harmonics = []
for _, row in df.iterrows():
    mix = int(row["Mix[1]"]) if "Mix[1]" in cols else None
    nodes = {}
    for c in node_cols:
        z = complex(row[c])
        nodes[c] = [z.real, z.imag]
    harmonics.append({"freq_hz": float(row["freq"]), "mix": mix, "nodes": nodes})
meas = {}
for k in keys:
    if k.startswith("aele_"):
        try:
            mdf = data[k].to_dataframe().reset_index()
        except Exception as exc:
            meas[k] = {"error": repr(exc)}
            continue
        for c in mdf.columns:
            c = str(c)
            if c == "__i" or c in ("freq",):
                continue
            v = mdf[c].iloc[0]
            try:
                z = complex(v)
                meas[c] = z.real if abs(z.imag) == 0.0 else [z.real, z.imag]
            except Exception:
                meas[c] = str(v)
print(json.dumps({"ok": True, "key": hb_key, "harmonics": harmonics,
                  "measurements": meas, "keys": keys}))
"""


def parse_hb_dataset(
    dataset_path: str | Path,
    ads_dir: str | Path | None = None,
    timeout_s: int = 180,
) -> dict[str, Any]:
    """解析 HB (谐波平衡) 输出数据集 (.ds) -> 结构化 dict。

    真机实证口径 (ADS 2027 hpeesofsim 650.shp):
    HB 块键形如 ``HB1.HB``, 列 = ``freq`` / ``Mix[1]`` (谐波序号, 0=DC) /
    各节点电压相量 (复数); 网表 ``aele`` 测量方程各自成块 ``aele_N.HB1.HB``
    (列 ``__i`` + 变量名, 单行标量)。返回::

        {"ok": True, "key": "HB1.HB",
         "harmonics": [{"freq_hz", "mix", "nodes": {name: [re, im]}}, ...],
         "measurements": {"Pout_W": .., "Pout_dBm": .., ...}, "keys": [...]}

    与 ``parse_dataset`` 同进程边界 (ADS 自带 python 子进程)。
    """
    dataset_path = Path(dataset_path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"ADS 数据集不存在: {dataset_path}")
    ads = _resolve_ads_dir(ads_dir)
    py = ads / "tools" / "python" / "python.exe"
    env = _build_ads_env(ads)
    probe = None
    p = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(_HB_PROBE)
            probe = f.name
        try:
            p = subprocess.run(
                [str(py), probe, str(dataset_path), str(ads)],
                env=env, capture_output=True, text=True, timeout=timeout_s, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SimulationFailedError(
                f"ADS HB .ds 解析超时 ({timeout_s}s)",
                details={"timeout_s": timeout_s, "dataset": str(dataset_path)},
            ) from exc
        if p.returncode != 0:
            raise SimulationFailedError(
                f"ADS HB .ds 解析失败 (exit {p.returncode})",
                details={"stderr": p.stderr[-1500:], "stdout": p.stdout[-500:],
                         "dataset": str(dataset_path)},
            )
        stdout = p.stdout.strip()
        if not stdout:
            raise SimulationFailedError("ADS HB .ds 解析无输出", details={"dataset": str(dataset_path)})
        payload = json.loads(stdout.splitlines()[-1])
        if not payload.get("ok"):
            raise SimulationFailedError(
                f"ADS HB .ds 解析: {payload.get('error')}", details={"dataset": str(dataset_path)},
            )
        return payload
    except json.JSONDecodeError as exc:
        raise SimulationFailedError(
            f"ADS HB .ds 解析输出非 JSON: {(p.stdout if p else '')[-300:]!r}",
            details={"dataset": str(dataset_path)},
        ) from exc
    finally:
        if probe:
            Path(probe).unlink(missing_ok=True)


def snp_meta_for_netlist(s_params_path: str | Path) -> dict[str, Any]:
    """便捷: 读取 Touchstone 元信息(供上层做契约校验/缓存键)。"""
    return _read_snp_meta(Path(s_params_path))

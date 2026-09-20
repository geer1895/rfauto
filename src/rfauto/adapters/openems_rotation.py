"""N 端口全 S 矩阵装配器（ratrace/coupler 族，#208）。

口径：N 端口宽带 S 参数 = 每端口各激励一次的激励轮转（openEMS 官方
Full S-Parameter Simulation Loop）。**进程隔离**实现——按 excite_port=1..N
渲染 N 份单激励脚本，每份在独立工作目录独立子进程跑一次（单激励是全
库已验证的安全模式），适配器层读各列 CSV 装配 N×N，主产物 skrf
Touchstone .s{N}p（.s4p/.s6p/...，P2⑬ 列解析已按 n_ports 通用化）。

为什么不进程内轮转（SetEnabled/复用 CSX）：Run(cleanup=True) 会销毁
激励属性乃至 CSX 的 C++ 对象，跨 Run 复用包装器触发 "wrapped C++
object has been deleted"（pt3/pt4 实测，#208）。进程隔离同时天然免疫
瞬态崩溃（单轮失败只重跑该轮）。

产物布局（work_root 下）：p1/..pN/（各含 simulation.py + sparams.csv）、
<template>.s{N}p（装配结果）、.smatrix_cache.npz（可选缓存）。

**逐轮断点缓存**：每轮 CSV 即断点——重入时
逐轮校验「simulation.py 与本次渲染逐字节一致 + sparams.csv 可解析」，
二者齐备则跳过该轮子进程直接复用列（resume=True 默认开）；任一不满足
即重跑该轮。脚本内容=轮次身份，杜绝换参/换 mesh 后错配陈旧产物。

**装配归一化（#250 链，opt-in `line_z0`，C4 refix 实证）**：各轮 CSV
是 footer `CalcPort(ref_impedance=50)` 的 **50Ω 伪波带载比值**；端口线在缺省网格
下的引擎自算 ZL 并不等于 HJ 设计值（lange/cline 50Ω 馈线实测 ZL≈45.7Ω，−8.7%），
非激励端由 PML 按离散线自身 ZL 匹配端接，50Ω 分解便在每端口引入伪反射
Γ=(ZL−50)/(ZL+50)≈−0.045 → 装配矩阵非无源（σmax 1.0275/1.0344）。
`line_z0="engine"`：从各轮 p{k}/fdtd 三面探针按 openEMS `MSLPort.ReadUIData`
同式复算 ZL(f)（均匀线上 sqrt(V·V'/(I·I')) 与负载无关），逐端口跨轮取中位，
走 `openems_templates.renorm_engine_s_to_ref`（按列反演到线基 → skrf
renormalize 到 50Ω）；原始矩阵另存 `<template>_raw.s{N}p`，返回值
`assembly_norm` 记录 ZL/偏差/归一前后 σmax。默认 `line_z0=None` 行为不变。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

_CACHE_SCHEMA = "rfauto-openems-smatrix-v1"

# _absorb_round 槽位守卫标记：槽位数≠n_ports 时返回，调用方按损坏产物重跑该轮
_SLOT_GUARD = "slot-count-mismatch"


def _script_hash(scripts: list[str], exe_path: str | None,
                 salt: str = "") -> str:
    h = hashlib.sha256()
    h.update(_CACHE_SCHEMA.encode())
    for s in scripts:
        h.update(s.encode())
    h.update((exe_path or "").encode())
    h.update(salt.encode())
    with suppress(Exception):
        from importlib.metadata import version

        h.update(version("openEMS").encode())
    return h.hexdigest()


def _load_cache(cache_dir: Path | None, key: str) -> dict[str, Any] | None:
    if cache_dir is None:
        return None
    npz = cache_dir / f"{key}.npz"
    if not npz.exists():
        return None
    try:
        import json

        import numpy as np

        with np.load(npz) as data:
            out: dict[str, Any] = {"ok": True, "freq_ghz": data["freq_ghz"],
                                   "s_params": data["s_params"],
                                   "message": "全 S 矩阵完成（缓存复用）"}
            if "assembly_norm_json" in data.files:
                out["assembly_norm"] = json.loads(str(data["assembly_norm_json"]))
            return out
    except Exception:
        return None


def _store_cache(cache_dir: Path | None, key: str,
                 freq_ghz: Any, s_params: Any,
                 assembly_norm: dict[str, Any] | None = None) -> None:
    if cache_dir is None:
        return
    try:
        import json

        import numpy as np

        cache_dir.mkdir(parents=True, exist_ok=True)
        npz = cache_dir / f"{key}.npz"
        tmp = npz.with_name(npz.name + ".tmp")
        extra: dict[str, Any] = {}
        if assembly_norm is not None:
            extra["assembly_norm_json"] = np.array(
                json.dumps(assembly_norm, ensure_ascii=False, default=str))
        with open(tmp, "wb") as fh:
            np.savez_compressed(fh, freq_ghz=freq_ghz, s_params=s_params,
                                **extra)
        tmp.replace(npz)
    except Exception:
        with suppress(Exception):
            (cache_dir / f"{key}.npz.tmp").unlink()


def _load_round_csv(csv_path: Path,
                    n_cols: int) -> tuple[Any, list[Any]] | None:
    """读单轮 sparams.csv（freq_hz + n_cols×(re,im) 槽位列，P2⑬ 通用列）。

    槽位 i → 列 (1+2i, 2+2i)，即相对激励端口 k 的 S(i+1)k。列宽
    ≥ 1+2×n_cols 即接受（容忍超宽归档）；不足则拒绝返回 None——
    禁止静默截断（>4 端口扩规模时旧实现静默取前 4 槽，P2⑬ 堵死）。
    缺失/损坏/列数不足一律返回 None（调用方重跑该轮，不阻塞主路径 #105）。
    """
    try:
        import numpy as np

        if not csv_path.exists():
            return None
        data = np.loadtxt(str(csv_path), delimiter=",", skiprows=1,
                          ndmin=2)
        if data.shape[0] < 1 or data.shape[1] < 1 + 2 * n_cols:
            return None
        fg = data[:, 0] / 1e9
        col = [data[:, 1 + 2 * i] + 1j * data[:, 2 + 2 * i]
               for i in range(n_cols)]
        return fg, col
    except Exception:
        return None


# ─── 装配归一化（#250 链，引擎自算 ZL 线基 → 50Ω）────────────────────────────
def _read_probe_file(path: Path) -> tuple[Any, Any, Any]:
    """读 openEMS 探针文件（`%` 头 + 时间/值两列）；返回 (t, v, start_xyz_m)。

    头行 `% start-coordinates: (x,y,z) m -> [i,j,k]` 给探针面位置（米），用于
    传播轴识别与有限差分间距（ZL 比值里长度单位抵消，只 β 依赖单位）。
    """
    import numpy as np

    coords = None
    rows: list[list[str]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("%"):
                if coords is None and "start-coordinates" in line:
                    inner = line.split("(", 1)[1].split(")", 1)[0]
                    coords = np.array([float(v) for v in inner.split(",")])
                continue
            s = line.strip()
            if s:
                rows.append(s.split()[:2])
    if coords is None or not rows:
        raise ValueError(f"{path}: 缺 start-coordinates 头或无数据行")
    data = np.array(rows, dtype=float)
    return data[:, 0], data[:, 1], coords


def _dft_pulse(t: Any, v: Any, f_hz: Any) -> Any:
    """openEMS `utilities.DFT_time2freq(signal_type='pulse')` 同式（×dt、单边 ×2）。"""
    import numpy as np

    out = np.empty(len(f_hz), dtype=complex)
    for i, fi in enumerate(f_hz):
        out[i] = np.sum(v * np.exp(-2j * np.pi * fi * t))
    return 2.0 * out * (t[1] - t[0])


def engine_msl_line_z0(fdtd_dir: str | Path, port_nr: int,
                       freq_hz: Any) -> Any | None:
    """MSLPort 三面探针 → 引擎自算线特征阻抗 ZL(f)（`MSLPort.ReadUIData` 同式）。

    Z_L = sqrt(Et·dEt/(Ht·dHt))：Et=U_B、dEt=(U_C−U_A)/Σ|ΔU|、Ht=(I_A+I_B)/2、
    dHt=(I_B−I_A)/|ΔI|（openEMS ports.py 逐行对照）。均匀线上 V·V'/(I·I')≡Z0²
    与负载无关（驻波亦成立），故激励轮/非激励轮均可取——但离散化误差随该轮
    驻波形态略变（lange 实测 45.45/45.57/45.80 与孤立端低信噪 47.31），调用方
    跨轮取中位。文件 port_ut_{nr}{A,B,C}/port_it_{nr}{A,B} 任一缺失（LumpedPort
    等无三面探针）返回 None。返回 (N,) 复数，Re 取正根。
    """
    import numpy as np

    d = Path(fdtd_dir)
    names_u = [d / f"port_ut_{port_nr}{s}" for s in "ABC"]
    names_i = [d / f"port_it_{port_nr}{s}" for s in "AB"]
    if not all(p.exists() for p in names_u + names_i):
        return None
    f = np.asarray(freq_hz, dtype=float)
    u = [_read_probe_file(p) for p in names_u]
    cur = [_read_probe_file(p) for p in names_i]
    span = np.abs(u[2][2] - u[0][2])
    ax = int(np.argmax(span))
    if span[ax] <= 0.0:
        return None
    uf = [_dft_pulse(t, v, f) for t, v, _ in u]
    cf = [_dft_pulse(t, v, f) for t, v, _ in cur]
    u_pos = [c[ax] for _, _, c in u]
    i_pos = [c[ax] for _, _, c in cur]
    et = uf[1]
    det = (uf[2] - uf[0]) / (abs(u_pos[1] - u_pos[0]) + abs(u_pos[2] - u_pos[1]))
    ht = 0.5 * (cf[0] + cf[1])
    dht = (cf[1] - cf[0]) / abs(i_pos[1] - i_pos[0])
    zl = np.sqrt(et * det / (ht * dht))
    return np.where(np.real(zl) < 0, -zl, zl)


def line_z0_from_rounds(root: str | Path, n_ports: int, freq_hz: Any,
                        sim_dir: str = "fdtd") -> tuple[Any, dict[str, Any]]:
    """各端口线 ZL(f)：逐轮 `engine_msl_line_z0`，按轮取中位（实/虚分开）。

    返回 ((N,P) 复数数组, info)；某端口零可用轮 → 该列 nan（调用方按 z_ref
    恒等处理并记录）。info["rounds_used"][port]=贡献轮号列表。
    """
    import numpy as np

    rootp = Path(root)
    f = np.asarray(freq_hz, dtype=float)
    zl = np.full((len(f), n_ports), np.nan + 0j, dtype=complex)
    rounds_used: dict[str, list[int]] = {}
    for p in range(1, n_ports + 1):
        samples = []
        used = []
        for k in range(1, n_ports + 1):
            try:
                z = engine_msl_line_z0(rootp / f"p{k}" / sim_dir, p, f)
            except Exception:
                z = None
            if z is None or not np.all(np.isfinite(z)):
                continue
            samples.append(z)
            used.append(k)
        rounds_used[str(p)] = used
        if samples:
            stack = np.stack(samples)
            zl[:, p - 1] = (np.median(np.real(stack), axis=0)
                            + 1j * np.median(np.imag(stack), axis=0))
    return zl, {"rounds_used": rounds_used}


def _sigma_max(s: Any) -> float:
    import numpy as np

    return float(np.max(np.linalg.svd(s, compute_uv=False)))


def normalize_assembled_smatrix(
    s_raw: Any, freq_ghz: Any, line_z0: Any, *,
    n_ports: int, root: str | Path | None = None, z_ref_ohm: float = 50.0,
    sim_dir: str = "fdtd",
) -> tuple[Any, dict[str, Any]]:
    """装配矩阵（CalcPort ref=z_ref 带载比值）→ #250 链 → z_ref 真波基。

    `line_z0`："engine"（从 root/p{k}/sim_dir 探针复算，需 root）| 标量 | 逐端口
    序列 | (N,P) 数组。返回 (s_norm, info)，info 含 mode/z_ref_ohm/
    line_z0_ohm（逐端口频带中位 Re）/line_z0_dev_pct/sigma_max_raw/
    sigma_max_norm/rounds_used/notes。缺探针端口按 z_ref 恒等并入 notes。
    """
    import numpy as np

    from rfauto.adapters.openems_templates import renorm_engine_s_to_ref

    s = np.asarray(s_raw, dtype=complex)
    n = s.shape[0]
    notes: list[str] = []
    info: dict[str, Any] = {"mode": str(line_z0), "z_ref_ohm": float(z_ref_ohm)}
    if isinstance(line_z0, str):
        if line_z0 != "engine":
            raise ValueError(f"line_z0 仅支持 'engine' 或数值，得 {line_z0!r}")
        if root is None:
            raise ValueError("line_z0='engine' 需要 root（各轮 p{k}/fdtd 探针）")
        f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
        zl, extra = line_z0_from_rounds(root, n_ports, f_hz, sim_dir=sim_dir)
        info["rounds_used"] = extra["rounds_used"]
        for p in range(n_ports):
            if not np.all(np.isfinite(zl[:, p])):
                zl[:, p] = z_ref_ohm
                notes.append(f"port{p + 1} 无三面探针 → 按 z_ref 恒等")
    else:
        zl = np.broadcast_to(np.asarray(line_z0, dtype=complex),
                             (n, n_ports)).copy()
    s_norm = renorm_engine_s_to_ref(s, zl, z_ref_ohm)
    z_med = [float(np.median(np.real(zl[:, p]))) for p in range(n_ports)]
    info["line_z0_ohm"] = z_med
    info["line_z0_dev_pct"] = [(z / z_ref_ohm - 1.0) * 100.0 for z in z_med]
    info["sigma_max_raw"] = _sigma_max(s)
    info["sigma_max_norm"] = _sigma_max(s_norm)
    info["notes"] = notes
    return s_norm, info


def solve_smatrix_openems(
    work_root: str | Path,
    *,
    template: str,
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
    n_ports: int = 4,
    timeout_s: int = 36000,
    exe_path: str | None = None,
    cache: bool = True,
    resume: bool = True,
    line_z0: Any = None,
    z_ref_ohm: float = 50.0,
) -> dict[str, Any]:
    """进程隔离激励轮转：N 次单激励真跑 → 装配 N×N → .s{N}p。

    返回 JSON 契约 {"ok", "freq_ghz", "s_params", "s4p_path",
    "n_runs", "elapsed_s", ...}；单轮失败如实报错（附该轮 stderr 尾）。
    resume=True（默认）启用逐轮断点缓存：已完成轮（脚本一致+产物可解析）
    重入时直接复用，瞬态崩溃只补跑缺失轮。
    line_z0（默认 None=原始带载比值，行为不变）："engine"/数值 → 走
    `normalize_assembled_smatrix`（#250 链）后再写 .s{N}p，原始矩阵另存
    `<template>_raw.s{N}p`，返回值增 "assembly_norm"（ZL/偏差/σmax 前后）与
    "s_params_raw"；缓存键含 line_z0 描述，raw/归一两种结果互不串味。
    """
    import numpy as np

    from rfauto.adapters.openems_templates import render_script

    t0 = time.time()
    root = Path(work_root)
    root.mkdir(parents=True, exist_ok=True)

    scripts: list[str] = []
    for k in range(1, n_ports + 1):
        scripts.append(render_script(
            template, params, freq_range_ghz,
            mesh_resolution_mm=mesh_resolution_mm, excite_port=k))

    cache_dir = root / ".smatrix_cache" if cache else None
    salt = "" if line_z0 is None else f"line_z0={line_z0!r};z_ref={z_ref_ohm!r}"
    key = _script_hash(scripts, exe_path, salt=salt)
    cached = _load_cache(cache_dir, key)
    if cached is not None:
        return {**cached, "s4p_path": str(root / f"{template}.s{n_ports}p"),
                "n_runs": n_ports, "elapsed_s": 0.0}

    python_exe = sys.executable
    freq_ghz: Any = None
    s_params: Any = None
    run_errors: list[str] = []
    resumed: list[int] = []

    def _absorb_round(fg: Any, col: list[Any], k: int) -> str | None:
        """装配第 k 列；首轮定频率轴，后续轮轴不一致显式报错。

        槽位数≠n_ports 返回 _SLOT_GUARD（断点复用路径按损坏产物重跑该轮，
        而非装配出残缺矩阵）。
        """
        nonlocal freq_ghz, s_params
        if len(col) != n_ports:
            return _SLOT_GUARD
        if freq_ghz is None:
            freq_ghz = fg
            s_params = np.zeros((len(fg), n_ports, n_ports), dtype=complex)
        elif not np.allclose(fg, freq_ghz):
            return f"p{k} 频率轴与 p1 不一致"
        for i in range(n_ports):
            s_params[:, i, k - 1] = col[i]
        return None

    for k in range(1, n_ports + 1):
        work_k = root / f"p{k}"
        work_k.mkdir(parents=True, exist_ok=True)
        script_path = work_k / "simulation.py"
        csv_path = work_k / "sparams.csv"
        # 逐轮断点缓存：脚本逐字节一致（=轮次身份，防换参陈旧产物）且
        # CSV 可解析才复用；任一不满足重跑该轮。
        round_data = _load_round_csv(csv_path, n_ports) if resume else None
        if round_data is not None:
            prev_script: str | None = None
            with suppress(OSError):
                prev_script = script_path.read_text(encoding="utf-8")
            if prev_script != scripts[k - 1]:
                round_data = None
        if round_data is not None:
            err = _absorb_round(round_data[0], round_data[1], k)
            if err == _SLOT_GUARD:
                round_data = None  # 槽位守卫：按损坏产物重跑该轮
            elif err is not None:
                return {"ok": False, "errors": [err]}
            else:
                resumed.append(k)
                continue
        script_path.write_text(scripts[k - 1], encoding="utf-8")
        runner = work_k / "_rfauto_runner.py"
        if exe_path:
            exe_dir = str(Path(exe_path).resolve().parent)
            runner.write_text(
                "import os\nimport runpy\nimport sys\n"
                f"os.add_dll_directory({exe_dir!r})\n"
                f"os.environ['PATH'] = {exe_dir!r} + os.pathsep + "
                "os.environ.get('PATH', '')\n"
                "runpy.run_path(sys.argv[1], run_name='__main__')\n",
                encoding="utf-8")
        cmd = [python_exe]
        cmd += ([str(runner.resolve()), str(script_path.resolve())]
                if runner.exists() else [str(script_path.resolve())])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout_s,
                                  cwd=str(work_k.resolve()))
        except subprocess.TimeoutExpired:
            return {"ok": False,
                    "errors": [f"p{k} 仿真超时（>{timeout_s}s）"]}
        if not csv_path.exists():
            return {"ok": False, "errors": [
                f"p{k} 无产物（rc={proc.returncode}）；stderr 尾: "
                f"{(proc.stderr or '')[-800:]}"]}
        round_data = _load_round_csv(csv_path, n_ports)
        if round_data is None:
            return {"ok": False, "errors": [
                f"p{k} 产物不可解析（rc={proc.returncode}）；stderr 尾: "
                f"{(proc.stderr or '')[-800:]}"]}
        err = _absorb_round(round_data[0], round_data[1], k)
        if err is not None:
            return {"ok": False, "errors": [err]}

    import skrf

    freq = skrf.Frequency(float(freq_ghz[0]), float(freq_ghz[-1]),
                          len(freq_ghz), unit="GHz")
    s4p = root / f"{template}.s{n_ports}p"
    s_out = s_params
    norm_info: dict[str, Any] | None = None
    if line_z0 is not None:
        s_out, norm_info = normalize_assembled_smatrix(
            s_params, freq_ghz, line_z0, n_ports=n_ports, root=root,
            z_ref_ohm=z_ref_ohm)
        raw_path = root / f"{template}_raw.s{n_ports}p"
        skrf.Network(frequency=freq, s=s_params,
                     z0=z_ref_ohm).write_touchstone(str(raw_path))
        norm_info["raw_s4p_path"] = str(raw_path)
    net = skrf.Network(frequency=freq, s=s_out, z0=z_ref_ohm)
    net.write_touchstone(str(s4p))
    _store_cache(cache_dir, key, freq_ghz, s_out, assembly_norm=norm_info)

    message = "全 S 矩阵完成（进程隔离激励轮转）"
    if resumed:
        message += f"；断点复用 p{','.join(str(k) for k in resumed)}"
    if norm_info is not None:
        zs = "/".join(f"{z:.2f}" for z in norm_info["line_z0_ohm"])
        message += (f"；装配归一 line_z0={norm_info['mode']}（ZL {zs}Ω，"
                    f"σmax {norm_info['sigma_max_raw']:.4f}→"
                    f"{norm_info['sigma_max_norm']:.4f}）")
    return {"ok": True, "freq_ghz": freq_ghz, "s_params": s_out,
            "s_params_raw": s_params, "assembly_norm": norm_info,
            "s4p_path": str(s4p), "n_runs": n_ports,
            "n_reused": len(resumed), "resumed_rounds": resumed,
            "message": message,
            "errors": run_errors,
            "elapsed_s": round(time.time() - t0, 1)}

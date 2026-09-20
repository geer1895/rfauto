"""厂商被动元件库确定性内核。

职责（数值只在确定性内核）：
- 元件 registry：catalog.yaml 索引（vendor/mpn/type/nominal_value/srf_ghz/
  esr_ohm/model_file/sha256/source_url/license_note/synthetic/downloaded_at），
  按 part_id 加载 + sha256 校验（不符 → ValueError 硬错，这是 provenance 门
  不是 #105 观测性；真实厂商条目缺 sha 也硬错）。
- S2P → Z：1 端口 Z=Z0(1+Γ)/(1−Γ)；2 端口串联件 Z=ABCD 的 B，并与 −1/Y21
  交叉核对（诊断量，不硬错——厂商实测件含夹具寄生时两者可轻微分歧）。
- 指标提取：SRF（|Z| 峰/谷 + log|Z| 三点抛物线细化；Im(Z) 过零交叉核对）、
  L_eff(f)=Im(Z)/ω、C_eff(f)=−1/(ω·Im(Z))、Q(f)=Im(Z)/Re(Z)。
- 合成 RLC 模型生成器（写盘字节确定，不依赖 skrf 写盘格式——#175）：
  电感 Z=(Rs+jωL)∥(1/jωCp)；电容 Z=ESR+1/(jωC)+jωESL。
- 匹配链真元件替换：给定 MatchNetworkResult 的元件表（负载端→源端），
  指定槽位用真实元件阻抗曲线替换理想 LCElement，递推 Zin 并产出偏差报告
  （Δmatch_depth_dB / L_eff/L_nom / SRF/f0 / 最佳匹配频点偏移）。

厂商条款纪律：模型文件（*.s2p/*.lib/*.cir 等）按厂商条款经下载器获取，
永不入 git；catalog 只留索引+哈希+来源 URL+条款备注。
官方出处：Murata SimSurfing（murata.com/en-us/tool/simsurfing）、
Coilcraft SPICE 模型（coilcraft.com/en-us/models/spice）。
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.matching import LCElement, MatchNetworkResult

DEFAULT_Z0 = 50.0
CATALOG_FILENAME = "catalog.yaml"
_TOUCHSTONE_FMT = "%.12e"

# catalog.yaml 规范头（write_catalog 每次整文件重写时回带，保证往返稳定）。
CATALOG_HEADER = """# 厂商被动元件库索引（C15）：S 参数/SPICE 模型按 part_id 引用，不硬编码路径。
#
# 条款纪律：模型文件按厂商条款经 scripts/vendor_passive_download.py 下载到
# 本目录，**永不入 git**（.gitignore 目录级兜底）；catalog 只留索引+sha256+来源。
# 官方出处：Murata SimSurfing https://www.murata.com/en-us/tool/simsurfing
#           Coilcraft SPICE https://www.coilcraft.com/en-us/models/spice/
# 加载入口：core.vendor_passives.load_part（严格：缺文件 KeyError/哈希不符
# ValueError）；core.vendor_passives.validate_catalog（宽松盘点，缺文件
# skip-not-fail 只标状态）。
# synthetic 条目：模型文件由 core 生成器确定性再现（synthesize_seed_model_file），
# sha256 留空不钉死（生成即校验，见测试）；真实厂商条目 sha256 必填。
# 字段：vendor/mpn/type(inductor|capacitor)/nominal_value(H|F)/srf_ghz/esr_ohm/
#       model_file(与本文件同目录)/sha256/source_url/license_note/
#       synthetic/downloaded_at。
"""


# ─── registry 条目 ───────────────────────────────────────────────────────────

_REQUIRED_FIELDS = ("vendor", "mpn", "type", "nominal_value", "model_file")
_PART_TYPES = ("inductor", "capacitor")


@dataclass(frozen=True)
class VendorPartEntry:
    """catalog.yaml 单条元件索引（part_id 为映射键）。"""

    part_id: str
    vendor: str
    mpn: str
    type: str  # "inductor" | "capacitor"
    nominal_value: float  # H（电感）或 F（电容）
    model_file: str  # 与 catalog 同目录的模型文件名
    srf_ghz: float | None = None  # 厂商 datasheet 值；synthetic 为闭式推导值
    esr_ohm: float | None = None
    sha256: str | None = None  # None 仅允许 synthetic（provenance 门）
    source_url: str = ""
    license_note: str = ""
    synthetic: bool = False
    downloaded_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "vendor": self.vendor,
            "mpn": self.mpn,
            "type": self.type,
            "nominal_value": self.nominal_value,
            "model_file": self.model_file,
            "srf_ghz": self.srf_ghz,
            "esr_ohm": self.esr_ohm,
            "sha256": self.sha256,
            "source_url": self.source_url,
            "license_note": self.license_note,
            "synthetic": self.synthetic,
            "downloaded_at": self.downloaded_at,
        }

    @classmethod
    def from_dict(cls, part_id: str, raw: dict[str, Any]) -> VendorPartEntry:
        if not isinstance(raw, dict):
            raise ValueError(f"catalog 条目 {part_id!r} 必须是映射，实际 {type(raw).__name__}")
        missing = [key for key in _REQUIRED_FIELDS if raw.get(key) is None]
        if missing:
            raise ValueError(f"catalog 条目 {part_id!r} 缺必填字段: {missing}")
        part_type = str(raw["type"])
        if part_type not in _PART_TYPES:
            raise ValueError(f"catalog 条目 {part_id!r} type 必须是 {_PART_TYPES} 之一，实际 {part_type!r}")
        nominal = float(raw["nominal_value"])
        if not math.isfinite(nominal) or nominal <= 0.0:
            raise ValueError(f"catalog 条目 {part_id!r} nominal_value 必须为正有限数")
        sha = raw.get("sha256") or None
        synthetic = bool(raw.get("synthetic", False))
        if sha is None and not synthetic:
            # provenance 门：真实厂商模型必须留哈希，否则下载产物不可追责
            raise ValueError(f"catalog 条目 {part_id!r} 为真实厂商模型，sha256 必填（synthetic 条目可空）")
        srf = raw.get("srf_ghz")
        esr = raw.get("esr_ohm")
        return cls(
            part_id=str(part_id),
            vendor=str(raw["vendor"]),
            mpn=str(raw["mpn"]),
            type=part_type,
            nominal_value=nominal,
            model_file=str(raw["model_file"]),
            srf_ghz=None if srf is None else float(srf),
            esr_ohm=None if esr is None else float(esr),
            sha256=None if sha is None else str(sha),
            source_url=str(raw.get("source_url", "")),
            license_note=str(raw.get("license_note", "")),
            synthetic=synthetic,
            downloaded_at=None if raw.get("downloaded_at") is None else str(raw["downloaded_at"]),
        )


def default_catalog_path() -> Path:
    """工作区默认 catalog：knowledge/vendor_passives/catalog.yaml。"""
    return Path(__file__).resolve().parents[3] / "knowledge" / "vendor_passives" / CATALOG_FILENAME


def default_directory() -> Path:
    return default_catalog_path().parent


def sha256_file(path: str | Path) -> str:
    """文件字节流的 SHA-256（分块读取）。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_catalog(catalog_path: str | Path | None = None) -> dict[str, VendorPartEntry]:
    """读 catalog → {part_id: VendorPartEntry}（单条不合法即 ValueError，硬错）。"""
    path = Path(catalog_path) if catalog_path is not None else default_catalog_path()
    if not path.exists():
        raise KeyError(f"catalog 不存在: {path}")
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_parts = data.get("vendor_passives") or {}
    if not isinstance(raw_parts, dict):
        raise ValueError(f"catalog 结构必须是 vendor_passives: {{part_id: ...}}: {path}")
    return {str(pid): VendorPartEntry.from_dict(str(pid), raw) for pid, raw in raw_parts.items()}


def write_catalog(catalog_path: str | Path, parts: dict[str, VendorPartEntry]) -> Path:
    """整文件重写 catalog（规范头 + yaml dump），往返稳定。"""
    path = Path(catalog_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import yaml

    payload = {
        str(pid): _entry_yaml_dict(entry)
        for pid, entry in sorted(parts.items())
    }
    body = yaml.safe_dump(
        {"vendor_passives": payload},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=100,
    )
    path.write_text(CATALOG_HEADER + body, encoding="utf-8")
    return path


def _entry_yaml_dict(entry: VendorPartEntry) -> dict[str, Any]:
    return {
        "vendor": entry.vendor,
        "mpn": entry.mpn,
        "type": entry.type,
        "nominal_value": entry.nominal_value,
        "srf_ghz": entry.srf_ghz,
        "esr_ohm": entry.esr_ohm,
        "model_file": entry.model_file,
        "sha256": entry.sha256,
        "source_url": entry.source_url,
        "license_note": entry.license_note,
        "synthetic": entry.synthetic,
        "downloaded_at": entry.downloaded_at,
    }


@dataclass
class PartStatus:
    """validate_catalog 的逐条状态（宽松盘点，缺文件 skip-not-fail）。"""

    part_id: str
    status: str  # "ok" | "unverified" | "file_missing" | "hash_mismatch" | "invalid_entry"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"part_id": self.part_id, "status": self.status, "detail": self.detail}


def validate_catalog(
    catalog_path: str | Path | None = None,
    directory: str | Path | None = None,
) -> list[PartStatus]:
    """逐条盘点 registry：文件缺失/哈希不符只标状态，绝不抛异常（skip-not-fail）。

    哈希不符在盘点里也只标 "hash_mismatch"（可见即报）；真正消费模型时
    load_part 才硬错。
    """
    path = Path(catalog_path) if catalog_path is not None else default_catalog_path()
    d = Path(directory) if directory is not None else path.parent
    try:
        entries = read_catalog(path)
    except Exception as exc:
        return [PartStatus(part_id="<catalog>", status="invalid_entry", detail=str(exc))]
    statuses: list[PartStatus] = []
    for part_id, entry in entries.items():
        model_path = d / entry.model_file
        if not model_path.exists():
            statuses.append(PartStatus(part_id, "file_missing", str(model_path)))
            continue
        if entry.sha256 is None:
            # synthetic 未钉哈希：文件在场即 "unverified"（生成即校验归测试管）
            statuses.append(PartStatus(part_id, "unverified" if entry.synthetic else "file_missing",
                                       "sha256 未登记"))
            continue
        actual = sha256_file(model_path)
        if actual != entry.sha256:
            statuses.append(PartStatus(part_id, "hash_mismatch",
                                       f"catalog={entry.sha256} actual={actual}"))
            continue
        statuses.append(PartStatus(part_id, "ok"))
    return statuses


@dataclass
class LoadedPart:
    """严格加载结果：条目 + 阻抗曲线（provenance 校验已通过）。"""

    entry: VendorPartEntry
    curve: ImpedanceCurve
    model_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry.to_dict(),
            "model_path": str(self.model_path),
            "n_freq": int(self.curve.freqs_hz.size),
            "freq_range_ghz": [float(self.curve.freqs_hz[0] / 1e9), float(self.curve.freqs_hz[-1] / 1e9)],
            "n_ports": self.curve.n_ports,
            "z0": self.curve.z0,
        }


def load_part(
    part_id: str,
    catalog_path: str | Path | None = None,
    directory: str | Path | None = None,
) -> LoadedPart:
    """按 part_id 严格加载元件（provenance 门：缺文件 KeyError/哈希不符 ValueError）。

    - catalog 无此 ID → KeyError；
    - 模型文件缺失 → KeyError（与 load_calkit 同口径）；
    - sha256 已登记且不符 → ValueError（硬错，provenance 门）；
    - synthetic 条目 sha256 为空 → 放行（文件由生成器确定性再现）。
    """
    path = Path(catalog_path) if catalog_path is not None else default_catalog_path()
    d = Path(directory) if directory is not None else path.parent
    entries = read_catalog(path)
    entry = entries.get(part_id)
    if entry is None:
        raise KeyError(f"catalog 中无此元件: {part_id}")
    model_path = Path(d) / entry.model_file
    if not model_path.exists():
        raise KeyError(f"模型文件缺失: {entry.model_file}（元件 {part_id}，可由下载器获取）")
    if entry.sha256 is not None:
        actual = sha256_file(model_path)
        if actual != entry.sha256:
            raise ValueError(
                f"模型文件 sha256 不符（provenance 门）：元件 {part_id} "
                f"catalog={entry.sha256} actual={actual}"
            )
    return LoadedPart(entry=entry, curve=load_impedance_curve(model_path), model_path=model_path)


# ─── S2P → Z ────────────────────────────────────────────────────────────────

@dataclass
class ImpedanceCurve:
    """元件阻抗曲线（f 升序），支持标量/数组插值取值。"""

    freqs_hz: np.ndarray  # (n,) float，升序
    z: np.ndarray  # (n,) complex
    n_ports: int = 2
    z0: float = DEFAULT_Z0
    series_crosscheck_rel: float | None = None  # 2 端口：max|Z_abcd−Z_y21|/|Z_abcd| 诊断

    def at(self, f_hz: float | np.ndarray) -> complex | np.ndarray:
        """线性插值取 Z（Re/Im 分别插值）；越界取端点值。"""
        freqs = np.atleast_1d(np.asarray(f_hz, dtype=float))
        re = np.interp(freqs, self.freqs_hz, self.z.real)
        im = np.interp(freqs, self.freqs_hz, self.z.imag)
        out = re + 1j * im
        return complex(out[0]) if np.ndim(f_hz) == 0 else out


def load_impedance_curve(
    model_file: str | Path,
    z0: float = DEFAULT_Z0,
    topology: str | None = None,
) -> ImpedanceCurve:
    """读 Touchstone → 阻抗曲线。

    - 1 端口（shunt 测量）：Z = Z0(1+Γ)/(1−Γ)；
    - 2 端口（串联直通测量）：Z = ABCD 的 B，并与 −1/Y21 交叉核对
      （纯串联件两者数学恒等；诊断量 max 相对差存 series_crosscheck_rel）；
    - 其它端口数 ValueError。
    topology: None 自动按端口数判定；显式 "series_2port"/"one_port" 强制。
    """
    import skrf

    path = Path(model_file)
    if not path.exists():
        raise KeyError(f"模型文件缺失: {path}")
    net = skrf.Network(str(path))
    freqs = np.asarray(net.f, dtype=float)
    if topology is None:
        topology = "series_2port" if net.nports == 2 else ("one_port" if net.nports == 1 else None)
    if topology == "series_2port":
        if net.nports != 2:
            raise ValueError(f"topology=series_2port 需要 2 端口文件，实际 {net.nports}: {path}")
        z_abcd = np.asarray(net.a[:, 0, 1], dtype=complex)
        z_y21 = -1.0 / np.asarray(net.y[:, 1, 0], dtype=complex)
        scale = np.maximum(np.abs(z_abcd), 1e-300)
        crosscheck = float(np.max(np.abs(z_abcd - z_y21) / scale))
        return ImpedanceCurve(freqs_hz=freqs, z=z_abcd, n_ports=2, z0=z0, series_crosscheck_rel=crosscheck)
    if topology == "one_port":
        if net.nports != 1:
            raise ValueError(f"topology=one_port 需要 1 端口文件，实际 {net.nports}: {path}")
        gamma = np.asarray(net.s[:, 0, 0], dtype=complex)
        z = z0 * (1.0 + gamma) / (1.0 - gamma)
        return ImpedanceCurve(freqs_hz=freqs, z=z, n_ports=1, z0=z0)
    raise ValueError(f"不支持的模型端口面（nports={net.nports}, topology={topology!r}）: {path}")


# ─── 指标提取 ────────────────────────────────────────────────────────────────

def effective_inductance(f_hz: float, z: complex) -> float:
    """L_eff(f) = Im(Z)/ω (H)。"""
    return float(np.imag(z)) / (2.0 * math.pi * f_hz)


def effective_capacitance(f_hz: float, z: complex) -> float:
    """C_eff(f) = −1/(ω·Im(Z)) (F)（容性 Im<0 时为正）。"""
    im = float(np.imag(z))
    if im >= 0.0:
        raise ValueError(f"该频点非容性（Im(Z)={im:.6g} ≥ 0），C_eff 无意义")
    return -1.0 / (2.0 * math.pi * f_hz * im)


def q_factor(z: complex) -> float:
    """Q(f) = Im(Z)/Re(Z)（电感语境；电容语境取绝对值/符号由调用方解释）。"""
    return float(np.imag(z) / np.real(z))


def extract_srf(freqs_hz: np.ndarray, z: np.ndarray, mode: str = "peak") -> float | None:
    """|Z| 极值定位 SRF：peak=并联谐振峰（电感），valley=串联谐振谷（电容）。

    log|Z| 三点抛物线细化（网格步长内亚精度）；极值落在频带边缘 → None
    （SRF 不在带内，不硬凑数字）。
    """
    if mode not in ("peak", "valley"):
        raise ValueError(f"mode 必须是 peak/valley，实际 {mode!r}")
    freqs = np.asarray(freqs_hz, dtype=float)
    logmag = np.log(np.abs(np.asarray(z, dtype=complex)))
    if freqs.size < 3:
        raise ValueError("extract_srf 至少需要 3 个频点")
    idx = int(np.argmax(logmag) if mode == "peak" else np.argmin(logmag))
    if idx in (0, freqs.size - 1):
        return None
    y0, y1, y2 = (float(v) for v in logmag[idx - 1: idx + 2])
    denom = y0 - 2.0 * y1 + y2
    delta = 0.0 if denom == 0.0 else 0.5 * (y0 - y2) / denom
    step = 0.5 * ((freqs[idx] - freqs[idx - 1]) + (freqs[idx + 1] - freqs[idx]))
    return float(freqs[idx] + delta * step)


def im_zero_crossings(freqs_hz: np.ndarray, z: np.ndarray) -> list[tuple[float, str]]:
    """Im(Z) 过零点（线性插值），返回 [(f_hz, "增长→容性" | "容性→增长")]。

    电感并联谐振 = "+"→"−"（感性转容性）；电容串联谐振 = "−"→"+"。
    """
    freqs = np.asarray(freqs_hz, dtype=float)
    im = np.imag(np.asarray(z, dtype=complex))
    out: list[tuple[float, str]] = []
    for i in range(freqs.size - 1):
        a, b = float(im[i]), float(im[i + 1])
        if a == 0.0 and b != 0.0:
            # 网格点恰为 0：方向由下一采样符号定（合成模型连续，罕见角隅）
            out.append((float(freqs[i]), "inductive_to_capacitive" if b < 0.0 else "capacitive_to_inductive"))
            continue
        if (a > 0.0 >= b) or (a < 0.0 <= b):
            f_zero = float(freqs[i] + (freqs[i + 1] - freqs[i]) * a / (a - b))
            direction = "inductive_to_capacitive" if a > 0.0 else "capacitive_to_inductive"
            out.append((f_zero, direction))
    return out


# ─── 合成 RLC 模型生成器（写盘字节确定）──────────────────────────────────────

def synthesize_rlc_inductor_z(
    freqs_hz: np.ndarray,
    l_h: float,
    rs_ohm: float,
    cp_f: float,
) -> np.ndarray:
    """合成电感 Z = (Rs+jωL) ∥ (1/jωCp)；SRF = 1/(2π√(L·Cp))（|Z| 峰）。"""
    w = 2.0 * math.pi * np.asarray(freqs_hz, dtype=float)
    z_series = rs_ohm + 1j * w * l_h
    z_par = 1.0 / (1j * w * cp_f)
    return z_series * z_par / (z_series + z_par)


def synthesize_rlc_capacitor_z(
    freqs_hz: np.ndarray,
    c_f: float,
    esr_ohm: float,
    esl_h: float,
) -> np.ndarray:
    """合成电容 Z = ESR + 1/(jωC) + jωESL；SRF = 1/(2π√(C·ESL))（|Z| 谷）。"""
    w = 2.0 * math.pi * np.asarray(freqs_hz, dtype=float)
    return esr_ohm + 1.0 / (1j * w * c_f) + 1j * w * esl_h


def _touchstone_text(
    freqs_hz: np.ndarray,
    s_rows: list[tuple[np.ndarray, ...]],
    n_ports: int,
    z0: float,
    comment: str,
) -> str:
    """定长格式 Touchstone 文本（GHz/RI）；字节确定，不依赖 skrf 写盘（#175）。"""
    lines = [f"! {line}" for line in comment.splitlines() if line.strip()]
    lines.append(f"# GHZ S RI R {z0:g}")
    for f_hz, row in zip(freqs_hz, s_rows, strict=True):
        cols = [(_TOUCHSTONE_FMT % (f_hz / 1e9))]
        for s_complex in row:
            cols.append(_TOUCHSTONE_FMT % float(np.real(s_complex)))
            cols.append(_TOUCHSTONE_FMT % float(np.imag(s_complex)))
        lines.append(" ".join(cols))
    return "\n".join(lines) + "\n"


def write_touchstone_series_2port(
    path: str | Path,
    freqs_hz: np.ndarray,
    z: np.ndarray,
    z0: float = DEFAULT_Z0,
    comment: str = "",
) -> Path:
    """把串联元件阻抗写成 2 端口 Touchstone（S11=S22=Z/(2Z0+Z)，S21=S12=2Z0/(2Z0+Z)）。"""
    freqs = np.atleast_1d(np.asarray(freqs_hz, dtype=float))
    z_arr = np.asarray(z, dtype=complex)
    if z_arr.ndim == 0:
        z_arr = np.full(freqs.shape, complex(z_arr))
    s11 = z_arr / (2.0 * z0 + z_arr)
    s21 = 2.0 * z0 / (2.0 * z0 + z_arr)
    rows = [(s11[i], s21[i], s21[i], s11[i]) for i in range(freqs.size)]
    text = _touchstone_text(freqs, rows, 2, z0, comment)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="ascii")
    return out


def write_touchstone_one_port(
    path: str | Path,
    freqs_hz: np.ndarray,
    z: np.ndarray,
    z0: float = DEFAULT_Z0,
    comment: str = "",
) -> Path:
    """把 1 端口反射阻抗写成 Touchstone（Γ=(Z−Z0)/(Z+Z0)）。"""
    freqs = np.atleast_1d(np.asarray(freqs_hz, dtype=float))
    z_arr = np.asarray(z, dtype=complex)
    if z_arr.ndim == 0:
        z_arr = np.full(freqs.shape, complex(z_arr))
    gamma = (z_arr - z0) / (z_arr + z0)
    rows = [(gamma[i],) for i in range(freqs.size)]
    text = _touchstone_text(freqs, rows, 1, z0, comment)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="ascii")
    return out


def synthesize_seed_model_file(entry: VendorPartEntry, directory: str | Path) -> tuple[Path, str]:
    """由 synthetic 条目元数据确定性再现模型文件，返回 (路径, sha256)。

    电感：L=nominal_value、Rs=esr_ohm、Cp 由 srf_ghz 闭式反推
    （Cp = 1/((2π·f_srf)²·L)）；电容：C=nominal_value、ESR=esr_ohm、
    ESL 由 srf_ghz 反推（ESL = 1/((2π·f_srf)²·C)）。
    频带固定 [0.05, 3]×f_srf、4001 点——同一条目跨会话字节相同。
    """
    if not entry.synthetic:
        raise ValueError(f"只允许再现 synthetic 条目，实际 {entry.part_id!r}")
    if entry.srf_ghz is None or entry.esr_ohm is None:
        raise ValueError(f"synthetic 条目 {entry.part_id!r} 缺 srf_ghz/esr_ohm，无法再现")
    f_srf = entry.srf_ghz * 1e9
    freqs = np.linspace(0.05 * f_srf, 3.0 * f_srf, 4001)
    comment = (
        f"synthetic {entry.type} {entry.part_id} "
        f"nominal={entry.nominal_value:g} esr={entry.esr_ohm:g} srf={entry.srf_ghz:g}GHz "
        "(rfauto core.vendor_passives generator)"
    )
    out = Path(directory) / entry.model_file
    if entry.type == "inductor":
        cp = 1.0 / ((2.0 * math.pi * f_srf) ** 2 * entry.nominal_value)
        z = synthesize_rlc_inductor_z(freqs, entry.nominal_value, entry.esr_ohm, cp)
        path = write_touchstone_series_2port(out, freqs, z, comment=comment)
    else:
        esl = 1.0 / ((2.0 * math.pi * f_srf) ** 2 * entry.nominal_value)
        z = synthesize_rlc_capacitor_z(freqs, entry.nominal_value, entry.esr_ohm, esl)
        path = write_touchstone_series_2port(out, freqs, z, comment=comment)
    return path, sha256_file(path)


# ─── 匹配链真元件替换 + 偏差报告（§10.22 #24 口径）───────────────────────────

def _replacement_z(rep: Any, f_ghz: float) -> complex:
    """替换槽位取值：ImpedanceCurve 按频率插值，其余按复数常量。"""
    if isinstance(rep, ImpedanceCurve):
        return rep.at(f_ghz * 1e9)
    return complex(rep)


def chain_input_impedance(
    elements: list[LCElement],
    z_load: float,
    f_ghz: float,
    replacements: dict[int, Any] | None = None,
) -> complex:
    """匹配链 Zin 递推（负载端→源端），replacements={槽位序号: 真实阻抗}。

    槽位序号是 elements（负载端→源端）里的下标；未替换槽位走理想
    LCElement.impedance。无替换时与 MatchNetworkResult.input_impedance
    同式同序（回归钉：身份一致 <1e-12）。
    """
    omega = 2.0 * math.pi * float(f_ghz) * 1e9
    impedance = complex(z_load)
    reps = replacements or {}
    for index, element in enumerate(elements):  # 负载端 → 源端
        rep = reps.get(index)
        branch = element.impedance(omega) if rep is None else _replacement_z(rep, float(f_ghz))
        impedance = (
            impedance + branch
            if element.role == "series"
            else 1.0 / (1.0 / impedance + 1.0 / branch)
        )
    return impedance


@dataclass
class SlotReplacementReport:
    """单个替换槽位的真元件指标（对照理想元件值）。"""

    slot_index: int
    slot_kind: str  # "L" | "C"
    slot_role: str  # "series" | "shunt"
    nominal_value: float  # H 或 F（理想元件值）
    eff_value: float | None  # 真元件在 f0 的有效值（H 或 F；非预期极性 → None）
    eff_over_nom: float | None
    srf_ghz: float | None  # L→|Z| 峰，C→|Z| 谷；不在带内 → None
    srf_over_f0: float | None
    series_crosscheck_rel: float | None  # 2 端口 ABCD-B vs −1/Y21 诊断

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_index": self.slot_index,
            "slot_kind": self.slot_kind,
            "slot_role": self.slot_role,
            "nominal_value": self.nominal_value,
            "eff_value": self.eff_value,
            "eff_over_nom": self.eff_over_nom,
            "srf_ghz": self.srf_ghz,
            "srf_over_f0": self.srf_over_f0,
            "series_crosscheck_rel": self.series_crosscheck_rel,
        }


@dataclass
class MatchDeviationReport:
    """真元件替换匹配链偏差报告（§10.22 #24：接真实元件 S2P，±0.1dB 对拍口径）。

    match_depth_db = −20·log10|S11|（正值，越大越深；理想链在 f0 精确匹配 → +inf）。
    f0 处 Δ 因理想链为 +inf 而恒为 −inf（JSON→None），有限量化看 band_*：
    排除理想深度 >60 dB 的零点邻域（沿用 test_matching 口径）后逐点 |Δ| 的
    max/mean。
    """

    topology: str
    response: str
    f0_ghz: float
    z_source: float
    z_load: float
    freqs_ghz: list[float] = field(default_factory=list)
    ideal_match_depth_db: list[float] = field(default_factory=list)
    real_match_depth_db: list[float] = field(default_factory=list)
    ideal_match_depth_db_f0: float | None = None
    real_match_depth_db_f0: float | None = None
    delta_match_depth_db_f0: float | None = None  # real − ideal（理想 +inf 时为 −inf）
    band_max_abs_delta_db: float | None = None  # 排除零点邻域后逐点 |Δ| 最大
    band_mean_abs_delta_db: float | None = None
    n_band_points_compared: int = 0
    ideal_best_f_ghz: float | None = None
    real_best_f_ghz: float | None = None
    best_freq_offset_ghz: float | None = None  # 网格量化（默认步长 f0/200）
    slots: list[SlotReplacementReport] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topology": self.topology,
            "response": self.response,
            "f0_ghz": self.f0_ghz,
            "z_source": self.z_source,
            "z_load": self.z_load,
            "freqs_ghz": self.freqs_ghz,
            "ideal_match_depth_db": self.ideal_match_depth_db,
            "real_match_depth_db": self.real_match_depth_db,
            "ideal_match_depth_db_f0": self.ideal_match_depth_db_f0,
            "real_match_depth_db_f0": self.real_match_depth_db_f0,
            "delta_match_depth_db_f0": self.delta_match_depth_db_f0,
            "band_max_abs_delta_db": self.band_max_abs_delta_db,
            "band_mean_abs_delta_db": self.band_mean_abs_delta_db,
            "n_band_points_compared": self.n_band_points_compared,
            "ideal_best_f_ghz": self.ideal_best_f_ghz,
            "real_best_f_ghz": self.real_best_f_ghz,
            "best_freq_offset_ghz": self.best_freq_offset_ghz,
            "slots": [slot.to_dict() for slot in self.slots],
        }


_NULL_NEIGHBOURHOOD_DB = 60.0  # 理想链零点邻域：深度 >60 dB 无有效 dB 比较（test_matching 同口径）


def _match_depth_db(z_in: complex, z_ref: float) -> float:
    """回波损耗深度 −20·log10|S11|（正值；|S11|=0 → +inf）。"""
    s11 = (z_in - z_ref) / (z_in + z_ref)
    magnitude = abs(s11)
    return math.inf if magnitude == 0.0 else -20.0 * math.log10(magnitude)


def match_deviation_report(
    result: MatchNetworkResult,
    replacements: dict[int, Any],
    freqs_ghz: np.ndarray | list[float] | None = None,
) -> MatchDeviationReport:
    """真元件替换 vs 理想闭式链的偏差报告。

    freqs_ghz 缺省 [0.75, 1.25]×f0 共 101 点（奇数点保证 f0 恰在网格上）。
    槽位指标：eff_value 按 kind 取 L_eff/C_eff；SRF 按 kind 取 |Z| 峰/谷。
    """
    freqs = (
        np.linspace(0.75 * result.f0_ghz, 1.25 * result.f0_ghz, 101)
        if freqs_ghz is None
        else np.atleast_1d(np.asarray(freqs_ghz, dtype=float))
    )
    ideal_depth = [_match_depth_db(result.input_impedance(float(f)), result.z_source) for f in freqs]
    real_zin = [chain_input_impedance(result.elements, result.z_load, float(f), replacements) for f in freqs]
    real_depth = [_match_depth_db(z, result.z_source) for z in real_zin]

    idx_f0 = int(np.argmin(np.abs(freqs - result.f0_ghz)))
    ideal_depth_f0 = ideal_depth[idx_f0]
    real_depth_f0 = real_depth[idx_f0]
    best_ideal = float(freqs[int(np.argmax(np.asarray(ideal_depth, dtype=float)))])
    best_real = float(freqs[int(np.argmax(np.asarray(real_depth, dtype=float)))])

    # 带内有限量化：排除理想链零点邻域（深度 >60 dB）后逐点 |Δ|
    band_deltas = [
        abs(real_value - ideal_value)
        for ideal_value, real_value in zip(ideal_depth, real_depth, strict=True)
        if ideal_value <= _NULL_NEIGHBOURHOOD_DB and math.isfinite(real_value)
    ]
    band_max = max(band_deltas) if band_deltas else None
    band_mean = (sum(band_deltas) / len(band_deltas)) if band_deltas else None

    slots: list[SlotReplacementReport] = []
    for slot_index, rep in sorted(replacements.items()):
        element = result.elements[slot_index]
        if isinstance(rep, ImpedanceCurve):
            z_f0 = rep.at(result.f0_ghz * 1e9)
            if element.kind == "L":
                eff: float | None = effective_inductance(result.f0_ghz * 1e9, z_f0) if np.imag(z_f0) > 0 else None
                srf = extract_srf(rep.freqs_hz, rep.z, mode="peak")
            else:
                eff = effective_capacitance(result.f0_ghz * 1e9, z_f0) if np.imag(z_f0) < 0 else None
                srf = extract_srf(rep.freqs_hz, rep.z, mode="valley")
            slots.append(SlotReplacementReport(
                slot_index=slot_index,
                slot_kind=element.kind,
                slot_role=element.role,
                nominal_value=element.value,
                eff_value=eff,
                eff_over_nom=None if eff is None else eff / element.value,
                srf_ghz=None if srf is None else srf / 1e9,
                srf_over_f0=None if srf is None else srf / 1e9 / result.f0_ghz,
                series_crosscheck_rel=rep.series_crosscheck_rel,
            ))
        else:
            z_f0 = complex(rep)
            if element.kind == "L":
                eff = effective_inductance(result.f0_ghz * 1e9, z_f0) if z_f0.imag > 0 else None
            else:
                eff = effective_capacitance(result.f0_ghz * 1e9, z_f0) if z_f0.imag < 0 else None
            slots.append(SlotReplacementReport(
                slot_index=slot_index,
                slot_kind=element.kind,
                slot_role=element.role,
                nominal_value=element.value,
                eff_value=eff,
                eff_over_nom=None if eff is None else eff / element.value,
                srf_ghz=None,
                srf_over_f0=None,
                series_crosscheck_rel=None,
            ))

    return MatchDeviationReport(
        topology=result.topology,
        response=result.response,
        f0_ghz=result.f0_ghz,
        z_source=result.z_source,
        z_load=result.z_load,
        freqs_ghz=[float(f) for f in freqs],
        ideal_match_depth_db=list(ideal_depth),
        real_match_depth_db=list(real_depth),
        ideal_match_depth_db_f0=ideal_depth_f0,
        real_match_depth_db_f0=real_depth_f0,
        delta_match_depth_db_f0=real_depth_f0 - ideal_depth_f0,
        band_max_abs_delta_db=band_max,
        band_mean_abs_delta_db=band_mean,
        n_band_points_compared=len(band_deltas),
        ideal_best_f_ghz=best_ideal,
        real_best_f_ghz=best_real,
        best_freq_offset_ghz=best_real - result.f0_ghz,
        slots=slots,
    )

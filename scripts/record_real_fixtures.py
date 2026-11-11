#!/usr/bin/env python3
"""VB-5 录制层契约化录制器（aurora_r R-16）：runs/ 既有真机证据 → 已清洗录制件 + manifest 契约。

职责与口径
----------
* 只从 runs/ 既有证据录制（**不新跑真机**）；每个工具一件（HFSS sNp /
  ADS 数据集 .ds / openEMS port_ut，openEMS 自动配对同端口 port_it），
  输出 ``tests/fixtures/recorded/<tool>/`` + ``manifest.json``。
* **录制即清洗**：盘符、用户目录（C:\\Users\\<name> 形态）、仓库根名、
  run-id、主机名（meta.json 实值 + DESKTOP-* 形态兜底）、用户名（meta.json
  实值）、IPv4 → 占位符（``<DRIVE>``/``<USERDIR>``/``<REPO>``/``<RUN>``/
  ``<HOST>``/``<USER>``/``<IP>``）。文本件逐模式替换；二进制件（.ds）按
  字节层同型替换 + ASCII 串提取复核。
* **判官 = 发布敏感扫描器**（RELEASE_GUIDE §5 口径）：本脚本运行期 import
  ``release/scan_release.py``，用其 FAIL/WARN 模式与 IPv4 分类器对每个
  待出件逐行/逐 ASCII 串复扫（扩展名缺失的 port_ut 类文件扫描器主入口
  不覆盖，本脚本显式补扫同口径）——**FAIL 或 WARN 非零即中止并删除已写
  文件（不净不出件）**。回放测试侧（tests/unit/test_recorded_fixtures.py）
  在日常门内独立复验同一口径，双证据。
* manifest 契约键（proposal 口径）：{tool, tool_version, recorded, recorder,
  restricted_data, source_run, files[{name, sha256_12, bytes}]}；另附
  cleaning 统计与 expectations（录制时判读链快照，回放断言=该快照）。
  schema 校验函数 :func:`validate_manifest` 供录制侧自检与回放测试负例钉
  （缺字段/坏 sha 拒）。
* source_run 占位化：run-id 形态目录名 → ``runs/<RUN>``；其余 runs/ 子路径
  保留相对形态（模板/目录名非敏感，精确溯源留在 gitignored 的 runs/ 湖）。

用法（仓根）::

    .venv/Scripts/python.exe scripts/record_real_fixtures.py \\
        --tool hfss --source runs/<run-dir>
    .venv/Scripts/python.exe scripts/record_real_fixtures.py \\
        --tool openems --source runs/<smoke-dir> --artifact fdtd/port_ut_1
    .venv/Scripts/python.exe scripts/record_real_fixtures.py \\
        --tool ads --source runs/<ads-dir>

manifest 期望键（expectations）逐工具：
* hfss   — n_ports / n_freqs / freq_hz_min / freq_hz_max / s11_db_min
  （经 ``rfauto.adapters.interchange.read_touchstone`` 判读链）。
* openems — n_samples / dt_s / freq_grid_hz / gamma_re_im（经
  ``rfauto.core.mapes.dft_time2freq`` + ``port_gamma`` 离线判读链，Γ 快照
  逐频 [re, im]）。
* ads    — kind / magic_form / byte_order_marker / format_version /
  n_variables / variable_names（项目自有 ads_ds 速览链快照，
  ``rfauto.service.format_overview_service.overview_format`` 单源）。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "recorded"
RECORDER_VERSION = "record_real_fixtures v1 (aurora_r R-16, VB-5)"
MANIFEST_SCHEMA = "aurora_r_recorded_fixtures_v1"

#: 二进制录制件后缀（字节层清洗 + ASCII 串复核；发布扫描器主入口只扫文本
#: 后缀集合，二进制件由本脚本的字节层同口径复扫兜底）。
BINARY_SUFFIXES = frozenset({".ds"})

#: manifest 必备键（proposal 验收口径）与逐文件必备键。
REQUIRED_MANIFEST_KEYS = (
    "tool", "tool_version", "recorded", "recorder", "restricted_data",
    "source_run", "files",
)
REQUIRED_FILE_KEYS = ("name", "sha256_12", "bytes")
KNOWN_TOOLS = ("hfss", "ads", "openems")

# ── 清洗模式（文本口径；字节口径同型转译）────────────────────────────────
# 顺序敏感：用户目录先于盘符根（更长模式优先），仓库根名、run-id、主机名、
# 用户名、IPv4 收尾。占位符按 proposal 命名。
_USERDIR_RE = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\s\"'\\/]+")
_DRIVE_RE = re.compile(r"\b[A-Za-z]:[\\/]+")
_RUNID_RE = re.compile(r"\b\d{8}_\d{6}_[0-9a-f]{8}\b")
_DESKTOP_RE = re.compile(r"\bDESKTOP-[A-Z0-9]{5,}\b", re.IGNORECASE)
_IPV4_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])")
_SHA12_RE = re.compile(r"[0-9a-f]{12}")

_PLACEHOLDER_USERDIR = "<USERDIR>"
_PLACEHOLDER_DRIVE = "<DRIVE>"
_PLACEHOLDER_REPO = "<REPO>"
_PLACEHOLDER_RUN = "<RUN>"
_PLACEHOLDER_HOST = "<HOST>"
_PLACEHOLDER_USER = "<USER>"
_PLACEHOLDER_IP = "<IP>"


class ManifestValidationError(ValueError):
    """manifest 契约校验失败（缺字段/坏 sha/文件不齐）。"""


# ── 发布敏感扫描器 import（判官）─────────────────────────────────────────
def load_scanner():
    """运行期 import release/scan_release.py（判官模块；test_scan_release 同法）。"""
    spec = importlib.util.spec_from_file_location(
        "rfauto_vb5_scan_judge", REPO_ROOT / "release" / "scan_release.py")
    if spec is None or spec.loader is None:  # pragma: no cover - 布局异常
        raise RuntimeError("release/scan_release.py 无法定位")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass 注解解析需要 sys.modules 登记
    spec.loader.exec_module(mod)
    return mod


# ── 清洗器（文本）────────────────────────────────────────────────────────
@dataclass
class CleanStats:
    """清洗替换计数（逐类累计；manifest cleaning 统计口径）。"""

    userdir: int = 0
    drive: int = 0
    repo: int = 0
    run_id: int = 0
    host: int = 0
    user: int = 0
    ip: int = 0

    def merged(self) -> dict[str, int]:
        return {
            "userdir": self.userdir, "drive": self.drive, "repo": self.repo,
            "run_id": self.run_id, "host": self.host, "user": self.user,
            "ip": self.ip,
        }

    def total(self) -> int:
        return sum(self.merged().values())


def _sub_ipv4_text(text: str, scanner) -> tuple[str, int]:
    """IPv4 → <IP>（判官口径：classify_ipv4 非 None 即替换，含私网/环回）。"""
    n = 0

    def _repl(m: re.Match[str]) -> str:
        nonlocal n
        if scanner.classify_ipv4(m.group(1)) is not None:
            n += 1
            return _PLACEHOLDER_IP
        return m.group(0)

    return _IPV4_RE.sub(_repl, text), n


def clean_text(
    text: str,
    *,
    hosts: tuple[str, ...] = (),
    users: tuple[str, ...] = (),
    repo_name: str,
    scanner,
) -> tuple[str, CleanStats]:
    """文本清洗：盘符/用户目录/仓库根/run-id/主机名/用户名/IPv4 → 占位符。

    hosts/users 来自来源 run 的 meta.json 实值（精确替换）+ DESKTOP-* 形态
    兜底；word-bounded，防止把数据数值误替换（数值字段不含这些形态）。
    """
    st = CleanStats()
    steps: list[tuple[re.Pattern[str], str, str]] = [
        (_USERDIR_RE, _PLACEHOLDER_USERDIR, "userdir"),
        (_DRIVE_RE, _PLACEHOLDER_DRIVE + "/", "drive"),
        (_RUNID_RE, _PLACEHOLDER_RUN, "run_id"),
        (_DESKTOP_RE, _PLACEHOLDER_HOST, "host"),
    ]
    # 仓库根名运行期推导（脚本面不得出现该字面量——公开仓扫描器 FAIL 模式）
    steps.append((re.compile(r"\b" + re.escape(repo_name) + r"\b"),
                  _PLACEHOLDER_REPO, "repo"))
    for host in hosts:
        if host:
            steps.append((
                re.compile(r"(?<![\w.-])" + re.escape(host) + r"(?![\w.-])",
                           re.IGNORECASE),
                _PLACEHOLDER_HOST, "host"))
    for user in users:
        if user:
            steps.append((
                re.compile(r"(?<![\w.-])" + re.escape(user) + r"(?![\w.-])"),
                _PLACEHOLDER_USER, "user"))
    for pat, repl, key in steps:
        text, n = pat.subn(repl, text)
        setattr(st, key, getattr(st, key) + n)
    text, n_ip = _sub_ipv4_text(text, scanner)
    st.ip += n_ip
    return text, st


# ── 清洗器（字节，二进制件用）────────────────────────────────────────────
def clean_bytes(
    data: bytes,
    *,
    hosts: tuple[str, ...] = (),
    users: tuple[str, ...] = (),
    repo_name: str,
    scanner,
) -> tuple[bytes, CleanStats]:
    """二进制清洗：同型字节模式替换 + IPv4（ASCII 边界同口径）。保守替换：
    仅替换 ASCII 可编码的字面模式；数值二进制不含这些形态（.ds 数据节为
    定长浮点，变量名节为短标识符）。"""
    st = CleanStats()
    userdir_b = re.compile(rb"[A-Za-z]:[\\/]+Users[\\/]+[^\s\"'\\/]+")
    drive_b = re.compile(rb"\b[A-Za-z]:[\\/]+")
    runid_b = re.compile(rb"\b\d{8}_\d{6}_[0-9a-f]{8}\b")
    desktop_b = re.compile(rb"\bDESKTOP-[A-Z0-9]{5,}\b", re.IGNORECASE)
    repo_b = re.compile(rb"\b" + re.escape(repo_name.encode("utf-8")) + rb"\b")

    def _sub(pat: re.Pattern[bytes], repl: bytes, key: str) -> bytes:
        nonlocal data
        data, n = pat.subn(repl, data)
        setattr(st, key, getattr(st, key) + n)
        return data

    data = _sub(userdir_b, _PLACEHOLDER_USERDIR.encode(), "userdir")
    data = _sub(drive_b, (_PLACEHOLDER_DRIVE + "/").encode(), "drive")
    data = _sub(repo_b, _PLACEHOLDER_REPO.encode(), "repo")
    data = _sub(runid_b, _PLACEHOLDER_RUN.encode(), "run_id")
    data = _sub(desktop_b, _PLACEHOLDER_HOST.encode(), "host")
    for host in hosts:
        if not host:
            continue
        data = _sub(
            re.compile(rb"(?<![A-Za-z0-9._-])" + re.escape(host.encode()) +
                       rb"(?![A-Za-z0-9._-])", re.IGNORECASE),
            _PLACEHOLDER_HOST.encode(), "host")
    for user in users:
        if not user:
            continue
        data = _sub(
            re.compile(rb"(?<![A-Za-z0-9._-])" + re.escape(user.encode()) +
                       rb"(?![A-Za-z0-9._-])"),
            _PLACEHOLDER_USER.encode(), "user")
    # IPv4（字节层）：ASCII 边界同口径，classify 判官同源
    ipv4_b = re.compile(rb"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])")
    n_ip = 0

    def _repl(m: re.Match[bytes]) -> bytes:
        nonlocal n_ip
        if scanner.classify_ipv4(m.group(1).decode("ascii")) is not None:
            n_ip += 1
            return _PLACEHOLDER_IP.encode()
        return m.group(0)

    data = ipv4_b.sub(_repl, data)
    st.ip += n_ip
    return data, st


# ── 判官复扫（待出件目录；扫描器主入口 + 无后缀/二进制兜底）──────────────
_ASCII_RUN_RE = re.compile(rb"[\x20-\x7e]{6,}")


def verify_recorded_dir(out_dir: Path, scanner) -> list[str]:
    """以发布扫描器口径复扫录制目录；返回违例串列表（空=clean）。

    文本件逐行 scanner.scan_line（含 WARN）；二进制件提取 ASCII 串逐串
    scan_line；无后缀文本件（port_ut 类）同文本路径——扫描器主入口
    TEXT_SUFFIXES 不含无后缀文件，此处显式补扫（判官口径一致）。
    """
    assets = scanner.load_known_assets(REPO_ROOT)
    asset_pattern = scanner.compile_asset_pattern(assets)
    violations: list[str] = []
    for p in sorted(out_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(out_dir).as_posix()
        if p.suffix.lower() in BINARY_SUFFIXES:
            data = p.read_bytes()
            runs = _ASCII_RUN_RE.findall(data)
            for run in runs:
                for h in scanner.scan_line(run.decode("latin-1"), 0,
                                           asset_pattern):
                    violations.append(f"{rel}: [{h.label}] {h.value!r}")
        else:
            try:
                text = p.read_text(encoding="utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                violations.append(f"{rel}: not utf-8 text ({exc})")
                continue
            if "\uFFFD" in text:
                violations.append(f"{rel}: mojibake U+FFFD present")
            for lineno, line in enumerate(text.splitlines(), 1):
                for h in scanner.scan_line(line, lineno, asset_pattern):
                    violations.append(f"{rel}:{lineno}: [{h.label}] {h.value!r}")
    return violations


# ── manifest 契约校验（录制侧自检 + 回放测试负例钉共用）──────────────────
def validate_manifest(manifest: dict, fixture_dir: Path) -> None:
    """manifest 契约校验：缺字段/坏 sha/文件缺失即抛 :class:`ManifestValidationError`。

    files 每条 {name, sha256_12, bytes} 必须与 fixture_dir 下实际文件逐项
    对上（sha256 前 12 位 hex + 字节数）。
    """
    if not isinstance(manifest, dict):
        raise ManifestValidationError("manifest 必须是 dict")
    for key in REQUIRED_MANIFEST_KEYS:
        if key not in manifest:
            raise ManifestValidationError(f"缺必备字段: {key}")
    if manifest["tool"] not in KNOWN_TOOLS:
        raise ManifestValidationError(f"tool 非法: {manifest['tool']!r}")
    if not isinstance(manifest["recorded"], str) or not _is_date(manifest["recorded"]):
        raise ManifestValidationError(f"recorded 必须是 ISO 日期: {manifest['recorded']!r}")
    rd = manifest["restricted_data"]
    if rd is not None and not isinstance(rd, str):
        raise ManifestValidationError("restricted_data 必须是 null 或字符串标注")
    if not isinstance(manifest["source_run"], str) or not manifest["source_run"]:
        raise ManifestValidationError("source_run 必须是非空字符串（占位化）")
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise ManifestValidationError("files 必须是非空列表")
    for entry in files:
        if not isinstance(entry, dict):
            raise ManifestValidationError("files 条目必须是 dict")
        for key in REQUIRED_FILE_KEYS:
            if key not in entry:
                raise ManifestValidationError(f"files 条目缺字段: {key}")
        name = entry["name"]
        p = fixture_dir / name
        if not p.is_file():
            raise ManifestValidationError(f"录制件不存在: {name}")
        sha12 = entry["sha256_12"]
        if not isinstance(sha12, str) or not _SHA12_RE.fullmatch(sha12):
            raise ManifestValidationError(f"sha256_12 必须是 12 位小写 hex: {name}")
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if not actual.startswith(sha12):
            raise ManifestValidationError(
                f"sha256_12 与实际文件不符: {name}（manifest {sha12} vs {actual[:12]}）")
        if entry["bytes"] != p.stat().st_size:
            raise ManifestValidationError(
                f"bytes 与实际文件不符: {name}（manifest {entry['bytes']} vs "
                f"{p.stat().st_size}）")


def _is_date(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


# ── 工具规格与发现 ───────────────────────────────────────────────────────
@dataclass(frozen=True)
class ToolSpec:
    """录制规格：发现模式、配对件、版本提取。"""

    tool: str
    discover: str  # runs 子树内的 glob（rglob 语义）
    pair_prefix: str | None = None  # openems：port_ut_X ↔ port_it_X 配对
    source_hint: str = ""


TOOLS: dict[str, ToolSpec] = {
    "hfss": ToolSpec("hfss", "**/*.s?p"),
    "ads": ToolSpec("ads", "**/*.ds"),
    "openems": ToolSpec("openems", "**/port_ut_*", pair_prefix="port_it_"),
}

_SNP_SUFFIX_RE = re.compile(r"\.s\d+p$", re.IGNORECASE)


def discover_artifacts(source: Path, spec: ToolSpec) -> list[Path]:
    """按工具默认规则发现录制对象（确定性排序；hfss 优先 results/ 下的 sNp）。"""
    if spec.tool == "hfss":
        cands = [p for p in sorted(source.rglob("*"))
                 if p.is_file() and _SNP_SUFFIX_RE.search(p.name)]
        results_first = [p for p in cands if "results" in p.parts]
        picked = (results_first or cands)[:1]
        if not picked:
            raise SystemExit(f"hfss 来源未发现 sNp 件: {source}")
        return picked
    if spec.tool == "ads":
        picked = sorted(source.rglob("*.ds"))[:1]
        if not picked:
            raise SystemExit(f"ads 来源未发现 .ds 数据集: {source}")
        return picked
    # openems：首个 port_ut（排序确定）+ 同目录同端口号 port_it 配对
    uts = sorted(source.rglob(spec.discover))
    if not uts:
        raise SystemExit(f"openems 来源未发现 port_ut 件: {source}")
    picked = [uts[0]]
    if spec.pair_prefix:
        it = uts[0].with_name(spec.pair_prefix + uts[0].name[len("port_ut_"):])
        if it.is_file():
            picked.append(it)
    return picked


# ── 来源元数据（主机名/用户名实值——清洗替换源）──────────────────────────
def load_identity(source: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    meta = source / "meta.json"
    if not meta.is_file():
        return (), ()
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (), ()
    host = data.get("hostname") or data.get("host") or ""
    user = data.get("user") or ""
    return ((host,) if isinstance(host, str) and host else (),
            (user,) if isinstance(user, str) and user else ())


def placeholder_source_run(source: Path) -> str:
    """source_run 占位化：run-id 形态 → runs/<RUN>；其余保留 runs/ 相对形态。"""
    try:
        rel = source.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return "<SRC>"
    if _RUNID_RE.fullmatch(source.name):
        return "runs/<RUN>"
    return rel if rel.startswith("runs/") else f"<SRC>/{rel}"


# ── 逐工具期望（录制时判读链快照）────────────────────────────────────────
def expectations_hfss(path: Path) -> dict:
    import numpy as np

    from rfauto.adapters.interchange import read_touchstone

    net = read_touchstone(path)
    f = net.f
    s11_db = 20.0 * np.log10(np.abs(net.s[:, 0, 0]))
    return {
        "n_ports": int(net.s.shape[1]),
        "n_freqs": int(f.shape[0]),
        "freq_hz_min": float(f.min()),
        "freq_hz_max": float(f.max()),
        "s11_db_min": float(s11_db.min()),
    }


#: openEMS Γ 快照判读频栅（确定值；录制与回放共用同一栅）。
OPENEMS_FREQ_GRID_HZ = [0.5e9 + 0.5e9 * k for k in range(12)]


def _parse_port_file(path: Path) -> tuple:
    """解析 openEMS port_ut/port_it 文本件 → (t, v)（严格两列，% 注释跳过）。"""
    import numpy as np

    rows: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("%") or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) != 2:
            raise SystemExit(f"{path.name}: 期望两列数据行，实得 {len(parts)} 列")
        rows.append((float(parts[0]), float(parts[1])))
    if len(rows) < 2:
        raise SystemExit(f"{path.name}: 数据行不足（{len(rows)}）")
    arr = np.asarray(rows, dtype=float)
    return arr[:, 0], arr[:, 1]


def expectations_openems(files: list[Path]) -> dict:
    """port_ut+port_it → dft_time2freq + port_gamma 判读链快照。

    u/i 两个时域文件按各自时间栅独立 DFT（mapes.dft_time2freq 本就按
    (t, val) 逐点求值，非均匀栅合法）——真机数据里 E/H 探针的落盘时间栅
    可有亚步长错位（本例 ~0.0035·dt，Yee 交错+落盘舍入），硬性等栅断言
    会把真机证据拒之门外；dt 相对差 >1% 才判配对失败。
    """
    import numpy as np

    from rfauto.core.mapes import dft_time2freq, port_gamma

    u_path = next(p for p in files if p.name.startswith("port_ut"))
    i_path = next(
        (p for p in files if p.name.startswith("port_it")), None)
    t_u, u = _parse_port_file(u_path)
    freqs = np.asarray(OPENEMS_FREQ_GRID_HZ, dtype=float)
    exp: dict = {
        "n_samples": int(t_u.shape[0]),
        "dt_s": float(t_u[1] - t_u[0]),
        "freq_grid_hz": [float(v) for v in freqs],
    }
    if i_path is None:
        exp["gamma_re_im"] = None
        exp["note"] = "无配对 port_it，仅 u 链快照"
        return exp
    t_i, i = _parse_port_file(i_path)
    dt_u = float(t_u[1] - t_u[0])
    dt_i = float(t_i[1] - t_i[0])
    if abs(dt_i - dt_u) > 0.01 * dt_u or t_i.shape != t_u.shape:
        raise SystemExit(
            f"port_it 与 port_ut 采样形态不一致：dt {dt_i} vs {dt_u}，"
            f"n {t_i.shape[0]} vs {t_u.shape[0]}")
    exp["dt_i_s"] = dt_i
    exp["time_grid_identical"] = bool(np.array_equal(t_i, t_u))
    uf = dft_time2freq(t_u, u, freqs)
    if_ = dft_time2freq(t_i, i, freqs)
    gamma = port_gamma(uf, if_)
    exp["gamma_re_im"] = [[float(v.real), float(v.imag)] for v in gamma]
    return exp


def expectations_ads(path: Path) -> dict:
    """ADS .ds → 项目自有 ads_ds 速览链快照（format_overview_service 单源，
    STRINGDATA 变量名面 stdlib 可解口径；数值块专有布局未解=如实不承诺）。

    另附字节层数据面描述符名（``data_variable_names``）：S[i,j]/PortZ[i] 等
    变量描述符不在 STRINGDATA 头部面（实测本件），以 ASCII 边界正则独立
    提取作数据面存在性证据（判读内容层，非专有布局解析）。
    """
    from rfauto.service.format_overview_service import overview_format

    env = overview_format(path)
    if not env.get("ok"):
        raise SystemExit(f"ads 数据集速览失败: {env.get('error')}")
    if env.get("kind") != "ads_ds":
        raise SystemExit(f"ads 数据集 kind 非 ads_ds: {env.get('kind')!r}")
    stats = env["stats"]
    data = path.read_bytes()
    data_vars = sorted({
        m.group(0).decode("ascii")
        for m in re.finditer(
            rb"(?<![\w.\[])[A-Za-z_][A-Za-z0-9_]{0,40}\[\d+(?:,\d+)?\](?![\w.\]])",
            data)
    })
    return {
        "kind": env["kind"],
        "magic_form": stats["magic_form"],
        "byte_order_marker": stats["byte_order_marker"],
        "format_version": stats["format_version"],
        "n_variables": stats["n_variables"],
        "variable_names": env["entities"]["variable_names"],
        "data_variable_names": data_vars,
    }


# ── 工具版本（从录制件/来源证据提取，不臆造）────────────────────────────
def tool_version(tool: str, source: Path, files: list[Path]) -> tuple[str, str]:
    """返回 (tool_version, 版本来源说明)。"""
    if tool == "hfss":
        head = files[0].read_text(encoding="utf-8", errors="replace")[:400]
        m = re.search(r"exported from HFSS ([0-9.]+)", head)
        if m:
            return m.group(1), "sNp 头注 '! Touchstone file exported from HFSS <ver>'"
        meta = source / "meta.json"
        if meta.is_file():
            data = json.loads(meta.read_text(encoding="utf-8"))
            v = data.get("aedt_version")
            if v:
                return str(v), "来源 run meta.json aedt_version"
        return "unknown", "无版本证据"
    if tool == "ads":
        for log in sorted(source.rglob("logFile.txt")):
            head = log.read_text(encoding="utf-8", errors="replace")[:400]
            m = re.search(r"hpeesofsim \(\*\) (\S+)", head)
            if m:
                return m.group(1), "来源 run hpeesofsim 日志横幅（logFile.txt）"
        return "unknown", "无版本证据"
    head = files[0].read_text(encoding="utf-8", errors="replace")[:200]
    m = re.search(r"openEMS (v\S+)", head)
    if m:
        return m.group(1), "port_ut 头注 'openEMS <ver>'"
    return "unknown", "无版本证据"


# ── 主流程 ───────────────────────────────────────────────────────────────
@dataclass
class RecordOutcome:
    tool: str
    out_dir: Path
    manifest: dict = field(default_factory=dict)


def record(
    tool: str,
    source: Path,
    out_root: Path,
    *,
    artifacts: list[str] | None = None,
    recorded_date: str | None = None,
) -> RecordOutcome:
    """录制单工具：发现→清洗→判官复扫→期望快照→manifest（不净不出件）。"""
    scanner = load_scanner()
    spec = TOOLS[tool]
    if not source.is_dir():
        raise SystemExit(f"来源目录不存在: {source}")
    files = ([source / a for a in artifacts] if artifacts
             else discover_artifacts(source, spec))
    for f in files:
        if not f.is_file():
            raise SystemExit(f"指定录制对象不存在: {f}")
    hosts, users = load_identity(source)
    out_dir = out_root / tool
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    entries: list[dict] = []
    stats_total = CleanStats()
    try:
        for f in files:
            raw = f.read_bytes()
            if f.suffix.lower() in BINARY_SUFFIXES:
                cleaned, st = clean_bytes(
                    raw, hosts=hosts, users=users,
                    repo_name=REPO_ROOT.name, scanner=scanner)
                (out_dir / f.name).write_bytes(cleaned)
            else:
                cleaned, st = clean_text(
                    raw.decode("utf-8"), hosts=hosts, users=users,
                    repo_name=REPO_ROOT.name, scanner=scanner)
                (out_dir / f.name).write_text(cleaned, encoding="utf-8",
                                              newline="\n")
            for k, v in st.merged().items():
                setattr(stats_total, k, getattr(stats_total, k) + v)
            written.append(out_dir / f.name)
            digest = hashlib.sha256((out_dir / f.name).read_bytes()).hexdigest()
            entries.append({
                "name": f.name,
                "sha256_12": digest[:12],
                "bytes": (out_dir / f.name).stat().st_size,
            })
        violations = verify_recorded_dir(out_dir, scanner)
        if violations:
            raise SystemExit(
                "判官复扫非 clean（不净不出件），已回滚本次写入：\n  "
                + "\n  ".join(violations[:20]))
        if tool == "hfss":
            exp = expectations_hfss(written[0])
        elif tool == "ads":
            exp = expectations_ads(written[0])
        else:
            exp = expectations_openems(written)
        version, version_src = tool_version(tool, source, files)
        manifest = {
            "schema_version": MANIFEST_SCHEMA,
            "tool": tool,
            "tool_version": version,
            "tool_version_source": version_src,
            "recorded": recorded_date or date.today().isoformat(),
            "recorder": RECORDER_VERSION,
            "restricted_data": None,
            "source_run": placeholder_source_run(source),
            "cleaning": {
                "replacements": stats_total.merged(),
                "total": stats_total.total(),
                "judge": "release/scan_release.py FAIL+WARN 双零口径",
            },
            "expectations": exp,
            "files": entries,
        }
        validate_manifest(manifest, out_dir)
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    except BaseException:
        for p in written:
            p.unlink(missing_ok=True)  # 失败即回滚，不留半成品
        raise
    return RecordOutcome(tool=tool, out_dir=out_dir, manifest=manifest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="VB-5 真机证据录制器（录制即清洗）")
    ap.add_argument("--tool", required=True, choices=sorted(TOOLS))
    ap.add_argument("--source", required=True, help="runs/ 下来源 run 目录")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="录制输出根")
    ap.add_argument("--artifact", nargs="*", default=None,
                    help="显式指定录制对象（相对 source；缺省按工具自动发现）")
    ap.add_argument("--recorded-date", default=None,
                    help="manifest recorded 日期（缺省今天；复现录制用）")
    args = ap.parse_args(argv)
    outcome = record(
        args.tool, Path(args.source), Path(args.out),
        artifacts=args.artifact, recorded_date=args.recorded_date)
    m = outcome.manifest
    print(f"OK {outcome.out_dir / 'manifest.json'}")
    print(f"  tool={m['tool']} version={m['tool_version']} "
          f"source_run={m['source_run']}")
    print(f"  cleaning replacements total={m['cleaning']['total']} "
          f"{m['cleaning']['replacements']}")
    print("  files: " + ", ".join(
        f"{e['name']}({e['bytes']}B sha12={e['sha256_12']})" for e in m["files"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

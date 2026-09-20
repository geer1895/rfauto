"""C15 厂商被动元件模型下载器（SimSurfing/Coilcraft 等按条款获取，模型不入 git）。

网络只在本脚本（service/core 保持零网络，单测 monkeypatch 钉住 #139）：
  urllib.request 拉取 → knowledge/vendor_passives/ 落盘 → sha256 →
  --register 经 service.register_model_entry 追加 catalog 条目（索引+哈希+
  来源 URL+条款备注入库；模型文件本身被 .gitignore 目录级兜底忽略）。

用法示例：
  python scripts/vendor_passive_download.py \
      --url "https://www.coilcraft.com/models/.../0402DC-1N8.s2p" \
      --part-id coilcraft_0402dc_1n8 --vendor coilcraft --mpn 0402DC-1N8 \
      --type inductor --nominal-value 1.8e-9 \
      --source-page "https://www.coilcraft.com/en-us/models/spice/" \
      --license-note "Coilcraft 免费下载用于设计；禁止再分发模型文件" \
      --register

官方出处：Murata SimSurfing https://www.murata.com/en-us/tool/simsurfing
          Coilcraft SPICE https://www.coilcraft.com/en-us/models/spice/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, "src")

from rfauto.service.vendor_passives_service import register_model_entry

USER_AGENT = "rfauto-vendor-passives/0.1 (design-tooling; respects vendor terms)"
DEFAULT_CATALOG = "knowledge/vendor_passives/catalog.yaml"
DEFAULT_DEST = "knowledge/vendor_passives"
_FALLBACK_FILENAME = "model.s2p"
_ALLOWED_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def sanitize_filename(name: str) -> str:
    """URL 片段 → 安全文件名（白名单字符，其余折成 '_'）。"""
    cleaned = "".join(ch if ch in _ALLOWED_NAME_CHARS else "_" for ch in name.strip())
    return cleaned or _FALLBACK_FILENAME


def filename_from_url(url: str, fallback: str = _FALLBACK_FILENAME) -> str:
    """取 URL 路径末段做文件名（query 丢弃、percent-decode、sanitize）。

    路径以 / 结尾（目录式 URL）→ 无文件名语义，回退默认名。
    """
    path = unquote(urlparse(url).path)
    if path.endswith("/"):
        return fallback
    tail = path.rsplit("/", 1)[-1]
    if not tail or tail in (".", ".."):
        return fallback
    return sanitize_filename(tail)


def fetch_bytes(url: str, timeout_s: float = 60.0) -> bytes:
    """下载 URL 字节流（显式 UA；网络只存在于本函数）。"""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout_s) as response:
        return response.read()


def download_model(
    url: str,
    dest_dir: str | Path,
    filename: str | None = None,
    timeout_s: float = 60.0,
) -> tuple[Path, str, bytes]:
    """下载 → 落盘 → 返回 (路径, sha256, 字节)。不触 catalog。"""
    name = sanitize_filename(filename) if filename else filename_from_url(url)
    payload = fetch_bytes(url, timeout_s=timeout_s)
    out = Path(dest_dir) / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    import hashlib

    return out, hashlib.sha256(payload).hexdigest(), payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="厂商被动元件模型下载器（模型不入 git）")
    parser.add_argument("--url", required=True, help="模型文件下载 URL")
    parser.add_argument("--dest", default=DEFAULT_DEST, help="落盘目录（默认 knowledge/vendor_passives）")
    parser.add_argument("--filename", default=None, help="覆盖文件名（默认取 URL 末段）")
    parser.add_argument("--timeout", type=float, default=60.0, help="下载超时秒数")
    parser.add_argument("--register", action="store_true", help="登记进 catalog（需元件元数据齐备）")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG, help="catalog 路径")
    parser.add_argument("--part-id", default=None, help="registry ID（--register 必填）")
    parser.add_argument("--vendor", default=None, help="厂商（--register 必填）")
    parser.add_argument("--mpn", default=None, help="料号（--register 必填）")
    parser.add_argument("--type", default=None, choices=["inductor", "capacitor"], help="元件类型")
    parser.add_argument("--nominal-value", type=float, default=None, help="标称值（SI：H 或 F）")
    parser.add_argument("--srf-ghz", type=float, default=None, help="datasheet 自谐振频率 (GHz)")
    parser.add_argument("--esr-ohm", type=float, default=None, help="ESR (ohm)")
    parser.add_argument("--source-page", default="", help="来源页面（区别于模型直链）")
    parser.add_argument("--license-note", default="", help="厂商条款备注（--register 强烈建议必填）")
    parser.add_argument("--replace", action="store_true", help="同 ID 已存在时覆盖")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path, sha, payload = download_model(args.url, args.dest, filename=args.filename, timeout_s=args.timeout)
    print(f"downloaded: {path} ({len(payload)} bytes) sha256={sha}")
    if not args.register:
        return 0
    missing = [
        flag for flag, value in (
            ("--part-id", args.part_id), ("--vendor", args.vendor), ("--mpn", args.mpn),
            ("--type", args.type),
            ("--nominal-value", args.nominal_value),
        ) if value is None
    ]
    if missing:
        print(f"--register 需要元件元数据，缺: {missing}", file=sys.stderr)
        return 2
    if not args.license_note:
        print("--register 需要 --license-note（厂商条款纪律：留痕才登记）", file=sys.stderr)
        return 2
    result = register_model_entry(
        catalog_path=args.catalog,
        part_id=args.part_id,
        vendor=args.vendor,
        mpn=args.mpn,
        part_type=args.type,
        nominal_value=args.nominal_value,
        model_file=path.name,
        sha256=sha,
        srf_ghz=args.srf_ghz,
        esr_ohm=args.esr_ohm,
        source_url=args.source_page or args.url,
        license_note=args.license_note,
        synthetic=False,
        downloaded_at=None,
        replace=args.replace,
    )
    print(f"registered: {result['registered']['part_id']} -> {result['catalog']} "
          f"(n_parts={result['n_parts']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

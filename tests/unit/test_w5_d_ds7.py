"""W5-D 件 3 DS-7 测试：dsh（deepseek-harness）挂 rfauto MCP server 配置面。

判据（宏图 v3.2 §十 DS-7 行 + W5-D criteria）：产配置模板（cordis 补丁
形态+JSON schema 形态）+互通对拍记录（runs/w5_phase5/w5d/interop_report.md）；
不引 TS 依赖、不装 dsh（零网络）；适用版本在模板头预声明（快照日期+
锁模式不锁版本，宏图 §10.2 裁决③）。字段面锚=packages/mcp/mcp-client
配置目录（serverName/transport/command/args/cwd/env + url/headers）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO_ROOT / "configs" / "dsh" / "rfauto_mcp_server.cordis.yml"
_SCHEMA = _REPO_ROOT / "configs" / "dsh" / "rfauto_mcp_client_config.schema.json"

# dsh mcp-client 配置键面（快照 2026-10-05，packages/mcp/mcp-client 配置目录）
_GROUNDED_KEYS = {
    "serverName",
    "transport",
    "command",
    "args",
    "cwd",
    "env",
    "url",
    "headers",
    "reconnect",
}
_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _load_template_config() -> dict:
    raw = yaml.safe_load(_TEMPLATE.read_text(encoding="utf-8"))
    assert isinstance(raw, list) and raw, "cordis 补丁顶层须为 insert 行列表"
    entry = raw[0]["insert"][0]
    assert entry["id"] == "mcp-rfauto"
    assert entry["name"] == "@deepseek-ai/dsh-mcp-client"
    return entry["config"]


def test_template_parses_as_cordis_insert_patch() -> None:
    raw = yaml.safe_load(_TEMPLATE.read_text(encoding="utf-8"))
    assert isinstance(raw, list) and "insert" in raw[0]
    config = _load_template_config()
    assert config["serverName"] == "rfauto"


def test_config_keys_within_grounded_surface() -> None:
    config = _load_template_config()
    unknown = set(config) - _GROUNDED_KEYS
    assert not unknown, f"键面漂移（快照外键）: {unknown}"


def test_config_required_keys_and_values() -> None:
    config = _load_template_config()
    for key in ("serverName", "transport", "command", "args"):
        assert key in config, key
    assert _SERVER_NAME_RE.match(config["serverName"])
    assert config["transport"] == "stdio"
    # 零 TS 依赖：python -m 同源入口（console script exe 未重装可能缺位，#278）
    assert config["args"] == ["-m", "rfauto.mcp_server"]
    assert "node" not in str(config["command"]).lower()
    assert str(config["command"]).replace("/", "\\").endswith(".venv\\Scripts\\python.exe")


def test_config_cwd_is_repo_root() -> None:
    config = _load_template_config()
    # 占位符化（审查 P2-3/铁律 8）：模板路径用 {{REPO_ROOT}}，部署时替换；
    # 本仓自用态（替换后）应与仓根一致。
    cwd = config["cwd"]
    assert cwd == "{{REPO_ROOT}}" or Path(cwd).resolve() == _REPO_ROOT.resolve()


def test_template_carries_version_preadeclaration() -> None:
    text = _TEMPLATE.read_text(encoding="utf-8")
    assert "2026-10-05" in text  # 快照日期（citation-rot 防御）
    assert "锁模式不锁版本" in text  # 预览期 breaking changes 裁决口径
    assert "@deepseek-ai/dsh-mcp-client" in text


def test_schema_json_validates_example() -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"serverName", "transport", "command", "args"}
    # schema 键面与 grounded 集一致（双检：模板面 vs schema 面）
    assert set(schema["properties"]) <= _GROUNDED_KEYS
    pattern = schema["properties"]["serverName"]["pattern"]
    assert re.compile(pattern)  # 合法正则
    assert re.compile(pattern).match("rfauto")
    assert not re.compile(pattern).match("非法 名字!")

    # 最小校验器（不引 jsonschema 依赖）：required+pattern+enum+键封闭
    example = schema["examples"][0]
    missing = set(schema["required"]) - set(example)
    assert not missing
    assert re.compile(pattern).match(example["serverName"])
    assert example["transport"] in schema["properties"]["transport"]["enum"]
    extra = set(example) - set(schema["properties"])
    assert not extra


def test_schema_declares_version_and_no_ts_runtime() -> None:
    text = _SCHEMA.read_text(encoding="utf-8")
    assert "2026-10-05" in text
    assert "python -m rfauto.mcp_server" in text
    assert "npm" not in text and "pnpm" not in text

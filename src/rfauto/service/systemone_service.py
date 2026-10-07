"""systemone_service：System One（Jev 类）typed-question 决策通道（W1-G，2026-10-05）。

Jev 本体专有不可引入（无开源权重）；本模块引入的是**范式通道**：
typed-question（choice/score）→ typed-answer（枚举选择/排序索引），
provider 可插拔，**缺省确定性零网络**。调研账=
研究扩充_jev_systemone.md。

工程护栏（逐条对照项目硬规则）：
- **铁律 7（数值只在确定性内核）**：通道输出只允许枚举选择/排序索引/
  偏好分序；float 仅允许两处元数据——choice 的 ``confidence``（校准概率
  元数据，[0,1]）与 score 的 ``scores``（序偏好分，仅定序消费）——答案
  schema **白名单强制**（pydantic extra=forbid + 物理语义键名负筛），
  任何物理语义字段（freq/power/loss/几何量等样态键）构造即 ValidationError；
- **#139（配置存在则走外部服务）**：``openai_compatible``（复用既有 chat
  通道配置 configs/chat_settings.yaml 的 base_url/model/api_key）与
  ``typesafe_jev``（官方端点形态 POST {base}/v1/systemone，model=jev-latest）
  均"配置存在才启用"——配置缺失时**注册但在册 health=unavailable**，
  ask() 显式抛 ProviderUnavailableError，**绝不隐式回退读网**；测试全部
  monkeypatch 钉住传输面，缺省态零网络；
- **#105（观测/增强面 best-effort）**：``ask_systemone`` 门面捕获 provider
  任何异常 → 走确定性兜底并附 ``degraded=True``+``degrade_reason``——
  决策通道永不阻塞主路径；
- **规则 3（基类+注册表）**：SystemOneProvider 基类 + SystemOneRegistry
  （照 EMSolverRegistry 惯例），三内置 provider 注册即用，可替换组件走
  ``get_systemone_registry().register``；
- **规则 8（上传零敏感）精神外发面**：``sanitize_outbound`` 在一切外发
  渲染点强制调用——盘符绝对路径/私有 IP/主机名:端口/凭据样态字符串
  剥离为占位符，redactions 留痕**只记规则名与命中次数、不记命中原文**
  （审计日志本身不得成为泄漏面）。

分层：本模块=service 层新件（规则 4），CLI/MCP 本批零接线（Phase 5
DS-1 工具瀑布落地时再接 rank 挂点，见调研账 §三）。
"""

from __future__ import annotations

import json
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "DeterministicProvider",
    "OpenAICompatibleProvider",
    "ProviderUnavailableError",
    "SystemOneAnswer",
    "SystemOneProvider",
    "SystemOneProviderError",
    "SystemOneQuestion",
    "SystemOneRegistry",
    "TypesafeJevProvider",
    "ask_systemone",
    "get_systemone_registry",
    "hint_question_for_message",
    "resolve_systemone_provider",
    "sanitize_outbound",
    "systemone_status",
    "validate_answer_against_question",
]

_SOURCE = "rfauto.service.systemone_service"

# ─── typed-question / typed-answer schema（铁律 7 白名单单源） ────────────────


class SystemOneQuestion(BaseModel):
    """typed-question：choice（枚举选择）/ score（排序）两种问题原语。

    - choice：``options`` ≥2 个互斥候选（answer=选中索引或选项原文）；
    - score：``items`` 非空待排序项（answer=索引置换 ranking）；
    - ``context``：调用方元数据（task 标记/计数等）；**外部 provider 外发前
      会整体 sanitize**，但调用方不该把敏感面放进来（纵深防御非洗白通道）。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["choice", "score"]
    question: str = Field(min_length=1)
    options: list[str] | None = None
    items: list[Any] | None = None
    context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_kind_payload(self) -> SystemOneQuestion:
        if self.kind == "choice":
            if not self.options or len(self.options) < 2:
                raise ValueError("choice 问题要求 options ≥2 个互斥候选")
        elif not self.items:
            raise ValueError("score 问题要求 items 非空")
        return self


#: 答案 schema 键白名单（铁律 7）：除此以外的一切键构造即 ValidationError
_ANSWER_KEYS_WHITELIST = frozenset(
    {"kind", "selected", "confidence", "ranking", "scores"})

#: 物理语义键名负筛标记（白名单外键命中这些样态时报铁律 7 专项错；
#: 只对白名单外键生效——白名单键集本身不含任何标记子串，已核对）
_PHYSICAL_KEY_MARKERS = (
    "freq", "ghz", "mhz", "khz", "hz", "db", "power", "loss", "gain",
    "s11", "s21", "s31", "s_param", "sparam", "resist", "imped", "capac",
    "induc", "volt", "current", "watt", "ohm", "physical", "numeric",
    "value", "mesh", "threshold", "temp", "length", "width", "thickness",
    "cost", "metric", "tol_", "q_factor",
)


def _looks_physical(key: str) -> bool:
    low = key.lower()
    return any(marker in low for marker in _PHYSICAL_KEY_MARKERS)


class SystemOneAnswer(BaseModel):
    """typed-answer 白名单 schema（铁律 7 schema 强制）。

    - choice：``selected``（索引 int 或选项原文 str）+ 可选 ``confidence``
      （校准概率元数据，[0,1]）；score 字段禁带；
    - score：``ranking``（索引置换）+ 可选 ``scores``（与 ranking 等长对齐的
      序偏好分——**仅定序消费的偏好元数据，非物理量语义**）；choice 字段禁带；
    - 白名单外键（含 physical/numeric 数值载荷样态键）→ ValidationError
      （extra=forbid + before-validator 物理键名负筛双保险）。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["choice", "score"]
    selected: int | str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ranking: list[int] | None = None
    scores: list[float | None] | None = None

    @model_validator(mode="before")
    @classmethod
    def _enforce_whitelist(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        unknown = {str(k) for k in data} - _ANSWER_KEYS_WHITELIST
        if unknown:
            physical = sorted(k for k in unknown if _looks_physical(k))
            if physical:
                raise ValueError(
                    f"铁律 7 违约：答案禁止物理语义字段 {physical}"
                    f"（通道输出只允许枚举选择/排序索引；float 仅限"
                    f" confidence/scores 元数据；白名单={sorted(_ANSWER_KEYS_WHITELIST)}）")
            raise ValueError(
                f"答案 schema 白名单违约：非法键 {sorted(unknown)}"
                f"（白名单={sorted(_ANSWER_KEYS_WHITELIST)}）")
        return data

    @model_validator(mode="after")
    def _check_kind_fields(self) -> SystemOneAnswer:
        if self.kind == "choice":
            if self.selected is None:
                raise ValueError("choice 答案必须给 selected（索引或选项原文）")
            if isinstance(self.selected, int) and not isinstance(self.selected, bool) \
                    and self.selected < 0:
                raise ValueError("choice selected 索引非负")
            if self.ranking is not None or self.scores is not None:
                raise ValueError("choice 答案禁止携带 ranking/scores（跨原语字段）")
        else:
            if not self.ranking:
                raise ValueError("score 答案必须给 ranking（索引排序）")
            if self.selected is not None or self.confidence is not None:
                raise ValueError("score 答案禁止携带 selected/confidence（跨原语字段）")
            if any(i < 0 for i in self.ranking):
                raise ValueError("score ranking 索引非负")
            if self.scores is not None:
                if len(self.scores) != len(self.ranking):
                    raise ValueError("scores 与 ranking 等长对齐（rank 序）")
                if any(s is not None and not math.isfinite(s) for s in self.scores):
                    raise ValueError("scores 必须为有限值或 None")
        return self


def validate_answer_against_question(
    answer: SystemOneAnswer, question: SystemOneQuestion
) -> dict[str, Any]:
    """答案↔问题交叉校验（确定性守卫）：选择越界/排序非置换如实报 errors。"""
    errors: list[str] = []
    if answer.kind != question.kind:
        errors.append(f"kind 不一致：answer={answer.kind} question={question.kind}")
    elif question.kind == "choice":
        opts = question.options or []
        sel = answer.selected
        if isinstance(sel, bool) or not isinstance(sel, (int, str)):
            errors.append("choice selected 必须是索引 int 或选项原文 str")
        elif isinstance(sel, int) and not (0 <= sel < len(opts)):
            errors.append(f"choice selected 索引越界：{sel}（options={len(opts)}）")
        elif isinstance(sel, str) and sel not in opts:
            errors.append("choice selected 文本不在 options 中")
    else:
        n = len(question.items or [])
        rank = answer.ranking or []
        if sorted(rank) != list(range(n)):
            errors.append(f"score ranking 必须是 0..{n - 1} 的置换（items={n}）")
    return ok_envelope(valid=not errors, errors=errors, source=_SOURCE)


# ─── provider 基类 + 注册表（规则 3，照 EMSolverRegistry 惯例） ───────────────


class SystemOneProviderError(RuntimeError):
    """provider 运行面故障（不可用/响应不可解析）——门面捕获后降级。"""


class ProviderUnavailableError(SystemOneProviderError):
    """外部 provider 配置缺失——"配置存在才启用"，绝不隐式回退读网（#139）。"""


class SystemOneProvider(ABC):
    """System One provider 基类：ask(question) -> SystemOneAnswer。"""

    name: str = "base"

    @abstractmethod
    def ask(self, question: SystemOneQuestion) -> SystemOneAnswer:
        """回答一个 typed-question（实现必须构造过 SystemOneAnswer 白名单门）。"""

    def health(self) -> dict[str, Any]:
        """可用性快照（零网络；外部 provider 按配置存在性判定）。"""
        return {"provider": self.name, "available": True, "detail": ""}


class SystemOneRegistry:
    """provider 注册表：name → 工厂（类或零参 callable）。"""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], SystemOneProvider]] = {}

    def register(
        self, name: str, factory: Callable[[], SystemOneProvider]
    ) -> None:
        """注册 provider 工厂（同名覆盖=换实现，注册表模式惯例）。"""
        self._factories[name] = factory

    def create(self, name: str) -> SystemOneProvider:
        if name not in self._factories:
            raise ProviderUnavailableError(
                f"未注册的 System One provider: {name}（在册={self.list_providers()}）")
        return self._factories[name]()

    def list_providers(self) -> list[str]:
        return sorted(self._factories)

    def is_registered(self, name: str) -> bool:
        return name in self._factories


_REGISTRY = SystemOneRegistry()


def get_systemone_registry() -> SystemOneRegistry:
    """全局注册表访问口（可替换组件扩展点，规则 3）。"""
    return _REGISTRY


# ─── 内置 provider 1：deterministic（缺省，零网络零依赖） ─────────────────────


def _default_decide(question: SystemOneQuestion) -> SystemOneAnswer:
    """缺省确定性决策：choice=首选项、score=原序（保守恒等，如实零语义）。

    真实决策函数由调用方注入（``DeterministicProvider(decide=...)``）——
    缺省实现只保证"永远有合法答案"，不假装智能。
    """
    if question.kind == "choice":
        return SystemOneAnswer(kind="choice", selected=0)
    return SystemOneAnswer(kind="score",
                           ranking=list(range(len(question.items or []))))


class DeterministicProvider(SystemOneProvider):
    """缺省 provider：可注入确定性决策函数，零网络零依赖。"""

    name = "deterministic"

    def __init__(
        self,
        decide: Callable[[SystemOneQuestion], SystemOneAnswer] | None = None,
    ) -> None:
        self._decide = decide or _default_decide

    def ask(self, question: SystemOneQuestion) -> SystemOneAnswer:
        return self._decide(question)


# ─── 配置面（复用既有 chat 通道；#139：配置存在才启用） ───────────────────────


def _chat_raw() -> dict[str, Any]:
    """既有 chat 通道原始配置（含 api_key；惰性导入防环）。"""
    from rfauto.service.r3_services import get_chat_settings_raw

    return get_chat_settings_raw() or {}


def _systemone_section() -> dict[str, Any]:
    """chat_settings.yaml 的可选 ``systemone`` 段（typesafe_jev/缺省 provider）。"""
    section = _chat_raw().get("systemone")
    return section if isinstance(section, dict) else {}


# ─── 外发 sanitize（规则 8 精神：外发零敏感，留痕不泄密） ─────────────────────

#: 占位符前缀；redactions 只记规则名+命中次数，不记命中原文
_REDACTED_FMT = "<redacted:{rule}>"

# 路径/主机类字符类：空白、引号、尖括号、管道、ASCII 括号方括号花括号与
# 全角闭合标点处截断（防把句尾标点吃进占位符）
_PATH_STOP = r"[^\s\"'<>|()\[\]{}，。；、【】《》「」]"

_SANITIZE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Windows 盘符绝对路径：D:/rf_workspace\runs\xxx、C:/Users/pc/...
    ("win_drive_path",
     re.compile(r"(?i)\b[a-z]:[\\/]" + _PATH_STOP + r"{0,200}")),
    # POSIX 用户/系统绝对路径：/home/u、/Users/u、/root、/mnt、/srv、/opt
    ("posix_abs_path",
     re.compile(r"(?i)(?<![\w])/(?:home|users|root|mnt|srv|opt)/"
                + _PATH_STOP + r"{0,200}")),
    # 凭据样态：api_key=... / token: ... / Authorization: Bearer x / sk-xxx
    #（(?i) 必须置首——Python 3.11+ 表达式中段内联全局旗标直接 re.error）
    ("credential",
     re.compile(
         r"(?i)\b(?:api[_-]?key|apikey|access[_-]?token|token|secret|"
         r"password|passwd|authorization|auth)\s*[=:：]\s*\S{4,}"
         r"|\bbearer\s+[a-z0-9._~+/=-]{8,}"
         r"|\bsk-[A-Za-z0-9]{8,}")),
    # 私有网段 IP（10/172.16-31/192.168——课题组服务器/内网面）
    ("private_ip",
     re.compile(r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)"
                r"\.\d{1,3}\.\d{1,3}\b")),
    # 主机名:端口（sim_host:88、api.typesafe.ai:443；首段须字母/下划线起，
    # 不误伤 "12:30" 类时间样态）
    ("host_port",
     re.compile(r"(?i)\b[a-z_][a-z0-9_-]*(?:\.[a-z_][a-z0-9_-]*)*:\d{2,5}\b")),
    # 长随机串（≥40 的 hex/base64 样态——凭据/哈希碎片兜底）
    ("long_token",
     re.compile(r"\b[A-Za-z0-9+/=_-]{40,}\b")),
)


def _sanitize_text(text: str,
                   counts: dict[str, int]) -> str:
    for rule_name, pattern in _SANITIZE_RULES:
        text, n = pattern.subn(_REDACTED_FMT.format(rule=rule_name), text)
        if n:
            counts[rule_name] = counts.get(rule_name, 0) + n
    return text


def sanitize_outbound(payload: Any) -> tuple[Any, list[dict[str, Any]]]:
    """外发前剥离敏感面（盘符绝对路径/私有 IP/主机:端口/凭据样态）。

    递归遍历 dict/list/tuple，字符串逐规则替换为 ``<redacted:规则名>``；
    返回 ``(sanitized_payload, redactions)``，redactions 项=
    ``{"rule", "placeholder", "count"}``——**只计数留痕，不记命中原文**
    （审计面自身不得成为泄漏面）。
    """
    counts: dict[str, int] = {}

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            return _sanitize_text(node, counts)
        if isinstance(node, dict):
            return {str(_walk(k) if isinstance(k, str) else k): _walk(v)
                    for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            out = [_walk(v) for v in node]
            return out if isinstance(node, list) else tuple(out)
        return node

    sanitized = _walk(payload)
    redactions = [
        {"rule": rule, "placeholder": _REDACTED_FMT.format(rule=rule),
         "count": counts[rule]}
        for rule in (r for r, _ in _SANITIZE_RULES) if rule in counts
    ]
    return sanitized, redactions


# ─── 内置 provider 2：openai_compatible（复用既有 chat 通道配置面） ───────────


def _default_chat_transport(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """OpenAI 兼容单次 chat 调用（复用 agent_runtime 既有传输层与配置）。

    测试 monkeypatch 点（#139）：钉住本函数即钉住全部外呼。
    """
    from rfauto.service.agent_runtime import openai_chat_completion

    return openai_chat_completion(messages, [])


_ANSWER_FORMAT_HINT = {
    "choice": '只输出一个 JSON 对象：{"selected": <0 起始选项索引或选项原文>,'
              ' "confidence": <0..1 或 null>}，不要输出其他文字',
    "score": '只输出一个 JSON 对象：{"ranking": [<按偏好降序的 0 起始索引置换>],'
             ' "scores": [<与 ranking 等长的偏好分或 null>]}，不要输出其他文字',
}


class OpenAICompatibleProvider(SystemOneProvider):
    """Jev 范式适配器：把 choice/score 渲染成单次 chat 调用+结构化解析。

    复用既有 chat 通道配置（configs/chat_settings.yaml 的 base_url/model/
    api_key——经 agent_runtime.openai_chat_completion 既有传输层，模型/
    鉴权/URL 映射零重写）。配置缺失 → 注册但在册 health=unavailable，
    ask() 抛 ProviderUnavailableError（#139 绝不隐式回退读网）。

    外发前对渲染负载整体 ``sanitize_outbound``（规则 8 精神外发面）。
    """

    name = "openai_compatible"

    def __init__(
        self,
        transport: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
    ) -> None:
        self._transport = transport or _default_chat_transport

    def health(self) -> dict[str, Any]:
        cfg = _chat_raw()
        missing = [k for k in ("base_url", "model") if not cfg.get(k)]
        if missing:
            return {"provider": self.name, "available": False,
                    "detail": "chat 通道未配置（缺 " + "/".join(missing) +
                              "；configs/chat_settings.yaml）"}
        return {"provider": self.name, "available": True,
                "detail": "复用 chat 通道（model=" + str(cfg.get("model")) + "）"}

    def _require_config(self) -> dict[str, Any]:
        cfg = _chat_raw()
        if not cfg.get("base_url") or not cfg.get("model"):
            raise ProviderUnavailableError(
                "openai_compatible 不可用：chat 通道缺 base_url/model 配置"
                "（配置存在才启用，不隐式回退读网）")
        return cfg

    def _render(self, question: SystemOneQuestion) -> list[dict[str, Any]]:
        payload = {"kind": question.kind, "question": question.question,
                   "options": question.options, "items": question.items,
                   "context": question.context}
        clean, _redactions = sanitize_outbound(payload)
        return [
            {"role": "system",
             "content": "你是 System One 决策通道：只做类型化判定，"
                        "不解释、不生成正文。" + _ANSWER_FORMAT_HINT[question.kind]},
            {"role": "user", "content": json.dumps(clean, ensure_ascii=False)},
        ]

    def ask(self, question: SystemOneQuestion) -> SystemOneAnswer:
        self._require_config()
        messages = self._render(question)
        resp = self._transport(messages)
        try:
            content = resp["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise SystemOneProviderError(
                f"chat 响应形状异常：{exc!r}") from exc
        return self._parse(content, question.kind)

    def _parse(self, content: str, kind: str) -> SystemOneAnswer:
        data = _extract_json_object(content)
        data["kind"] = kind
        try:
            return SystemOneAnswer.model_validate(data)
        except ValidationError as exc:
            raise SystemOneProviderError(
                f"provider 答案未过白名单 schema：{exc}") from exc


def _extract_json_object(content: str) -> dict[str, Any]:
    """从 provider 文本回复提取首个 JSON 对象（容 markdown 围栏）。"""
    text = (content or "").strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        tail = text.rstrip()
        if first_nl != -1 and tail.endswith("```"):
            text = text[first_nl + 1:tail.rfind("```")].strip()
    try:
        out = json.loads(text)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            out = json.loads(match.group(0))
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass
    raise SystemOneProviderError(
        f"provider 返回内容无法解析为 JSON 对象：{text[:120]!r}")


# ─── 内置 provider 3：typesafe_jev（官方端点形态骨架，配置存在才启用） ─────────


def _default_http_post_json(
    url: str, body: dict[str, Any], *, api_key: str, timeout_s: float
) -> dict[str, Any]:
    """官方端点 POST（urllib，仓内既有 HTTP 惯例；测试 monkeypatch 点 #139）。"""
    import urllib.request

    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


_RESPONSE_WRAPPER_KEYS = ("answer", "data", "result")


class TypesafeJevProvider(SystemOneProvider):
    """TypeSafe 官方端点形态骨架：``POST {base}/v1/systemone``，model=jev-latest。

    配置面=chat_settings.yaml 可选 ``systemone`` 段：
    ``{provider: typesafe_jev, base_url: https://api.typesafe.ai,
       api_key: ..., model: jev-latest, timeout_s: 30}``——段缺失/无 api_key
    → 注册但在册 health=unavailable，ask() 抛 ProviderUnavailableError。
    响应映射骨架：接受裸答案对象或 ``{"answer"|"data"|"result": {...}}``
    包裹形态，最终一律过 SystemOneAnswer 白名单门（铁律 7 对外部输出同门）。
    """

    name = "typesafe_jev"

    def __init__(
        self,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._transport = transport or _default_http_post_json

    def _config(self) -> dict[str, Any]:
        section = _systemone_section()
        raw_timeout = section.get("timeout_s")
        # #364④ 家法：数值可达 0 的面禁 `or` 缺省惯语——0/0.0 是合法显式值
        # （此处语义=禁等待立即超时），仅 None/缺键走缺省。
        return {
            "base_url": str(section.get("base_url") or "https://api.typesafe.ai"),
            "api_key": str(section.get("api_key") or ""),
            "model": str(section.get("model") or "jev-latest"),
            "timeout_s": float(raw_timeout) if raw_timeout is not None else 30.0,
        }

    def health(self) -> dict[str, Any]:
        section = _systemone_section()
        if not section or not section.get("api_key"):
            return {"provider": self.name, "available": False,
                    "detail": "systemone 段未配置 api_key"
                              "（configs/chat_settings.yaml；配置存在才启用）"}
        return {"provider": self.name, "available": True,
                "detail": "official endpoint（base=" +
                          str(section.get("base_url") or "https://api.typesafe.ai") + "）"}

    def _require_config(self) -> dict[str, Any]:
        cfg = self._config()
        if not cfg["api_key"]:
            raise ProviderUnavailableError(
                "typesafe_jev 不可用：systemone 段缺 api_key"
                "（配置存在才启用，不隐式回退读网）")
        return cfg

    def ask(self, question: SystemOneQuestion) -> SystemOneAnswer:
        cfg = self._require_config()
        question_payload = {"kind": question.kind, "question": question.question,
                            "options": question.options, "items": question.items,
                            "context": question.context}
        clean, _redactions = sanitize_outbound(question_payload)
        url = cfg["base_url"].rstrip("/") + "/v1/systemone"
        body = {"model": cfg["model"], "question": clean}
        resp = self._transport(url, body, api_key=cfg["api_key"],
                               timeout_s=cfg["timeout_s"])
        data = dict(resp) if isinstance(resp, dict) else {}
        for wrapper in _RESPONSE_WRAPPER_KEYS:
            inner = data.get(wrapper)
            if isinstance(inner, dict):
                data = dict(inner)
                break
        data["kind"] = question.kind
        try:
            return SystemOneAnswer.model_validate(data)
        except ValidationError as exc:
            raise SystemOneProviderError(
                f"provider 答案未过白名单 schema：{exc}") from exc


# 内置三 provider 注册（导入即注册，同内置适配器惯例）
_REGISTRY.register("deterministic", DeterministicProvider)
_REGISTRY.register("openai_compatible", OpenAICompatibleProvider)
_REGISTRY.register("typesafe_jev", TypesafeJevProvider)


# ─── 门面（服务 JSON 进出，规则 4；#105 降级兜底） ────────────────────────────


def resolve_systemone_provider(name: str | None = None) -> str:
    """解析生效 provider 名：显式传入 > systemone.provider 配置 > deterministic。"""
    if name:
        return name
    configured = str(_systemone_section().get("provider") or "").strip()
    if configured and _REGISTRY.is_registered(configured):
        return configured
    return "deterministic"


def ask_systemone(
    question: SystemOneQuestion | dict[str, Any], *,
    provider: str | None = None,
) -> dict[str, Any]:
    """System One 决策门面：typed-question → 信封（answer+provider+degraded）。

    - 缺省 provider 从配置解析（无配置→deterministic，零网络）；
    - provider 任何异常（含配置缺失/解析失败/未注册名）→ 捕获+``degraded:
      true``+``degrade_reason``+走缺省确定性兜底（#105：决策通道永不阻塞
      主路径；兜底=首选项/原序保守恒等，不冒充真实决策）；
    - 问题 schema 校验失败 → error 信封（契约违约显式报告，不静默降级）。
    """
    try:
        q = (question if isinstance(question, SystemOneQuestion)
             else SystemOneQuestion.model_validate(question))
    except ValidationError as exc:
        return error_envelope([f"问题 schema 校验失败：{exc}"], source=_SOURCE)
    name = resolve_systemone_provider(provider)
    try:
        impl = _REGISTRY.create(name)
        answer = impl.ask(q)
        # 语义越界交叉校验内联（审查 P2-3）：白名单 schema 挡物理字段，
        # 越界选择/非置换排序在此降级——不合格答案视同 provider 故障走兜底。
        xcheck = validate_answer_against_question(answer, q)
        if xcheck.get("errors"):
            raise SystemOneProviderError("; ".join(xcheck["errors"]))
    except Exception as exc:  # #105：provider 故障只降级不外抛（含未注册名）
        fallback = DeterministicProvider().ask(q)
        return ok_envelope(answer=fallback.model_dump(), provider=name,
                           degraded=True, degrade_reason=str(exc),
                           question_kind=q.kind, source=_SOURCE)
    return ok_envelope(answer=answer.model_dump(), provider=name,
                       degraded=False, question_kind=q.kind, source=_SOURCE)


def systemone_status() -> dict[str, Any]:
    """各 provider 注册与可用性快照（零网络；诊断/上层选型消费面）。"""
    rows = []
    for name in _REGISTRY.list_providers():
        impl = _REGISTRY.create(name)
        rows.append(impl.health())
    return ok_envelope(providers=rows, default=resolve_systemone_provider(),
                       source=_SOURCE)


def hint_question_for_message(message: str) -> dict[str, Any]:
    """构造"错误消息→hint 规则选择"choice 问题（error_hints 第二档用）。"""
    from rfauto.service.error_hints_service import list_hint_rules

    rules = list_hint_rules().get("rules") or []
    options = [str(r.get("pattern", "")) for r in rules]
    return SystemOneQuestion(
        kind="choice",
        question="为下述错误消息选择最可能的修复提示规则（只返回选项）：\n"
                 + str(message),
        options=options,
        context={"task": "hint_rule_select", "n_options": len(options)},
    ).model_dump()

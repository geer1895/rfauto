"""G1 Python SDK：REST 契约的薄客户端。

两种传输（都不新增第三方依赖）：
- 进程内（默认）：直接驱动 create_rest_app() 返回的 ASGI app，用
 starlette TestClient（懒加载）——单测/嵌入式脚本无需常驻服务器、无网络。
- HTTP：给 base_url 时用标准库 urllib 请求远端 rfauto rest-api 服务
 （确定性测试以下游 URL 打桩，不在单测里发真实网络请求）。

成功返回信封的 data；失败抛 RfautoApiError（含 status_code/code/message）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol


class RfautoApiError(RuntimeError):
  """REST 调用失败（HTTP >= 400 或信封 ok=False）。"""

  def __init__(self, status_code: int, code: str, message: str) -> None:
    super().__init__(f"[{status_code}] {code}: {message}")
    self.status_code = status_code
    self.code = code
    self.message = message


class _Transport(Protocol):
  def request(
    self,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
  ) -> tuple[int, Any]: ...


class InProcessTransport:
  """直接驱动 ASGI app（starlette TestClient，进程内、无网络）。"""

  def __init__(self, app: Any) -> None:
    from starlette.testclient import TestClient

    self._client = TestClient(app)

  def request(
    self,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
  ) -> tuple[int, Any]:
    response = self._client.request(
      method, path, params=params, json=json_body)
    return int(response.status_code), response.json()


class HttpTransport:
  """标准库 urllib 传输（接受 base_url，请求远端服务）。"""

  def __init__(self, base_url: str) -> None:
    self._base = base_url.rstrip("/")

  def request(
    self,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
  ) -> tuple[int, Any]:
    url = f"{self._base}{path}"
    if params:
      url = f"{url}?{urllib.parse.urlencode(params)}"
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
      request.add_header("Content-Type", "application/json")
    try:
      with urllib.request.urlopen(request) as response:
        return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
      raw = exc.read().decode("utf-8")
      try:
        payload = json.loads(raw)
      except ValueError:
        payload = {"ok": False, "error": {
          "code": "http_error", "message": raw or f"HTTP {exc.code}"}}
      return int(exc.code), payload


class RfautoClient:
  """rfauto REST API 薄客户端。

  用法::

    client = RfautoClient()          # 进程内（默认）
    client = RfautoClient(base_url="http://127.0.0.1:8644") # 远端
    client.health()
    client.calculate("attenuator_pi", {"attenuation_db": 3.0, "z0_ohm": 50.0})
  """

  def __init__(
    self,
    app: Any = None,
    *,
    base_url: str | None = None,
    transport: _Transport | None = None,
  ) -> None:
    if transport is not None:
      self._transport: _Transport = transport
    elif base_url:
      self._transport = HttpTransport(base_url)
    else:
      from rfauto.service.rest_api import create_rest_app

      self._transport = InProcessTransport(
        app if app is not None else create_rest_app())

  # -- 内部 ---------------------------------------------------------------

  def _request(
    self,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
  ) -> tuple[int, Any]:
    return self._transport.request(
      method, path, params=params, json_body=json_body)

  @staticmethod
  def _error_from(status: int, payload: Any) -> RfautoApiError:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
      code = str(error.get("code") or "error")
      message = str(error.get("message") or "")
      return RfautoApiError(status, code, message)
    return RfautoApiError(status, "http_error", f"HTTP {status}")

  def _call(
    self,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
  ) -> Any:
    status, payload = self._request(
      method, path, params=params, json_body=json_body)
    if status >= 400 or not (isinstance(payload, dict) and payload.get("ok")):
      raise self._error_from(status, payload)
    return payload.get("data")

  # -- 端点 ---------------------------------------------------------------

  def health(self) -> dict[str, Any]:
    return self._call("GET", "/api/v1/health")

  def openapi(self) -> dict[str, Any]:
    status, payload = self._request("GET", "/api/v1/openapi.json")
    if status >= 400:
      raise self._error_from(status, payload)
    return payload

  def list_runs(self, limit: int = 50) -> dict[str, Any]:
    return self._call("GET", "/api/v1/runs", params={"limit": limit})

  def run_detail(self, run_id: str) -> dict[str, Any]:
    return self._call("GET", f"/api/v1/runs/{run_id}")

  def list_calculators(self, include_experimental: bool = True) -> dict[str, Any]:
    """计算器清单；include_experimental=False 剔除实验键（REST 查询参数透传）。"""
    params = None if include_experimental else {"include_experimental": "false"}
    return self._call("GET", "/api/v1/calculators", params=params)

  def calculate(
    self, name: str, params: dict[str, Any] | None = None,
    *, allow_experimental: bool | None = None,
  ) -> dict[str, Any]:
    """执行计算器；allow_experimental 三态（True/False/None）随请求体透传。"""
    body: dict[str, Any] = {"params": dict(params or {})}
    if allow_experimental is not None:
      body["allow_experimental"] = bool(allow_experimental)
    return self._call(
      "POST", f"/api/v1/calculators/{name}/run", json_body=body)

  def query_dataset(
    self,
    name: str,
    *,
    where: str | None = None,
    columns: list[str] | None = None,
    limit: int | None = None,
    model: str | None = None,
    study_name: str | None = None,
  ) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name}
    for key, value in (("where", where), ("columns", columns),
              ("limit", limit), ("model", model),
              ("study_name", study_name)):
      if value is not None:
        body[key] = value
    return self._call("POST", "/api/v1/datasets/query", json_body=body)

  # ---- datasets 余量（dataset_insights 八接口，E1 收口 re-export）------

  def list_datasets(self, visibility: str | None = None) -> dict[str, Any]:
    params = {"visibility": visibility} if visibility is not None else None
    return self._call("GET", "/api/v1/datasets", params=params)

  def dataset_coverage(
    self, name: str, *, bins: int | None = None
  ) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name}
    if bins is not None:
      body["bins"] = bins
    return self._call("POST", "/api/v1/datasets/coverage", json_body=body)

  def annotate_ground_truth(
    self, name: str, *, threshold: int | None = None
  ) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name}
    if threshold is not None:
      body["threshold"] = threshold
    return self._call(
      "POST", "/api/v1/datasets/ground-truth/annotate", json_body=body)

  def neural_operator_readiness(
    self, name: str, *, threshold: int | None = None
  ) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name}
    if threshold is not None:
      body["threshold"] = threshold
    return self._call(
      "POST", "/api/v1/datasets/neural-operator-readiness", json_body=body)

  def set_dataset_visibility(self, name: str, visibility: str) -> dict[str, Any]:
    return self._call(
      "POST", "/api/v1/datasets/visibility",
      json_body={"name": name, "visibility": visibility})

  def export_hf_dataset(
    self,
    name: str,
    *,
    license: str | None = None,
    allow_private: bool | None = None,
  ) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name}
    if license is not None:
      body["license"] = license
    if allow_private is not None:
      body["allow_private"] = allow_private
    return self._call("POST", "/api/v1/datasets/export-hf", json_body=body)

  def register_public_dataset(
    self,
    name: str,
    *,
    source: str | None = None,
    license: str | None = None,
    promote: bool | None = None,
  ) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name}
    for key, value in (("source", source), ("license", license),
              ("promote", promote)):
      if value is not None:
        body[key] = value
    return self._call(
      "POST", "/api/v1/datasets/public/register", json_body=body)

  def load_dataset_sets(self) -> dict[str, Any]:
    return self._call("GET", "/api/v1/datasets/sets")

  # ---- db / rag / 工作目录发现 / slotline·transitions（只读透传，F-R2-3）--

  def db_status(self, db_path: str | None = None) -> dict[str, Any]:
    """注册表状态盘点（只读不建库）。"""
    params = {"db_path": db_path} if db_path is not None else None
    return self._call("GET", "/api/v1/db/status", params=params)

  def db_query(
    self,
    sql: str,
    params: list[Any] | None = None,
    *,
    limit: int | None = None,
    db_path: str | None = None,
  ) -> dict[str, Any]:
    """只读查询注册表（SELECT 白名单 + ? 占位符参数绑定）。"""
    body: dict[str, Any] = {"sql": sql}
    if params is not None:
      body["params"] = list(params)
    if limit is not None:
      body["limit"] = limit
    if db_path is not None:
      body["db_path"] = db_path
    return self._call("POST", "/api/v1/db/query", json_body=body)

  def rag_query(
    self,
    text: str,
    *,
    top_k: int | None = None,
    docs_dir: str | None = "docs",
    runs_dir: str | None = "runs",
    runs_limit: int | None = None,
  ) -> dict[str, Any]:
    """RAG 词法检索（BM25，只读、citation 可溯）。

    docs_dir/runs_dir 缺省 docs/runs；显式传 None 随请求体发 null 跳过
    该来源（与 CLI/MCP 同口径）。
    """
    body: dict[str, Any] = {
      "text": text, "docs_dir": docs_dir, "runs_dir": runs_dir}
    if top_k is not None:
      body["top_k"] = top_k
    if runs_limit is not None:
      body["runs_limit"] = runs_limit
    return self._call("POST", "/api/v1/rag/query", json_body=body)

  def rag_explain(
    self,
    text: str,
    *,
    top_k: int | None = None,
    docs_dir: str | None = "docs",
    runs_dir: str | None = "runs",
    runs_limit: int | None = None,
  ) -> dict[str, Any]:
    """RAG 检索 + 逐词 BM25 分数明细（hits[].score_breakdown）。"""
    body: dict[str, Any] = {
      "text": text, "docs_dir": docs_dir, "runs_dir": runs_dir}
    if top_k is not None:
      body["top_k"] = top_k
    if runs_limit is not None:
      body["runs_limit"] = runs_limit
    return self._call("POST", "/api/v1/rag/explain", json_body=body)

  def discover_workdir(
    self,
    runs_root: str | None = None,
    models: list[str] | None = None,
  ) -> dict[str, Any]:
    """发现工作目录形态真机产物（只读；models 为器件族列表）。"""
    params: dict[str, Any] = {}
    if runs_root is not None:
      params["runs_root"] = runs_root
    if models is not None:
      params["models"] = ",".join(models)
    return self._call(
      "GET", "/api/v1/datasets/discover-workdir", params=params or None)

  def slotline_analyze(
    self, w_mm: float, h_mm: float, epsilon_r: float, freq_ghz: float,
  ) -> dict[str, Any]:
    """槽线闭式分析：(w, h, εr, f) → Z0/εeff/β/λ'。"""
    return self._call("POST", "/api/v1/slotline/analyze", json_body={
      "w_mm": w_mm, "h_mm": h_mm,
      "epsilon_r": epsilon_r, "freq_ghz": freq_ghz})

  def slotline_synth(
    self, z0_ohm: float, h_mm: float, epsilon_r: float, freq_ghz: float,
  ) -> dict[str, Any]:
    """槽线综合：目标 Z0 → 槽宽 w。"""
    return self._call("POST", "/api/v1/slotline/synth", json_body={
      "z0_ohm": z0_ohm, "h_mm": h_mm,
      "epsilon_r": epsilon_r, "freq_ghz": freq_ghz})

  def msl_slot_transition(
    self,
    f0_ghz: float,
    h_mm: float,
    er: float,
    w_slot_mm: float,
    *,
    tan_d: float | None = None,
    z_msl_target: float | None = None,
  ) -> dict[str, Any]:
    """Roberts/Knorr MSL↔槽线过渡设计参数（+ 预声明过渡门）。"""
    body: dict[str, Any] = {
      "f0_ghz": f0_ghz, "h_mm": h_mm, "er": er, "w_slot_mm": w_slot_mm}
    if tan_d is not None:
      body["tan_d"] = tan_d
    if z_msl_target is not None:
      body["z_msl_target"] = z_msl_target
    return self._call(
      "POST", "/api/v1/transitions/msl-slot", json_body=body)

  def marchand_balun(
    self,
    f0_ghz: float,
    h_mm: float,
    er: float,
    w_slot_mm: float,
    *,
    tan_d: float | None = None,
    z_msl_target: float | None = None,
  ) -> dict[str, Any]:
    """双槽臂 Marchand 巴伦（最小族）设计参数（+ 预声明巴伦门）。"""
    body: dict[str, Any] = {
      "f0_ghz": f0_ghz, "h_mm": h_mm, "er": er, "w_slot_mm": w_slot_mm}
    if tan_d is not None:
      body["tan_d"] = tan_d
    if z_msl_target is not None:
      body["z_msl_target"] = z_msl_target
    return self._call(
      "POST", "/api/v1/transitions/marchand-balun", json_body=body)

  def marchand_two_section(
    self,
    *,
    f0_ghz: float | None = None,
    z_unbal_ohm: float | None = None,
    z_bal_diff_ohm: float | None = None,
    er: float | None = None,
    h_mm: float | None = None,
    tan_d: float | None = None,
    s_min_mm: float | None = None,
    w_max_mm: float | None = None,
    z_c_ohm: float | None = None,
    band_ghz: list[float] | None = None,
  ) -> dict[str, Any]:
    """两节对称 Marchand 电路级综合；全部可选（缺省走 service 名义点）。"""
    body: dict[str, Any] = {}
    for key, value in (
        ("f0_ghz", f0_ghz), ("z_unbal_ohm", z_unbal_ohm),
        ("z_bal_diff_ohm", z_bal_diff_ohm), ("er", er),
        ("h_mm", h_mm), ("tan_d", tan_d), ("s_min_mm", s_min_mm),
        ("w_max_mm", w_max_mm), ("z_c_ohm", z_c_ohm),
        ("band_ghz", band_ghz)):
      if value is not None:
        body[key] = value
    return self._call(
      "POST", "/api/v1/transitions/marchand-two-section", json_body=body)

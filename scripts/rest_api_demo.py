"""G1 REST API + SDK 演示（确定性、无网络，进程内直接驱动 ASGI app）。

用法: .venv/Scripts/python.exe scripts/rest_api_demo.py
"""

from __future__ import annotations

import json

from rfauto.service import rest_api
from rfauto.service.sdk import RfautoClient


def main() -> int:
    spec = rest_api.openapi_spec()
    validation = rest_api.validate_openapi_spec(spec)
    print(f"OpenAPI {spec['openapi']} paths={len(spec['paths'])} "
          f"schemas={len(spec['components']['schemas'])} ok={validation['ok']}")
    client = RfautoClient()
    print("health:", json.dumps(client.health(), ensure_ascii=False))
    print("calculate:", json.dumps(
        client.calculate("attenuator_pi",
                         {"attenuation_db": 3.0, "z0_ohm": 50.0}),
        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

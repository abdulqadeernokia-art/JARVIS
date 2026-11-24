"""Home Assistant REST client (https://developers.home-assistant.io/docs/api/rest/).

You need a running Home Assistant instance, its URL (e.g. http://homeassistant.local:8123), and a long-lived access
token (Profile → Security → Long-lived access tokens). The token is kept in the DPAPI vault (core/secrets.py).
"""
from __future__ import annotations

import json
import urllib.request

from ..core import secrets

CONTROLLABLE = {"light", "switch", "fan", "cover", "media_player", "climate", "scene", "script", "input_boolean"}
SENSITIVE = {"lock", "alarm_control_panel"}   # never controlled from the UI without explicit confirmation


class HomeAssistant:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    @property
    def token(self) -> str | None:
        return secrets.get("HOME_ASSISTANT_TOKEN")

    def _req(self, method: str, path: str, body: dict | None = None):
        if not self.url or not self.token:
            raise RuntimeError("Home Assistant is not configured (URL and token needed).")
        req = urllib.request.Request(self.url + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 (user-configured local URL)
            return json.loads(r.read() or b"null")

    def ping(self) -> str:
        return self._req("GET", "/api/").get("message", "ok")

    def states(self) -> list[dict]:
        out = []
        for s in self._req("GET", "/api/states"):
            domain = s["entity_id"].split(".")[0]
            if domain in CONTROLLABLE | SENSITIVE or domain in ("sensor", "binary_sensor"):
                out.append({"entity_id": s["entity_id"], "domain": domain, "state": s["state"],
                            "name": s["attributes"].get("friendly_name", s["entity_id"]),
                            "unit": s["attributes"].get("unit_of_measurement", "")})
        return out

    def call(self, domain: str, service: str, entity_id: str, data: dict | None = None):
        return self._req("POST", f"/api/services/{domain}/{service}", {"entity_id": entity_id, **(data or {})})

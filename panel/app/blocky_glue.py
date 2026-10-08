"""Technitium → Blocky (hybrid B): всегда IP, лучше фиксированный DNS_BLOCKY_IP.

Пароль на диск не кладём. Вызывается с уже авторизованным TechnitiumClient
(login / PUT forwarders).
"""

from __future__ import annotations

import os
from typing import Any

from .technitium import TechnitiumClient, TechnitiumError


def blocky_forwarder_target() -> str:
    # Всегда фиксированный IP из compose — не резолвим «blocky» (плывёт / Resolver exception)
    return (os.environ.get("DNS_BLOCKY_IP") or "172.18.0.100").strip()


async def ensure_technitium_points_at_blocky(client: TechnitiumClient) -> dict[str, Any]:
    target = blocky_forwarder_target()
    try:
        await client.settings_set(
            {
                "forwarders": target,
                "forwarderProtocol": "Udp",
                "concurrentForwarding": "false",
                "dnssecValidation": "false",
            }
        )
        return {"ok": True, "forwarders": target}
    except TechnitiumError as exc:
        return {"ok": False, "forwarders": target, "error": exc.message}

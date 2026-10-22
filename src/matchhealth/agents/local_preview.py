"""Local live-preview publisher: broadcasts overlays over a plain WebSocket so
web/index.html can render them live with no Azure dependency at all. This is
purely a visualisation/demo aid for local development -- the real deployed
path is `webpubsub_publisher()` in `publisher.py`, which this mirrors.
"""

from __future__ import annotations

import asyncio
import json
import logging

from matchhealth.shared.models import Overlay

log = logging.getLogger(__name__)


class LocalPreviewServer:
    def __init__(self, host: str = "localhost", port: int = 8765) -> None:
        self.host, self.port = host, port
        self._clients: set = set()
        self._server = None

    async def start(self) -> None:
        import websockets

        async def handler(ws) -> None:
            self._clients.add(ws)
            log.info("preview client connected (%d total)", len(self._clients))
            try:
                await ws.wait_closed()
            finally:
                self._clients.discard(ws)

        self._server = await websockets.serve(handler, self.host, self.port)
        log.info("local preview server listening on ws://%s:%d", self.host, self.port)

    async def publish(self, base: Overlay, variants: list[Overlay]) -> None:
        if not self._clients:
            return
        msg = json.dumps({"base": base.to_wire(), "variants": [v.to_wire() for v in variants]})
        await asyncio.gather(*(c.send(msg) for c in list(self._clients)), return_exceptions=True)

    async def broadcast_raw(self, payload: dict) -> None:
        """A second, independent stream (e.g. live health ticks) alongside the
        Overlay path above -- the frontend tells them apart by shape."""
        if not self._clients:
            return
        msg = json.dumps(payload)
        await asyncio.gather(*(c.send(msg) for c in list(self._clients)), return_exceptions=True)

    async def wait_for_a_client(self, timeout_s: float = 120.0) -> bool:
        """Blocks until at least one browser connects, so early moments aren't lost."""
        elapsed = 0.0
        while not self._clients and elapsed < timeout_s:
            await asyncio.sleep(0.25)
            elapsed += 0.25
        return bool(self._clients)

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

"""HTTP endpoint so a browser can get a short-lived Web PubSub client token.

Runs as its own scale-to-zero Container App, sharing the same Docker image
as the replay job -- just a different entrypoint command. Stdlib-only so the
image doesn't need an extra web framework for one GET endpoint.

    python -m matchhealth.negotiate_service
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv

log = logging.getLogger(__name__)


def _client_access_url() -> str:
    from azure.identity import DefaultAzureCredential
    from azure.messaging.webpubsubservice import WebPubSubServiceClient

    client = WebPubSubServiceClient(
        endpoint=os.environ["WEBPUBSUB_ENDPOINT"],
        hub=os.environ.get("WEBPUBSUB_HUB", "overlays"),
        credential=DefaultAzureCredential(),
    )
    token = client.get_client_access_token()
    return token["url"]


_snapshot_cache: dict = {"at": 0.0, "value": None}


def _snapshot() -> dict | None:
    """The demo job's latest catch-up, so a new viewer sees the match at once.
    Cached for 10s: a crowd of viewers costs one Cosmos read, not one each."""
    import time
    if not os.environ.get("COSMOS_ENDPOINT"):
        return None
    if time.time() - _snapshot_cache["at"] > 10:
        try:
            from matchhealth.shared.state import load_live_snapshot
            _snapshot_cache["value"] = load_live_snapshot()
        except Exception:  # pragma: no cover
            log.exception("snapshot read failed")
            _snapshot_cache["value"] = None
        _snapshot_cache["at"] = time.time()
    return _snapshot_cache["value"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/negotiate", "/"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            url = _client_access_url()
            body = json.dumps({"url": url, "snapshot": _snapshot()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # pragma: no cover
            log.exception("negotiate failed")
            self.send_response(500)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(str(exc).encode())

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        log.info(fmt, *args)


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("PORT", 8080))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log.info("negotiate service listening on :%d", port)
    server.serve_forever()


if __name__ == "__main__":
    main()

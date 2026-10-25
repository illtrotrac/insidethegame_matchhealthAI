"""Delivers overlays to viewers: console locally, Azure Web PubSub in the cloud."""

from __future__ import annotations

import os

from matchhealth.shared.models import Overlay


async def console_publish(base: Overlay, variants: list[Overlay]) -> None:
    print(f"[{base.show_at}] P{base.priority} {base.template:<20} {base.headline}")


def _client():
    from azure.identity import DefaultAzureCredential
    from azure.messaging.webpubsubservice import WebPubSubServiceClient

    # Fail fast instead of retrying: once the service refuses messages (a quota
    # or an outage) the SDK's retries can wait for the Retry-After header, which
    # stalls the whole match. A dropped message is healed by the next catch-up.
    return WebPubSubServiceClient(
        endpoint=os.environ["WEBPUBSUB_ENDPOINT"],
        hub=os.environ.get("WEBPUBSUB_HUB", "overlays"),
        credential=DefaultAzureCredential(),
        retry_total=0, connection_timeout=5, read_timeout=10,
    )


def safe_sender(send_to_all):
    """Wraps a send so a failure is logged and skipped; the match must go on."""
    failures = 0

    def send(payload: dict) -> None:
        nonlocal failures
        try:
            send_to_all(payload, content_type="application/json")
        except Exception as exc:
            failures += 1
            if failures == 1 or failures % 50 == 0:
                print(f"Web PubSub send failed ({failures} so far): {exc}")

    return send


def webpubsub_publisher():
    send = safe_sender(_client().send_to_all)

    async def publish(base: Overlay, variants: list[Overlay]) -> None:
        # Pass a dict, not a pre-dumped string: with content_type="application/json"
        # the SDK JSON-serializes `message` itself, so a string here gets dumped
        # twice (the client would receive a quoted JSON string, not an object).
        send({"base": base.to_wire(), "variants": [v.to_wire() for v in variants]})

    return publish


def webpubsub_health_sender():
    """A second, independent send path for the lightweight health-tick stream
    (control/chaos per team) -- additive, doesn't touch the Overlay contract
    the orchestrator and tests depend on."""
    send_now = safe_sender(_client().send_to_all)

    async def send(payload: dict) -> None:
        send_now(payload)

    return send

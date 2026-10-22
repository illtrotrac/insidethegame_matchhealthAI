"""Delivers overlays to viewers: console locally, Azure Web PubSub in the cloud."""

from __future__ import annotations

import os

from matchhealth.shared.models import Overlay


async def console_publish(base: Overlay, variants: list[Overlay]) -> None:
    print(f"[{base.show_at}] P{base.priority} {base.template:<20} {base.headline}")


def webpubsub_publisher():
    from azure.identity import DefaultAzureCredential
    from azure.messaging.webpubsubservice import WebPubSubServiceClient

    client = WebPubSubServiceClient(
        endpoint=os.environ["WEBPUBSUB_ENDPOINT"],
        hub=os.environ.get("WEBPUBSUB_HUB", "overlays"),
        credential=DefaultAzureCredential(),
    )

    async def publish(base: Overlay, variants: list[Overlay]) -> None:
        # Pass a dict, not a pre-dumped string: with content_type="application/json"
        # the SDK JSON-serializes `message` itself, so a string here gets dumped
        # twice (the client would receive a quoted JSON string, not an object).
        client.send_to_all(
            {"base": base.to_wire(), "variants": [v.to_wire() for v in variants]},
            content_type="application/json")

    return publish

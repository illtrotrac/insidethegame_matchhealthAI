"""Delivers overlays to viewers: console locally, Azure Web PubSub in the cloud."""

from __future__ import annotations

import json
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
        client.send_to_all(json.dumps({
            "base": base.to_wire(), "variants": [v.to_wire() for v in variants]}),
            content_type="application/json")

    return publish

from __future__ import annotations

import json


def to_sse(event) -> str:
    event_name = getattr(event, "event", "message")
    data = getattr(event, "data", {})
    if hasattr(event_name, "value"):
        event_name = event_name.value
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

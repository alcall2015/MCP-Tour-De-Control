import json


def sse_frame(event: str, data: dict) -> str:
    """One Server-Sent Events frame, UTF-8 kept readable."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

"""Reject oversized request bodies with HTTP 413 (defense-in-depth).

Checks the ``Content-Length`` header so an oversized payload is refused before
it is read into memory. Real HTTP clients — including the OpenTelemetry OTLP
exporter — always send ``Content-Length``, so this covers the practical
memory-exhaustion vector on the ingestion endpoints.

ponytail: header check only; a reverse proxy (nginx ``client_max_body_size``)
should enforce the same cap at the edge for pathological chunked uploads that
omit Content-Length.
"""

from starlette.types import ASGIApp, Receive, Scope, Send

_BODY = b'{"detail":"Request body too large"}'


class MaxBodySizeMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            for name, value in scope.get("headers") or []:
                if name == b"content-length":
                    try:
                        declared = int(value)
                    except ValueError:
                        break
                    if declared > self._max_bytes:
                        await self._reject(send)
                        return
                    break
        await self._app(scope, receive, send)

    async def _reject(self, send: Send) -> None:
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_BODY)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": _BODY})

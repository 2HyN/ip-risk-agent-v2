"""Safe Product UI redirect for completed provider connections."""

from __future__ import annotations

from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from iprisk_contracts import SourceType


class ProductSourceCompletionRedirect:
    def __init__(self, public_base_url: str) -> None:
        parsed = urlsplit(public_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("public_base_url must be an HTTP(S) origin")
        self._origin = (parsed.scheme, parsed.netloc)

    def __call__(
        self,
        *,
        source_type: SourceType,
        risk_workspace_id: str,
        connection_id: str,
    ) -> str:
        if not connection_id or len(connection_id) > 256:
            raise ValueError("connection_id must be a bounded opaque identifier")
        path = f"/w/{quote(risk_workspace_id, safe='')}/sources"
        query = urlencode(
            {
                "provider": source_type.value,
                "connection_id": connection_id,
                "status": "connected",
            }
        )
        return urlunsplit((*self._origin, path, query, ""))


__all__ = ["ProductSourceCompletionRedirect"]

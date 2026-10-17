"""Explicit same-host instance configuration; no fallback to a personal ledger."""
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class WebSettings:
    data_root: Path
    public_origin: str = "http://localhost:8000"

    def __post_init__(self):
        root = Path(self.data_root).expanduser()
        if not root.is_absolute():
            raise ValueError("Web data root must be an explicit absolute directory")
        root = root.resolve()
        from ..workspace import CODE_ROOT
        if root == Path(root.anchor) or root == Path.home() or root == CODE_ROOT or root.is_relative_to(CODE_ROOT):
            raise ValueError("Web data root must be a dedicated directory outside the code checkout")
        origin = urlsplit(self.public_origin)
        if (origin.scheme not in {"http", "https"} or not origin.hostname or origin.username or origin.password
                or origin.path or origin.query or origin.fragment):
            raise ValueError("Public origin must contain only scheme, host and optional port")
        try:
            port = origin.port
            if port is not None and port < 1:
                raise ValueError("Invalid origin port")
        except ValueError as exc:
            raise ValueError("Invalid public origin port") from exc
        if origin.scheme == "http" and origin.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Non-loopback public origins require HTTPS")
        if any(c.isspace() for c in self.public_origin) or self.public_origin.endswith(":"):
            raise ValueError("Invalid public origin")
        object.__setattr__(self, "data_root", root)
        object.__setattr__(self, "public_origin", self.public_origin.lower())

    @property
    def authority(self):
        return urlsplit(self.public_origin).netloc

    @property
    def secure_cookie(self):
        return self.public_origin.startswith("https://")

    @property
    def cookie_name(self):
        return "__Host-wealth_session" if self.secure_cookie else "wealth_session"

    @classmethod
    def from_environment(cls):
        root = os.environ.get("WEALTH_LEDGER_DATA_ROOT")
        if not root:
            raise ValueError("WEALTH_LEDGER_DATA_ROOT is required; no checkout-local Web default")
        return cls(Path(root), os.environ.get("WEALTH_LEDGER_PUBLIC_ORIGIN", "http://localhost:8000"))

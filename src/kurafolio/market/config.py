"""Operator configuration for market data. Off unless the operator enables it.

The configuration is a small JSON file the operator passes explicitly. It holds
no credentials; a provider that needs a key reads it from its own private file.
"""
from dataclasses import dataclass
import json
from pathlib import Path

from .service import QuoteService

MAX_CONFIG_BYTES = 4096
# Provider name -> factory(settings). Unofficial adapters are added here only
# after the owner approves the named endpoint (WL-P0-009A decision 1).
PROVIDERS = {}


@dataclass(frozen=True, slots=True)
class MarketSettings:
    provider: str = "none"
    cache_seconds: int = 60
    max_requests_per_minute: int = 30
    accept_unofficial_terms: bool = False

    def __post_init__(self):
        if not isinstance(self.provider, str) or not self.provider:
            raise ValueError("Market provider name is invalid")
        for name, low, high in (("cache_seconds", 0, 86400), ("max_requests_per_minute", 1, 600)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"Market setting {name} is out of range")
        if type(self.accept_unofficial_terms) is not bool:
            raise ValueError("accept_unofficial_terms must be true or false")

    @classmethod
    def from_mapping(cls, data):
        if not isinstance(data, dict) or not set(data) <= set(cls.__dataclass_fields__):
            raise ValueError("Unknown market configuration keys")
        return cls(**data)

    @classmethod
    def from_file(cls, path):
        raw = Path(path).read_bytes()
        if len(raw) > MAX_CONFIG_BYTES:
            raise ValueError("Market configuration file is too large")
        return cls.from_mapping(json.loads(raw))


def build_quote_service(settings=None, providers=None, **service_options):
    """Return the instance's single quote service. ``provider: none`` (the
    default) builds a service that makes no requests and reports no_provider."""
    settings = settings or MarketSettings()
    registry = PROVIDERS if providers is None else providers
    if settings.provider == "none":
        provider = None
    elif settings.provider not in registry:
        raise ValueError("Unknown market provider")
    else:
        factory = registry[settings.provider]
        if getattr(factory, "unofficial", False) and not settings.accept_unofficial_terms:
            raise ValueError("An unofficial provider needs accept_unofficial_terms: true")
        provider = factory(settings)
    return QuoteService(provider, cache_seconds=settings.cache_seconds,
                        max_requests=settings.max_requests_per_minute, per_seconds=60, **service_options)

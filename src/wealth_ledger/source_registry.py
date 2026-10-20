"""Explicit trusted parser registration and detection, independent of ingestion.

Discovery reads installed distribution metadata without importing plugins. Loading
runs trusted Python only for explicitly selected distribution/version/entry points.
This module neither installs packages nor integrates parsers with CLI/Web imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
import re
from typing import Iterable

from .source_protocol import AdapterInfo, Detection, SourceAdapter, validate_info
from .source_v2 import SourceAdapter as ContextSourceAdapter

ENTRY_POINT_GROUP = "wealth_ledger.source_adapters"
MAX_INPUT_BYTES = 10 * 1024 * 1024
_NAMESPACE = re.compile(r"[a-z][a-z0-9_.-]*")
_DISTRIBUTION = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
_MESSAGES = {
    "invalid_configuration": "Invalid source registry configuration",
    "invalid_catalog": "Invalid installed source plugin metadata",
    "unavailable_plugin": "Selected source plugin or exact version is unavailable",
    "ambiguous_plugin": "Installed source plugin entry points collide",
    "plugin_load_failed": "Selected source plugin failed to load",
    "invalid_adapter": "Source adapter does not satisfy its declared contract",
    "incompatible_adapter": "Source adapter API version is unsupported",
    "duplicate_adapter": "Source adapter IDs must be unique",
    "conflicting_provider": "Source adapters declare conflicting provider metadata",
    "unknown_adapter": "Selected source adapter is not enabled",
    "invalid_input": "Source detection requires nonempty bounded bytes",
    "detection_failed": "An enabled source detector failed",
    "invalid_detection": "A source detector returned an invalid result",
    "no_match": "No enabled source adapter matches the input",
    "ambiguous_detection": "Multiple source adapters match; select an enabled adapter explicitly",
}


class RegistryError(ValueError):
    """Stable error codes; messages do not include plugin exceptions or source data."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(_MESSAGES[code])


@dataclass(frozen=True)
class ProviderInfo:
    provider_id: str
    display_name: str


@dataclass(frozen=True)
class PluginSelection:
    """Host-owned exact enablement, never an upload or a Python import path."""
    distribution: str
    version: str
    entry_point: str
    adapter_id: str


@dataclass(frozen=True)
class PluginCandidate:
    """Installed metadata; the entry point is not loaded during discovery."""
    distribution: str
    version: str
    entry_point: str
    target: str
    _entry_point: metadata.EntryPoint = field(repr=False, compare=False)


@dataclass(frozen=True)
class AdapterRegistration:
    """External entry-point factories return this same shape as trusted built-ins."""
    provider: ProviderInfo
    adapter: SourceAdapter | ContextSourceAdapter


@dataclass(frozen=True)
class AdapterDescriptor:
    provider: ProviderInfo
    info: AdapterInfo
    plugin: PluginSelection | None = None


@dataclass(frozen=True)
class SourceMatch:
    descriptor: AdapterDescriptor
    export_version: str
    reason: str


def _text(value):
    return (isinstance(value, str) and bool(value) and value == value.strip()
            and len(value) <= 200 and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _distribution(value):
    if not _text(value) or not _DISTRIBUTION.fullmatch(value):
        raise RegistryError("invalid_configuration")
    return re.sub(r"[-_.]+", "-", value).lower()


def _namespace(value):
    return _text(value) and _NAMESPACE.fullmatch(value) is not None


def _selection(value):
    if (not isinstance(value, PluginSelection) or not _text(value.version)
            or not _namespace(value.entry_point) or not _namespace(value.adapter_id)):
        raise RegistryError("invalid_configuration")
    return (_distribution(value.distribution), value.version, value.entry_point)


def _catalog_key(candidate):
    try:
        if (not isinstance(candidate, PluginCandidate) or not _text(candidate.version)
                or not _namespace(candidate.entry_point) or not _text(candidate.target)
                or not isinstance(candidate._entry_point, metadata.EntryPoint)
                or candidate._entry_point.group != ENTRY_POINT_GROUP
                or candidate._entry_point.name != candidate.entry_point
                or candidate._entry_point.value != candidate.target):
            raise ValueError("Invalid catalog")
        return (_distribution(candidate.distribution), candidate.entry_point)
    except (ValueError, TypeError, AttributeError):
        raise RegistryError("invalid_catalog") from None


def _catalog(candidates):
    by_key = {}
    for candidate in candidates:
        key = _catalog_key(candidate)
        if key in by_key:
            raise RegistryError("ambiguous_plugin")
        by_key[key] = candidate
    return by_key


def discover_plugins(distributions: Iterable | None = None) -> tuple[PluginCandidate, ...]:
    """Enumerate metadata only. Optional distributions support offline host tests."""
    try:
        found = []
        for distribution in metadata.distributions() if distributions is None else distributions:
            for point in distribution.entry_points:
                if point.group == ENTRY_POINT_GROUP:
                    found.append(PluginCandidate(distribution.metadata["Name"], distribution.version,
                                                 point.name, point.value, point))
        catalog = _catalog(found)
        return tuple(catalog[key] for key in sorted(catalog))
    except RegistryError:
        raise
    except Exception:
        raise RegistryError("invalid_catalog") from None


def _describe(registration, plugin=None):
    try:
        if not isinstance(registration, AdapterRegistration):
            raise RegistryError("invalid_adapter")
        provider, adapter = registration.provider, registration.adapter
        if (not isinstance(provider, ProviderInfo) or not _namespace(provider.provider_id)
                or not _text(provider.display_name)):
            raise RegistryError("invalid_adapter")
        info = adapter.info
        # Inspection compatibility is separate from financial booking capability.
        from .source_protocol import API_VERSION
        from .source_v2 import API_VERSION as V2, validate_info as validate_v2_info
        if not isinstance(info, AdapterInfo):
            raise RegistryError("invalid_adapter")
        if type(info.api_version) is not int or info.api_version not in {API_VERSION, V2}:
            raise RegistryError("incompatible_adapter")
        (validate_info if info.api_version == API_VERSION else validate_v2_info)(info)
        if not _namespace(info.adapter_id) or not _text(info.adapter_version):
            raise RegistryError("invalid_adapter")
        if (info.provider_id != provider.provider_id or not callable(adapter.detect)
                or not callable(adapter.normalize) or plugin is not None and info.adapter_id != plugin.adapter_id):
            raise RegistryError("invalid_adapter")
        return AdapterDescriptor(provider, info, plugin)
    except RegistryError:
        raise
    except Exception:
        raise RegistryError("invalid_adapter") from None


@dataclass(frozen=True)
class SourceRegistry:
    """An immutable registry snapshot; detection cannot book normalized records."""
    _entries: tuple[tuple[AdapterDescriptor, SourceAdapter | ContextSourceAdapter], ...] = field(repr=False)

    @property
    def adapters(self) -> tuple[AdapterDescriptor, ...]:
        return tuple(descriptor for descriptor, _ in self._entries)

    def detect(self, raw: bytes, *, adapter_id: str | None = None) -> SourceMatch:
        if type(raw) is not bytes or not raw or len(raw) > MAX_INPUT_BYTES:
            raise RegistryError("invalid_input")
        if adapter_id is not None and not _namespace(adapter_id):
            raise RegistryError("unknown_adapter")
        entries = tuple(entry for entry in self._entries if adapter_id is None or entry[0].info.adapter_id == adapter_id)
        if adapter_id is not None and not entries:
            raise RegistryError("unknown_adapter")
        results = []
        for descriptor, adapter in entries:
            try:
                if adapter.info != descriptor.info:
                    raise RegistryError("invalid_adapter")
                result = adapter.detect(raw)
                if adapter.info != descriptor.info:
                    raise RegistryError("invalid_adapter")
            except RegistryError:
                raise
            except Exception:
                raise RegistryError("detection_failed") from None
            if (not isinstance(result, Detection) or type(result.matched) is not bool
                    or not _text(result.reason)
                    or result.matched and (not isinstance(result.export_version, str) or result.export_version not in descriptor.info.export_versions)
                    or not result.matched and result.export_version is not None):
                raise RegistryError("invalid_detection")
            results.append((descriptor.info, result))
        matches = [(info, result) for info, result in results if result.matched]
        if not matches:
            raise RegistryError("no_match")
        if len(matches) > 1:
            raise RegistryError("ambiguous_detection")
        # Every result was checked against its versioned, validated descriptor.
        info, result = matches[0]
        descriptor = next(item[0] for item in entries if item[0].info.adapter_id == info.adapter_id)
        return SourceMatch(descriptor, result.export_version, result.reason)


def build_registry(*, builtins: tuple[AdapterRegistration, ...] = (),
                   enabled: tuple[PluginSelection, ...] = (),
                   catalog: tuple[PluginCandidate, ...] | None = None) -> SourceRegistry:
    """Build an explicitly enabled registry; never called automatically by imports.

    Entry points must be no-argument factories returning AdapterRegistration.
    Package installation and financial submission are outside this interface.
    """
    if not isinstance(builtins, tuple) or not isinstance(enabled, tuple) or catalog is not None and not isinstance(catalog, tuple):
        raise RegistryError("invalid_configuration")
    entries, providers, ids = [], {}, set()

    def add(registration, plugin=None):
        descriptor = _describe(registration, plugin)
        if descriptor.info.adapter_id in ids:
            raise RegistryError("duplicate_adapter")
        if descriptor.provider.provider_id in providers and providers[descriptor.provider.provider_id] != descriptor.provider:
            raise RegistryError("conflicting_provider")
        ids.add(descriptor.info.adapter_id)
        providers[descriptor.provider.provider_id] = descriptor.provider
        entries.append((descriptor, registration.adapter))

    for registration in builtins:
        add(registration)
    selections, selected_ids, selected_points = [], set(ids), set()
    for selection in enabled:
        distribution, version, point = _selection(selection)
        if selection.adapter_id in selected_ids:
            raise RegistryError("duplicate_adapter")
        if (distribution, point) in selected_points:
            raise RegistryError("ambiguous_plugin")
        selected_ids.add(selection.adapter_id)
        selected_points.add((distribution, point))
        selections.append((selection, (distribution, point), version))
    available = _catalog(discover_plugins() if catalog is None else catalog) if enabled or catalog is not None else {}
    # Validate every selection before any selected package gets imported.
    for selection, key, version in selections:
        if key not in available or available[key].version != version:
            raise RegistryError("unavailable_plugin")
    for selection, key, _ in sorted(selections, key=lambda item: item[0].adapter_id):
        try:
            factory = available[key]._entry_point.load()
            registration = factory()
        except Exception:
            raise RegistryError("plugin_load_failed") from None
        add(registration, selection)
    return SourceRegistry(tuple(sorted(entries, key=lambda item: item[0].info.adapter_id)))

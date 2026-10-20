"""Offline, versioned presentation catalogs with isolated rendering contexts."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache, wraps
from .workspace import CODE_ROOT

import hashlib
import json
from pathlib import Path
import re
from string import Formatter

RESOURCE_DIRECTORY = Path(__file__).with_name("locales")
ALIASES = {"en": "en-CA", "zh-Hant": "zh-TW", "zh-Hans": "zh-CN"}
LEGACY_LOCALE = "zh-TW"
DEFAULT_LOCALE = "en-CA"
SHEET_IDS = {
    "資產總覽": "overview", "幣別持倉": "currency_holdings", "帳戶持倉": "account_holdings",
    "組合分析": "portfolio_analysis", "圖表分析": "charts", "歷史追蹤": "history",
    "資金流": "cash_flows", "持倉資料": "positions", "匯率與說明": "rates_notes",
    "比特幣追蹤": "btc_tracking", "BTC餘額對帳": "btc_reconciliation",
}


class SourceText(str):
    """Verbatim user/source text, excluded from program-message localization."""


class LocalizationError(ValueError):
    """A locale or message cannot be rendered without ambiguity."""


@lru_cache(maxsize=1)
def registry():
    return json.loads((RESOURCE_DIRECTORY / "registry.json").read_text(encoding="utf-8"))


def normalize_locale(value):
    if not isinstance(value, str):
        raise LocalizationError("Locale must be a supported language tag")
    value = value.replace("_", "-")
    aliases = {key.casefold(): target for key, target in ALIASES.items()}
    value = aliases.get(value.casefold(), next((name for name in registry()["locales"] if name.casefold() == value.casefold()), value))
    if value not in registry()["locales"]:
        raise LocalizationError("Unsupported locale; choose " + ", ".join(registry()["locales"]))
    return value


@lru_cache(maxsize=8)
def catalog(locale):
    locale = normalize_locale(locale)
    data = json.loads((RESOURCE_DIRECTORY / (locale + ".json")).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("locale") != locale:
        raise LocalizationError("Invalid translation catalog metadata")
    messages = data.get("messages")
    if not isinstance(messages, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in messages.items()):
        raise LocalizationError("Invalid translation catalog messages")
    return messages


def placeholders(template):
    fields = set()
    for _, name, _, _ in Formatter().parse(template):
        if name is not None:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
                raise LocalizationError("Only named primitive message parameters are supported")
            fields.add(name)
    return fields


def validate_catalogs():
    reference = catalog(DEFAULT_LOCALE)
    for locale in registry()["locales"]:
        translated = catalog(locale)
        if set(translated) != set(reference):
            raise LocalizationError("Incomplete catalog: " + locale)
        for key, source in reference.items():
            if placeholders(translated[key]) != placeholders(source):
                raise LocalizationError("Translation parameters differ: " + locale + ":" + key)
    return {"locales": list(registry()["locales"]), "messages": len(reference)}


@dataclass(frozen=True)
class PresentationContext:
    locale: str = LEGACY_LOCALE

    def __post_init__(self):
        object.__setattr__(self, "locale", normalize_locale(self.locale))

    def message(self, key, **parameters):
        messages = catalog(self.locale)
        if key not in messages:
            raise LocalizationError("Missing translation: " + self.locale + ":" + key)
        template = messages[key]
        if placeholders(template) != set(parameters):
            raise LocalizationError("Message parameters differ: " + key)
        try:
            return template.format_map(parameters)
        except (ValueError, TypeError, KeyError) as exc:
            raise LocalizationError("Cannot format message: " + key) from exc

    def metadata(self):
        data = (RESOURCE_DIRECTORY / (self.locale + ".json")).read_bytes()
        return {"locale": self.locale, "catalog_sha256": hashlib.sha256(data).hexdigest(),
                "catalog_schema_version": 1, "formatting_version": "ledger-display-1",
                "renderer_locale_version": 1, "font": registry()["locales"][self.locale]["font"],
                "font_sha256": hashlib.sha256((CODE_ROOT / "assets/fonts" / registry()["locales"][self.locale]["font"]).read_bytes()).hexdigest()}


_CONTEXT = ContextVar("wealth_ledger_presentation", default=PresentationContext())


def current_context():
    return _CONTEXT.get()


@contextmanager
def presentation_context(locale):
    context = PresentationContext(normalize_locale(locale))
    token = _CONTEXT.set(context)
    try:
        yield context
    finally:
        _CONTEXT.reset(token)


def localized(function):
    """Public render entry points explicitly scope locale, including nested calls."""
    @wraps(function)
    def wrapped(*args, locale=None, **kwargs):
        value = locale
        if value is None and function.__name__ == "verify_workbook" and args:
            value = document_locale(args[0])
        if value is None and function.__name__ == "validate_report_presentation" and len(args) >= 2:
            value = document_locale(Path(args[1]) / "portfolio.ods")
        value = value or current_context().locale
        with presentation_context(value):
            validate_catalogs()
            return function(*args, **kwargs)
    return wrapped


def tr(key, **parameters):
    return current_context().message(key, **parameters)


class LabelCatalog(dict):
    """Keep stable keys at import time; resolve display values within each render."""
    def __getitem__(self, key):
        return tr(super().__getitem__(key))

    def get(self, key, default=None):
        return self[key] if key in self else default

    def items(self):
        return ((key, self[key]) for key in self)

    def values(self):
        return (self[key] for key in self)


def sheet_title(identifier):
    identifier = SHEET_IDS.get(identifier, identifier)
    source = next((name for name, key in SHEET_IDS.items() if key == identifier), None)
    if source is None:
        return identifier
    key = "message." + hashlib.sha256(source.encode()).hexdigest()[:12]
    return tr(key)


@lru_cache(maxsize=1)
def legacy_catalog():
    data = json.loads((RESOURCE_DIRECTORY / "legacy.json").read_text(encoding="utf-8"))
    return data["messages"]


@lru_cache(maxsize=1)
def legacy_patterns():
    patterns = []
    for source, key in legacy_catalog().items():
        if "{value" not in source:
            continue
        parts, names, literal_size = [], [], 0
        for literal, name, _, _ in Formatter().parse(source):
            parts.append(re.escape(literal))
            literal_size += len(literal)
            if name is not None:
                parts.append("(?P<" + name + ">.*?)")
                names.append(name)
        if literal_size:
            patterns.append((literal_size, re.compile("".join(parts), re.DOTALL), key, names))
    return sorted(patterns, key=lambda item: -item[0])


def legacy_text(value, *, depth=0):
    """Render known historic program text; never mutate saved source evidence.

    Unknown user/source text is retained. This is a closed, versioned mapping,
    not a translator, and it performs no network or model calls.
    """
    if isinstance(value, SourceText) or not isinstance(value, str) or depth > 8:
        return value
    key = legacy_catalog().get(value)
    if key is not None:
        return tr(key)
    country = re.fullmatch(r"(.+)（([A-Z]{2})）", value)
    if country and country.group(1) in legacy_catalog():
        return legacy_text(country.group(1)) + (" (" if current_context().locale == "en-CA" else "（") + country.group(2) + (")" if current_context().locale == "en-CA" else "）")
    if value == "CRYPTO:BTC 等值" and current_context().locale != LEGACY_LOCALE:
        return "CRYPTO:BTC-equivalent"
    if value.startswith("BTC 等值 / ") and current_context().locale != LEGACY_LOCALE:
        return legacy_text("BTC 等值") + value[len("BTC 等值"):]
    for _, pattern, key, names in legacy_patterns():
        match = pattern.fullmatch(value)
        if match:
            parameters = {name: legacy_text(match.group(name), depth=depth+1) for name in names}
            # Historic templates already contain their formatted values.
            template = catalog(current_context().locale)[key]
            formatted = []
            for literal, name, _, _ in Formatter().parse(template):
                formatted.append(literal)
                if name is not None:
                    formatted.append(str(parameters[name]))
            return "".join(formatted)
    return value


def display_payload(payload):
    """Copy presentation fields while preserving all original financial evidence."""
    from copy import deepcopy
    result = deepcopy(payload)
    for key in ("issues",):
        for issue in result.get(key, []):
            if isinstance(issue, dict) and "message" in issue:
                issue["message"] = legacy_text(issue["message"])
    result["findings"] = [legacy_text(text) for text in result.get("findings", [])]
    for collection in ("accounts", "positions", "cash_rows", "securities", "instrument_types"):
        for row in result.get(collection, []):
            is_crypto = row.get("security_type") == "CRYPTO" or row.get("source_provider") == "bullbitcoin"
            if is_crypto:
                for key in ("account_type", "account_label"):
                    if key in row:
                        row[key] = legacy_text(row[key])
            if not is_crypto and collection != "instrument_types":
                for key in ("account_label", "name", "label"):
                    if isinstance(row.get(key), str):
                        row[key] = SourceText(row[key])
            if collection == "instrument_types":
                for key in ("name", "label", "type", "security_type"):
                    if key in row:
                        row[key] = legacy_text(row[key])
    largest = result.get("concentration", {}).get("largest")
    if largest and largest.get("symbol") in {row["symbol"] for row in payload.get("positions", []) if row.get("security_type") == "CRYPTO"}:
        largest["symbol"] = legacy_text(largest["symbol"])
    for collection in ("companies", "top20", "top20_components"):
        for row in result.get("lookthrough", {}).get(collection, []):
            if isinstance(row.get("name"), str):
                row["name"] = SourceText(row["name"])
    for row in result.get("cash_flows", []):
        for key in ("note", "source", "description"):
            if isinstance(row.get(key), str):
                row[key] = SourceText(row[key])
    classification = result.get("lookthrough", {}).get("classification", {})
    region_ids = {"北美洲": "north_america", "拉丁美洲及加勒比海": "latin_america_caribbean", "歐洲": "europe", "亞洲": "asia", "中東": "middle_east", "非洲": "africa", "大洋洲": "oceania"}
    if current_context().locale != LEGACY_LOCALE:
        for row in classification.get("dimensions", {}).get("region", {}).get("rows", []):
            row["key"] = region_ids.get(row["key"], row["key"])
        for group in classification.get("root_groups", []):
            if group.get("dimension") == "region":
                group["key"] = region_ids.get(group["key"], group["key"])
        for component in classification.get("components", []):
            assignment = component.get("assignments", {}).get("region", {})
            assignment["value"] = region_ids.get(assignment.get("value"), assignment.get("value"))
    for summary in classification.get("dimensions", {}).values():
        for row in summary.get("rows", []):
            row["name"] = legacy_text(row["name"])
    if result.get("reporting", {}).get("offline_language_edition") and result.get("lookthrough"):
        result["lookthrough"]["mode"] = "frozen_replay"
    crypto = result.get("crypto") or {}
    for row in crypto.get("wallet", {}).get("events", []):
        for key in ("source", "reference", "reason"):
            if isinstance(row.get(key), str):
                row[key] = SourceText(row[key])
    for record in (crypto.get("assumptions") or {}, crypto.get("opening") or {}):
        for key in ("basis", "btc_basis", "cad_basis", "confirmed_by"):
            if isinstance(record.get(key), str):
                record[key] = SourceText(record[key])
    for row in crypto.get("wallet", {}).get("reconciliations", []):
        row["status_label"] = legacy_text(row["status_label"])
    return result


def font_path():
    return CODE_ROOT / "assets/fonts" / registry()["locales"][current_context().locale]["font"]


def font_family():
    return registry()["locales"][current_context().locale]["font_family"]


def font_package_path():
    return "Fonts/" + registry()["locales"][current_context().locale]["font"]


def font_license_path():
    return CODE_ROOT / "assets/fonts" / registry()["locales"][current_context().locale]["font_license"]


def document_locale(path):
    """Read a generated ODS locale; absent legacy metadata remains compatible."""
    import zipfile
    import xml.etree.ElementTree as ET
    path = Path(path)
    if not path.is_file():
        return None
    with zipfile.ZipFile(path) as archive:
        if "meta.xml" not in archive.namelist():
            return None
        info = archive.getinfo("meta.xml")
        if info.file_size > 65536:
            raise LocalizationError("Oversized document language metadata")
        root = ET.fromstring(archive.read(info))
    namespace = "urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
    nodes = [node for node in root.iter() if node.tag == "{"+namespace+"}user-defined" and node.get("{"+namespace+"}name") == "report_locale"]
    if len(nodes) > 1:
        raise LocalizationError("Conflicting document locale metadata")
    return normalize_locale(nodes[0].text) if nodes else None

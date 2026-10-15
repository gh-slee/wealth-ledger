"""Explicit local reporting choices, kept out of source control."""
from pathlib import Path
import tomllib

BTC_COST_POLICIES = ("actual_only", "bull_average_proxy")


def btc_cost_policy(project, override=None):
    """New projects opt out of proxy costs; an explicit CLI choice takes priority."""
    value = override
    if value is None:
        path = Path(project) / "config/local.toml"
        if path.exists():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
                reporting = data.get("reporting", {})
                if not isinstance(reporting, dict):
                    raise ValueError("The reporting configuration must be a table")
                value = reporting.get("btc_cost_policy", "actual_only")
            except tomllib.TOMLDecodeError as exc:
                raise ValueError("Invalid private config/local.toml") from exc
        else:
            value = "actual_only"
    if value not in BTC_COST_POLICIES:
        raise ValueError("btc_cost_policy must be actual_only or bull_average_proxy")
    return value


def report_locale(project, override=None):
    """Resolve presentation language without writing or reading host locale."""
    from .i18n import normalize_locale, DEFAULT_LOCALE, LEGACY_LOCALE
    if override is not None:
        return normalize_locale(override)
    project = Path(project)
    path = project / "config/local.toml"
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ValueError("Invalid private config/local.toml") from exc
        reporting = data.get("reporting", {})
        if not isinstance(reporting, dict):
            raise ValueError("The reporting configuration must be a table")
        if "locale" in reporting:
            return normalize_locale(reporting["locale"])
    legacy = (project / "data/db/portfolio.sqlite3").exists() or (project / "reports/latest.json").exists()
    return LEGACY_LOCALE if legacy else DEFAULT_LOCALE


def ensure_report_locale_setting(project):
    """Persist the project default under the caller's mutation lock, once only."""
    import os
    import re
    project = Path(project)
    path = project / "config/local.toml"
    value = report_locale(project)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text:
        parsed = tomllib.loads(text)
        if "locale" in parsed.get("reporting", {}):
            return value
    header = re.search(r"(?m)^\[reporting\][ \t]*(?:#.*)?$", text)
    entry = '\nlocale = "' + value + '"\n'
    if header:
        text = text[:header.end()] + entry + text[header.end():]
    else:
        text = text.rstrip() + "\n\n[reporting]" + entry
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("local.toml.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(text.lstrip("\n"))
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return value

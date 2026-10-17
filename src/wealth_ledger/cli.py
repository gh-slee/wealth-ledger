"""Localized everyday CLI surfaces; machine keys and ledger inputs stay stable."""
from __future__ import annotations

import argparse
from functools import partial
import sys

from .i18n import legacy_text, presentation_context, normalize_locale, LocalizationError, DEFAULT_LOCALE
from .settings import report_locale
from .workspace import workspace_from_args


def selected_locale(project, argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    override = None
    for index, value in enumerate(argv):
        if value == "--":
            break
        if value.startswith("--locale="):
            override = value.split("=", 1)[1]
        elif value == "--locale":
            if index + 1 == len(argv):
                raise LocalizationError("argument --locale: expected one argument")
            override = argv[index + 1]
    return report_locale(project, override)


class LocalizedHelpFormatter(argparse.HelpFormatter):
    def __init__(self, *args, locale, **kwargs):
        self.locale = locale
        super().__init__(*args, **kwargs)

    def _format_usage(self, usage, actions, groups, prefix):
        with presentation_context(self.locale):
            return super()._format_usage(usage, actions, groups, prefix or legacy_text("usage: "))


class LedgerArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, locale, **kwargs):
        self.locale = normalize_locale(locale)
        kwargs.setdefault("formatter_class", partial(LocalizedHelpFormatter, locale=self.locale))
        with presentation_context(self.locale):
            if kwargs.get("description"):
                kwargs["description"] = legacy_text(kwargs["description"])
            super().__init__(*args, **kwargs)
            self._positionals.title = legacy_text("positional arguments")
            self._optionals.title = legacy_text("options")
        self.add_argument("--workspace", default=argparse.SUPPRESS,
                          help="Existing private portfolio directory; omit for legacy checkout-local use")
        self.add_argument("--locale", default=argparse.SUPPRESS,
                          help="Choose en-CA, zh-TW or zh-CN; aliases en, zh-Hant and zh-Hans are accepted")

    def add_argument(self, *args, **kwargs):
        with presentation_context(self.locale):
            if isinstance(kwargs.get("help"), str):
                kwargs["help"] = legacy_text(kwargs["help"])
            return super().add_argument(*args, **kwargs)

    def add_subparsers(self, **kwargs):
        kwargs.setdefault("parser_class", partial(type(self), locale=self.locale))
        return super().add_subparsers(**kwargs)

    def error(self, message):
        with presentation_context(self.locale):
            self.print_usage(sys.stderr)
            self.exit(2, self.prog + ": " + legacy_text("error") + ": " + legacy_text(message) + "\n")


def make_parser(project, **kwargs):
    workspace = workspace_from_args(project)
    parser = LedgerArgumentParser(locale=selected_locale(workspace.workspace_root), **kwargs)
    parser.workspace = workspace
    return parser


def run_main(function, project):
    try:
        return function()
    except (ValueError, OSError) as exc:
        # Errors are rendered only after the financial operation returns.
        try:
            locale = selected_locale(workspace_from_args(project).workspace_root)
        except ValueError:
            locale = DEFAULT_LOCALE
        with presentation_context(locale):
            text = legacy_text(str(exc))
            print(legacy_text("error") + ": " + text, file=sys.stderr)
        return 2

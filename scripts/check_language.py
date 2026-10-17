#!/usr/bin/env python3
"""Check canonical public Markdown and Python comments/docstrings for CJK regressions."""
from __future__ import annotations

import argparse
import ast
import io
import json
from pathlib import Path
import re
import sys
import tokenize

from check_publication import path_allowed

CJK = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\U00020000-\U000323af]')


class LanguageError(RuntimeError):
    """The bounded source check could not complete."""


def check_file(path: str, text: str) -> list[dict]:
    """Allow translated string values while checking explanatory text and names."""
    issues = []

    def record(line: int, kind: str) -> None:
        issues.append({'path': path, 'line': line, 'kind': kind,
                       'reason': 'Canonical documentation, comments, docstrings and identifiers use English.'})

    if path.endswith('.md'):
        for line, value in enumerate(text.splitlines(), 1):
            if CJK.search(value):
                record(line, 'markdown')
        return issues
    try:
        tree = ast.parse(text, filename=path)
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type in {tokenize.COMMENT, tokenize.NAME} and CJK.search(token.string):
                record(token.start[0], 'comment' if token.type == tokenize.COMMENT else 'identifier')
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                value = ast.get_docstring(node, clean=False)
                if value and CJK.search(value):
                    record(node.body[0].lineno, 'docstring')
    except (SyntaxError, tokenize.TokenError, IndentationError) as exc:
        raise LanguageError('Cannot parse public Python source: ' + path) from exc
    return issues


def scan(root: Path) -> dict:
    """Read only allowlisted Markdown/Python, never private guidance or data."""
    files = []
    violations = []
    for candidate in sorted(root.rglob('*')):
        rel = candidate.relative_to(root).as_posix()
        if candidate.suffix not in {'.md', '.py'} or not path_allowed(rel):
            continue
        if candidate.is_symlink():
            raise LanguageError('Refusing a public source symlink: ' + rel)
        if not candidate.is_file():
            continue
        files.append(rel)
        violations.extend(check_file(rel, candidate.read_text(encoding='utf-8')))
    if not files:
        raise LanguageError('No allowlisted Markdown or Python files found.')
    return {'passed': not violations, 'files_checked': len(files),
            'violations': violations,
            'scope': 'Allowlisted public Markdown; Python comments, docstrings and identifiers.',
            'exceptions': 'Translation catalogs, runtime/legacy string values and localization test data are outside this bounded check.',
            'limitations': 'Detects CJK regressions; it cannot prove that prose is English or technically correct.'}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        result = scan(args.root)
    except (LanguageError, OSError, UnicodeError) as exc:
        print('Language check could not complete: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

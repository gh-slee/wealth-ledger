#!/usr/bin/env python3
"""Check PR Markdown structure against the canonical template, without network calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

TEMPLATE = Path(__file__).resolve().parents[1] / '.github/pull_request_template.md'
STATUS = re.compile(r'^[-*] (?:PASS|FAIL|NOT RUN)(?:\s*[:(])')
CI_STATUS = re.compile(r'^[-*] (?:PASS|FAIL|NOT RUN|PENDING)(?:\s*[:(])')


def visible_lines(value: str) -> list[str]:
    """Headings in HTML comments or fenced examples do not satisfy the format."""
    result = []
    fence = None
    for line in re.sub(r'<!--.*?(?:-->|\Z)', '', value, flags=re.S).splitlines():
        mark = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if mark:
            token = mark[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[mark.end():].strip():
                fence = None
            continue
        if fence is None:
            result.append(line)
    return result


def sections(lines: list[str], level: int) -> list[tuple[str, list[str]]]:
    pattern = re.compile(r'^' + '#' * level + r' ([^#].*?)\s*$')
    starts = [(i, match[1]) for i, line in enumerate(lines) if (match := pattern.match(line))]
    return [(name, lines[index + 1:starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)])
            for pos, (index, name) in enumerate(starts)]


def validate(body: str, template: str) -> list[str]:
    """Validate shape only; reviewers must verify claims, coverage and permissions."""
    required = re.findall(r'<!-- pr-standard: required -->\s*\n## ([^\n]+)', template)
    evidence = re.findall(r'<!-- pr-standard: evidence -->\s*\n### ([^\n]+)', template)
    order = [name for name, _ in sections(visible_lines(template), 2)]
    if (len(required) != 3 or len(set(required)) != 3 or len(evidence) != 4 or
            len(set(evidence)) != 4 or len(set(order)) != len(order) or required != order[:3]):
        raise ValueError('Canonical PR template has incomplete or duplicate requirements')
    groups = sections(visible_lines(body), 2)
    names = [name for name, _ in groups]
    errors = []
    if len(set(names)) != len(names):
        errors.append('Use each PR section once')
    if any(name not in order for name in names):
        errors.append('Use the canonical second-level section headings')
    if any(name not in names for name in required):
        errors.append('Include all three required PR sections')
    if all(name in order for name in names) and names != sorted(names, key=order.index):
        errors.append('Keep PR sections in canonical order')
    content = dict(groups)
    summary = [line for line in content.get(required[0], []) if line.strip()]
    bullets = [line for line in summary if re.match(r'^[-*] ', line)]
    if not summary or re.match(r'^[-*] ', summary[0]) or not 2 <= len(bullets) <= 6:
        errors.append('Start Change Summary with a sentence and 2-6 focused bullets')
    files = [line for line in content.get(required[1], []) if re.match(r'^[-*] ', line)]
    if not files or any(not re.search(r'`[^`]+`', line) or
                        not re.sub(r'`[^`]+`|^[-*] ', '', line).strip(' :-') for line in files):
        errors.append('Describe meaningful files/modules in bullets with backtick paths')
    categories = sections(content.get(required[2], []), 3)
    if [name for name, _ in categories] != evidence:
        errors.append('Separate all four Testing & Evidence categories in canonical order')
    if any(not any((CI_STATUS if name == evidence[1] else STATUS).match(line) for line in lines)
           for name, lines in categories):
        errors.append('Give each evidence category a PASS, FAIL or NOT RUN bullet; CI may be PENDING')
    for name, lines in groups:
        if name not in required and not any(line.strip() for line in lines):
            errors.append('Remove unused empty optional sections')
    return errors


def check(body_file: Path, template_file: Path = TEMPLATE) -> dict:
    errors = validate(body_file.read_text(encoding='utf-8'), template_file.read_text(encoding='utf-8'))
    return {'passed': not errors, 'violations': errors,
            'limitations': 'Structure only; no proof of factual accuracy, test results, independent review, risk coverage or publication consent.'}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--body-file', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = check(args.body_file)
    except (OSError, ValueError, UnicodeError):
        print(json.dumps({'passed': False, 'error': 'Unable to read the PR body or canonical template'}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Opt in to the repository-local privacy hooks; never change global Git settings."""
from pathlib import Path
import subprocess

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), 'config', '--local', 'core.hooksPath', '.githooks'], check=True)
    for hook in ('pre-commit', 'pre-push'):
        path = root / '.githooks' / hook
        path.chmod(path.stat().st_mode | 0o111)
    print('Enabled repository-local privacy hooks; other repositories are unchanged.')

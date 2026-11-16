#!/usr/bin/env python3
"""The version the release workflow publishes (D35), written into every file that carries it.

Run from the repo root by .github/workflows/release.yml: prints the version to release. If the version in
pyproject.toml has no tag yet (it was bumped by hand in a PR, for a minor or major), that version is released
as is; otherwise the patch is bumped in pyproject.toml, uv.lock, the plugin's plugin.json and the marketplace.
"""

import re
import subprocess
import sys
from pathlib import Path

# (file, pattern whose group 1 is followed by the version); each must match exactly once
FILES = (
    ("pyproject.toml", r'(?m)^(version = ")[^"]+'),
    ("uv.lock", r'(name = "atr"\nversion = ")[^"]+'),
    ("extensions/claude-code/.claude-plugin/plugin.json", r'(\n  "version": ")[^"]+'),
    (".claude-plugin/marketplace.json", r'("version": ")[^"]+'),
)


def current(root):
    return re.search(FILES[0][1], (root / FILES[0][0]).read_text()).group(0).split('"')[1]


def next_version(version, tags):
    """The version to release: `version` itself while it has no tag, else its patch bumped."""
    if f"v{version}" not in tags:
        return version
    major, minor, patch = (int(x) for x in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def write(root, version):
    for name, pattern in FILES:
        path = root / name
        text, n = re.subn(pattern, lambda m: m.group(1) + version, path.read_text(), count=1)
        if n != 1:
            raise SystemExit(f"no version found in {name}")
        path.write_text(text)


def main(root=Path()):
    tags = set(subprocess.run(["git", "tag", "--list"], capture_output=True, text=True, check=True).stdout.split())
    version = next_version(current(root), tags)
    write(root, version)
    print(version)


if __name__ == "__main__":
    sys.exit(main())

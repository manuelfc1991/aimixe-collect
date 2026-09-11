"""Create a GitHub release and attach the Windows bundle, with the GitHub REST API (standard library only).

    GITHUB_TOKEN=ghp_... python3 tools/publish_release.py [--tag v0.1.0] [--asset dist/....zip]

The token needs the ``repo`` scope (classic) or "Contents: read and write" (fine-grained).
If the release for the tag already exists, the asset is added to it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com"


def call(token: str, method: str, url: str, data: bytes | None = None, ctype: str = "application/json") -> dict:
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "Content-Type": ctype, "User-Agent": "aimixe-collect-release"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"GitHub API {exc.code} for {method} {url}: {detail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="Calnic-Solutions/aimixe-tools-ours")
    ap.add_argument("--tag", default="v0.1.0")
    ap.add_argument("--asset", default=None, help="zip to attach (default: newest dist/aimixe-collect-windows-*.zip)")
    ns = ap.parse_args()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("Set GITHUB_TOKEN (repo scope) in the environment.", file=sys.stderr)
        return 50
    asset = Path(ns.asset) if ns.asset else max((ROOT / "dist").glob("aimixe-collect-windows-*.zip"), key=lambda p: p.stat().st_mtime)
    sha = hashlib.sha256(asset.read_bytes()).hexdigest()
    notes = (
        "AImixE Data Collection Module, first release. All five phases of collect/PLAN.md.\n\n"
        "**Portable Windows bundle** (attached): unzip anywhere, double-click `aimixe-ui.cmd` for the web "
        "interface or run `aimixe collect` from a terminal in the folder. No Python installation needed; "
        "bundles Python 3.13.7 embeddable from python.org. Assembled on Linux and not yet run on Windows; "
        "please report any failure with the exact message. SmartScreen may warn on first launch of the unsigned .cmd.\n\n"
        f"SHA-256 of the zip: `{sha}`\n\n"
        "**Linux / macOS**: clone the repository and run `collect/bin/aimixe collect` (Python 3.11+, nothing else). "
        "See collect/README.md."
    )
    # existing release for the tag?
    try:
        rel = call(token, "GET", f"{API}/repos/{ns.repo}/releases/tags/{ns.tag}")
    except SystemExit:
        rel = call(token, "POST", f"{API}/repos/{ns.repo}/releases", json.dumps({
            "tag_name": ns.tag, "name": f"aimixe collect {ns.tag.lstrip('v')}", "body": notes, "draft": False}).encode())
        print("release created:", rel["html_url"])
    else:
        print("release exists:", rel["html_url"])
    for a in rel.get("assets", []):
        if a["name"] == asset.name:
            print("asset already attached; deleting the old one first")
            call(token, "DELETE", a["url"])
    upload = rel["upload_url"].split("{")[0] + "?" + urllib.parse.urlencode({"name": asset.name})
    res = call(token, "POST", upload, asset.read_bytes(), ctype="application/zip")
    print("asset uploaded:", res.get("browser_download_url"))
    print("sha256:", sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())

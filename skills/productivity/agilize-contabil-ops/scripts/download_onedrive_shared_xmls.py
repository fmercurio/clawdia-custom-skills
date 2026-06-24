#!/usr/bin/env python3
"""Download XML files from a public OneDrive shared folder via preview network responses.

This is useful when direct `onedrive.live.com/download?resid=...` URLs return 403 or HTML,
but the OneDrive web preview can load the actual XML through a temporary tempauth URL.

Requires: playwright (`python -m playwright install chromium` if browsers are missing).
"""
from __future__ import annotations

import argparse
import os
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path
from playwright.sync_api import sync_playwright


def safe_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._() \-]+", "_", name).strip(" .")
    return safe or "download.xml"


def is_valid_nfse_xml(data: bytes) -> bool:
    """Validate that downloaded bytes look like an emitted Brazilian NFS-e XML."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return False
    root_tag = root.tag or ""
    ns = root_tag.split("}", 1)[0].strip("{") if root_tag.startswith("{") else ""
    if ns not in {"http://www.sped.fazenda.gov.br/nfse", "http://www.abrasf.org.br/nfse.xsd"}:
        return False
    # If cStat exists, emitted/authorized is cStat=100. Some provider XMLs omit it.
    cstats = [el.text.strip() for el in root.iter() if el.tag.endswith("cStat") and el.text]
    return not cstats or "100" in cstats


def ensure_private_dir(path: Path) -> Path:
    path = path.expanduser()
    if path.exists() and path.is_symlink():
        raise OSError(f"output directory must not be a symlink: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, stat.S_IRWXU)
    return path


def write_secure_bytes(path: Path, data: bytes) -> None:
    path = path.expanduser()
    ensure_private_dir(path.parent)
    if path.exists() and path.is_symlink():
        raise OSError(f"refusing to overwrite symlink: {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def main() -> int:
    ap = argparse.ArgumentParser(description="Download XMLs from a public OneDrive shared folder")
    ap.add_argument("url", help="OneDrive shared folder URL")
    ap.add_argument("--subfolder", help="Visible subfolder name to enter, e.g. 2026-06")
    ap.add_argument("--name-regex", default=r"(?i)\.xml$", help="Visible filename regex to download")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--timeout-ms", type=int, default=60000)
    args = ap.parse_args()

    out = Path(args.out).expanduser()
    out = ensure_private_dir(out)
    name_re = re.compile(args.name_regex)
    saved: list[tuple[str, int]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        responses = []

        def on_response(resp):
            if "/download.aspx?UniqueId=" in resp.url:
                responses.append(resp)

        page.on("response", on_response)
        page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout_ms)

        if args.subfolder:
            page.wait_for_selector(f"text={args.subfolder}", timeout=args.timeout_ms)
            page.get_by_text(args.subfolder, exact=True).dblclick()

        page.wait_for_timeout(1500)
        links = page.get_by_role("link").all()
        names = []
        for link in links:
            try:
                name = (link.inner_text() or "").strip()
            except Exception:
                continue
            if name and name_re.search(name):
                names.append(name)

        # Preserve page order while removing duplicates.
        names = list(dict.fromkeys(names))
        if not names:
            raise SystemExit("No matching XML links found")

        for name in names:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            before = len(responses)
            page.get_by_role("link", name=name).click(timeout=args.timeout_ms)
            page.wait_for_timeout(2000)

            body = None
            for resp in reversed(responses[before:] or responses):
                try:
                    ctype = resp.headers.get("content-type", "")
                    data = resp.body()
                    if resp.status == 200 and "xml" in ctype.lower() and data.startswith(b"<?xml") and is_valid_nfse_xml(data):
                        body = data
                        break
                except Exception:
                    continue

            if body is None:
                raise RuntimeError(f"Could not capture XML body for {name}")

            path = out / safe_name(name)
            write_secure_bytes(path, body)
            saved.append((str(path), len(body)))

        browser.close()

    for path, size in saved:
        print(f"{size}\t{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

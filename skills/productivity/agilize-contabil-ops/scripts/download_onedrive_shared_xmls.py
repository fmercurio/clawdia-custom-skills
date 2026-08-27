#!/usr/bin/env python3
"""Download XML files from a public OneDrive shared folder via preview network responses.

This is useful when direct `onedrive.live.com/download?resid=...` URLs return 403 or HTML,
but the OneDrive web preview can load the actual XML through a temporary tempauth URL.

Requires: playwright (`python -m playwright install chromium` if browsers are missing).
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import re
import secrets
import socket
import stat
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from playwright.sync_api import Error as PlaywrightError, sync_playwright

EXPECTED_ONEDRIVE_DOWNLOAD_HOST = "my.microsoftpersonalcontent.com"
MAX_XML_FILES = 100
MAX_XML_BYTES = 10 * 1024 * 1024
MAX_TOTAL_XML_BYTES = 100 * 1024 * 1024
TRUSTED_ONEDRIVE_HOSTS = {
    "1drv.ms",
    "onedrive.live.com",
    "onedrive.com",
    "sharepoint.com",
    "sharepointonline.com",
    "microsoft.com",
    "microsoftonline.com",
    "microsoftpersonalcontent.com",
    "office.net",
}


def _is_trusted_onedrive_host(host: str) -> bool:
    host = host.rstrip(".").lower()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in TRUSTED_ONEDRIVE_HOSTS)


def validate_outbound_url(url: str, *, require_trusted_host: bool = False) -> str:
    parsed = urllib.parse.urlsplit((url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("OneDrive requests must use HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("OneDrive URL must not contain credentials")
    host = parsed.hostname.rstrip(".").lower()
    if require_trusted_host and not _is_trusted_onedrive_host(host):
        raise ValueError("URL must use a trusted OneDrive or Microsoft host")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as exc:
        raise ValueError("OneDrive host could not be resolved safely") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("OneDrive host must resolve only to public addresses")
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def validate_shared_url(url: str) -> str:
    parsed = urllib.parse.urlsplit((url or "").strip())
    if parsed.scheme != "https":
        raise ValueError("OneDrive shared URL must use HTTPS")
    if not _is_trusted_onedrive_host(parsed.hostname or ""):
        raise ValueError("URL must use a trusted OneDrive or Microsoft host")
    return validate_outbound_url(url, require_trusted_host=True)


def validate_browser_request(url: str) -> str:
    """Validate every browser request against the Microsoft host boundary."""
    return validate_outbound_url(url, require_trusted_host=True)


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


def _canonical_system_temp_alias(path: Path) -> Path:
    """Normalize only macOS's built-in /var and /tmp aliases before fd traversal."""
    candidate = path.expanduser()
    for alias, target in ((Path("/var"), Path("/private/var")), (Path("/tmp"), Path("/private/tmp"))):
        if candidate.is_absolute() and (candidate == alias or alias in candidate.parents):
            try:
                if alias.is_symlink() and alias.resolve(strict=True) == target:
                    return target.joinpath(*candidate.relative_to(alias).parts)
            except OSError:
                pass
            break
    return candidate


def _open_private_dir(path: Path) -> int:
    """Create and pin every output-directory component without following links."""
    candidate = _canonical_system_temp_alias(path)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if candidate.is_absolute():
        descriptor = os.open("/", flags)
        parts = candidate.parts[1:]
    else:
        descriptor = os.open(".", flags)
        parts = candidate.parts
    try:
        for part in parts:
            try:
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
            except OSError as exc:
                raise OSError(f"output directory must not contain symlinks: {path}") from exc
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise OSError(f"output directory must be owner-owned: {path}")
        os.fchmod(descriptor, stat.S_IRWXU)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def ensure_private_dir(path: Path) -> Path:
    descriptor = _open_private_dir(path)
    os.close(descriptor)
    return path.expanduser()


def write_secure_bytes(path: Path, data: bytes) -> None:
    destination = path.expanduser()
    directory_fd = _open_private_dir(destination.parent)
    temporary: str | None = None
    try:
        try:
            existing = os.stat(destination.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISREG(existing.st_mode):
                raise OSError(f"refusing to overwrite non-regular output: {destination}")
            raise FileExistsError(f"refusing to overwrite existing XML output: {destination}")
        temporary = f".{destination.name}.{secrets.token_hex(16)}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        try:
            offset = 0
            while offset < len(data):
                offset += os.write(descriptor, data[offset:])
            os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, destination.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        temporary = None
        os.fsync(directory_fd)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def is_expected_onedrive_download_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and host == EXPECTED_ONEDRIVE_DOWNLOAD_HOST
        and parsed.path.endswith("/download.aspx")
        and "UniqueId=" in parsed.query
    )


def extract_valid_xml_body(responses, *, max_bytes: int | None = None) -> bytes | None:
    max_bytes = MAX_XML_BYTES if max_bytes is None else max_bytes
    for resp in reversed(responses):
        try:
            ctype = resp.headers.get("content-type", "")
            declared_length = resp.headers.get("content-length")
            if not declared_length:
                continue
            if int(declared_length) < 0 or int(declared_length) > max_bytes:
                continue
            data = resp.body()
            if len(data) > max_bytes:
                continue
            if resp.status == 200 and "xml" in ctype.lower() and data.startswith(b"<?xml") and is_valid_nfse_xml(data):
                return data
        except (PlaywrightError, ValueError, TypeError, OSError):
            continue
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Treat any download redirect as a failed origin-bound transfer."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_valid_xml_body(download_url: str, *, max_bytes: int | None = None, timeout: float = 60) -> bytes | None:
    """Fetch a browser-discovered temporary URL with a transport-enforced cap."""
    max_bytes = MAX_XML_BYTES if max_bytes is None else max_bytes
    if not is_expected_onedrive_download_url(download_url):
        return None
    try:
        validate_outbound_url(download_url, require_trusted_host=True)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        request = urllib.request.Request(download_url, headers={"User-Agent": "onedrive-xml-download/1.0"})
        with opener.open(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            declared_length = response.headers.get("content-length")
            if response.status != 200 or "xml" not in content_type.lower() or not declared_length:
                return None
            if int(declared_length) < 0 or int(declared_length) > max_bytes:
                return None
            data = response.read(max_bytes + 1)
    except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError):
        return None
    if len(data) > max_bytes or not data.startswith(b"<?xml") or not is_valid_nfse_xml(data):
        return None
    return data


def output_path_for_name(out: Path, name: str, seen_names: set[str]) -> Path:
    filename = safe_name(name)
    if filename in seen_names:
        raise RuntimeError(f"Sanitized XML filename collision: {filename}")
    seen_names.add(filename)
    path = out / filename
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing XML output: {path}")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Download XMLs from a public OneDrive shared folder")
    ap.add_argument("url", help="OneDrive shared folder URL")
    ap.add_argument("--subfolder", help="Visible subfolder name to enter, e.g. 2026-06")
    ap.add_argument("--name-regex", default=r"(?i)\.xml$", help="Visible filename regex to download")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--timeout-ms", type=int, default=60000)
    args = ap.parse_args()

    shared_url = validate_shared_url(args.url)

    out = Path(args.out).expanduser()
    out = ensure_private_dir(out)
    name_re = re.compile(args.name_regex)
    saved: list[tuple[str, int]] = []
    seen_output_names: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        download_urls: list[str] = []

        def guard_request(route, request):
            try:
                validate_browser_request(request.url)
            except ValueError:
                route.abort()
                return
            if is_expected_onedrive_download_url(request.url):
                download_urls.append(request.url)
                route.abort()
                return
            route.continue_()
        page.route("**/*", guard_request)
        page.goto(shared_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        validate_outbound_url(page.url, require_trusted_host=True)

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
        if len(names) > MAX_XML_FILES:
            raise RuntimeError(f"refusing {len(names)} XML files; limit is {MAX_XML_FILES}")

        total_bytes = 0
        for name in names:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            before = len(download_urls)
            try:
                page.get_by_role("link", name=name).click(timeout=args.timeout_ms)
            except PlaywrightError:
                # The deliberate abort of a temporary download can surface as a
                # click failure after the route has already captured its URL.
                if len(download_urls) == before:
                    raise
            page.wait_for_timeout(2000)

            body = None
            for download_url in reversed(download_urls[before:]):
                body = fetch_valid_xml_body(download_url, timeout=args.timeout_ms / 1000)
                if body is not None:
                    break

            if body is None:
                raise RuntimeError(f"Could not securely fetch XML body for {name}")
            if total_bytes + len(body) > MAX_TOTAL_XML_BYTES:
                raise RuntimeError(f"XML download exceeds the {MAX_TOTAL_XML_BYTES}-byte total limit")

            path = output_path_for_name(out, name, seen_output_names)
            write_secure_bytes(path, body)
            saved.append((str(path), len(body)))
            total_bytes += len(body)

        browser.close()

    for path, size in saved:
        print(f"{size}\t{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

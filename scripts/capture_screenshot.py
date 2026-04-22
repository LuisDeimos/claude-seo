#!/usr/bin/env python3
"""
Capture screenshots of web pages.

Primary engine: Playwright (accurate viewport, DPR, network idle).
Fallback engine: headless google-chrome/chromium via subprocess — used when
Playwright is not installed so the SEO audit pipeline keeps working with a
system-wide Chrome instead of blocking on a ~200 MB Playwright download.

Usage:
    python capture_screenshot.py https://example.com
    python capture_screenshot.py https://example.com --viewport mobile
    python capture_screenshot.py https://example.com --output screenshots/
"""

import argparse
import ipaddress
import os
import shutil
import socket
import subprocess
import sys
from urllib.parse import ParseResult, urlparse

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    sync_playwright = None
    # Placeholder so `except PlaywrightTimeout` in capture_screenshot() does
    # not raise NameError when Playwright is missing.
    class PlaywrightTimeout(Exception):
        pass


def _find_chrome_binary() -> str:
    """Return path to a system chrome/chromium binary, or '' if none exists."""
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        path = shutil.which(name)
        if path:
            return path
    return ""


VIEWPORTS = {
    "desktop": {"width": 1920, "height": 1080},
    "laptop": {"width": 1366, "height": 768},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 375, "height": 812},
}


def normalize_url(url: str) -> tuple[str, ParseResult]:
    """Normalize URL and return (url, parsed_url)."""
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f"https://{url}"
        parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise ValueError("Invalid URL: missing hostname")

    return url, parsed


def capture_screenshot(
    url: str,
    output_path: str,
    viewport: str = "desktop",
    full_page: bool = False,
    timeout: int = 30000,
) -> dict:
    """
    Capture a screenshot of a web page.

    Args:
        url: URL to capture
        output_path: Output file path
        viewport: Viewport preset (desktop, laptop, tablet, mobile)
        full_page: Whether to capture full page or just viewport
        timeout: Page load timeout in milliseconds

    Returns:
        Dictionary with capture results
    """
    result = {
        "url": url,
        "output": output_path,
        "viewport": viewport,
        "engine": None,
        "success": False,
        "error": None,
    }

    if viewport not in VIEWPORTS:
        result["error"] = f"Invalid viewport: {viewport}. Choose from: {list(VIEWPORTS.keys())}"
        return result

    try:
        url, parsed = normalize_url(url)
        result["url"] = url
    except ValueError as e:
        result["error"] = str(e)
        return result

    # SSRF prevention: block private/internal IPs
    try:
        resolved_ip = socket.gethostbyname(parsed.hostname)
        ip = ipaddress.ip_address(resolved_ip)
        if ip.is_private or ip.is_loopback or ip.is_reserved:
            result["error"] = f"Blocked: URL resolves to private/internal IP ({resolved_ip})"
            return result
    except socket.gaierror:
        pass

    vp = VIEWPORTS[viewport]

    if HAS_PLAYWRIGHT:
        result["engine"] = "playwright"
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": vp["width"], "height": vp["height"]},
                    device_scale_factor=2 if viewport == "mobile" else 1,
                )
                page = context.new_page()
                page.goto(url, wait_until="networkidle", timeout=timeout)
                page.wait_for_timeout(1000)
                page.screenshot(path=output_path, full_page=full_page)
                result["success"] = True
                browser.close()
        except PlaywrightTimeout:
            result["error"] = f"Page load timed out after {timeout}ms"
        except Exception as e:
            result["error"] = str(e)
        return result

    # Fallback: system chrome/chromium via subprocess. Less accurate (no
    # device_scale_factor for mobile, no networkidle wait), but good enough
    # for smoke-tests and visual audits without Playwright installed.
    chrome_bin = _find_chrome_binary()
    if not chrome_bin:
        result["error"] = (
            "Neither Playwright nor a system chrome/chromium binary was found. "
            "Install Playwright: pip install playwright && playwright install chromium. "
            "Or install google-chrome / chromium system-wide."
        )
        return result

    result["engine"] = "chrome-headless"
    dpr = 2 if viewport == "mobile" else 1

    # --full-page-screenshot exists in Chrome 98+; older Chrome silently ignores it.
    cmd = [
        chrome_bin,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        f"--window-size={vp['width']},{vp['height']}",
        f"--force-device-scale-factor={dpr}",
        f"--screenshot={os.path.abspath(output_path)}",
        f"--virtual-time-budget={timeout}",
    ]
    if full_page:
        cmd.append("--full-page-screenshot")
    cmd.append(url)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(timeout / 1000 + 30, 60),
        )
    except subprocess.TimeoutExpired:
        result["error"] = f"chrome-headless timed out after {timeout}ms"
        return result
    except OSError as e:
        result["error"] = f"chrome-headless failed to start: {e}"
        return result

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip().splitlines()[-3:]
        result["error"] = (
            f"chrome-headless exited {proc.returncode}: "
            + " | ".join(stderr_tail)
        )
        return result

    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        result["error"] = "chrome-headless produced no screenshot file"
        return result

    result["success"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description="Capture web page screenshots")
    parser.add_argument("url", help="URL to capture")
    parser.add_argument("--output", "-o", default="screenshots", help="Output directory")
    parser.add_argument("--viewport", "-v", default="desktop", choices=VIEWPORTS.keys())
    parser.add_argument("--all", "-a", action="store_true", help="Capture all viewports")
    parser.add_argument("--full", "-f", action="store_true", help="Capture full page")
    parser.add_argument("--timeout", "-t", type=int, default=30000, help="Timeout in ms")

    args = parser.parse_args()

    # Sanitize output path - prevent directory traversal
    output_dir = os.path.realpath(args.output)
    cwd = os.getcwd()
    home = os.path.expanduser("~")
    if not (output_dir.startswith(cwd) or output_dir.startswith(home)):
        print("Error: Output path must be within current directory or home directory", file=sys.stderr)
        sys.exit(1)

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    try:
        normalized_url, parsed_url = normalize_url(args.url)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Generate filename from URL
    base_name = parsed_url.netloc.replace(".", "_")

    viewports = VIEWPORTS.keys() if args.all else [args.viewport]

    for viewport in viewports:
        filename = f"{base_name}_{viewport}.png"
        output_path = os.path.join(args.output, filename)

        print(f"Capturing {viewport} screenshot...")
        result = capture_screenshot(
            normalized_url,
            output_path,
            viewport=viewport,
            full_page=args.full,
            timeout=args.timeout,
        )

        if result["success"]:
            print(f"  ✓ Saved to {output_path}")
        else:
            print(f"  ✗ Failed: {result['error']}")


if __name__ == "__main__":
    main()

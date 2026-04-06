#!/usr/bin/env python3
"""
Frame TV Connection Test Script
Run this from INSIDE the container to diagnose connectivity:
  docker exec frame-tv-sync python3 /app/test_connection.py

Or run remotely via SSH:
  ssh nox@192.168.1.5 "docker exec frame-tv-sync python3 /app/test_connection.py"
"""

import asyncio
import inspect
import json
import os
import socket
import sys
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────────
TV_IP = os.getenv("TV_IPS", "192.168.1.106").split(",")[0].strip()
TV_PORT = int(os.getenv("TV_PORT", "8001"))
TV_NAME = os.getenv("TV_NAME", "ArtSync_Nox")
TOKEN_DIR = os.getenv("TOKEN_DIR", "/tokens")
TOKEN_FILE = str(Path(TOKEN_DIR) / f'tv_{TV_IP.replace(".", "_")}.txt')
TIMEOUT = 30

# ─── Colors ──────────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def header(msg):
    print(f"\n{BOLD}{CYAN}{'─' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {msg}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 60}{RESET}")


def ok(msg):
    print(f"  {GREEN}✔{RESET} {msg}")


def fail(msg):
    print(f"  {RED}✘{RESET} {msg}")


def warn(msg):
    print(f"  {YELLOW}⚠{RESET} {msg}")


def info(msg):
    print(f"  {CYAN}ℹ{RESET} {msg}")


# ─── Test 1: TCP Port Connectivity ──────────────────────────────────────────
def test_tcp_ports():
    header("Test 1: TCP Port Connectivity")
    for port in [8001, 8002]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((TV_IP, port))
            ok(f"Port {port}: OPEN")
            s.close()
        except Exception as e:
            fail(f"Port {port}: CLOSED ({e})")


# ─── Test 2: Library Inspection ──────────────────────────────────────────────
def test_library():
    header("Test 2: samsungtvws Library Inspection")
    try:
        from samsungtvws.async_art import SamsungTVAsyncArt
        sig = inspect.signature(SamsungTVAsyncArt.__init__)
        params = list(sig.parameters.keys())
        ok(f"SamsungTVAsyncArt found")
        info(f"__init__ params: {params}")

        if "ssl" in params:
            ok(f"'ssl' parameter IS supported")
        else:
            warn(f"'ssl' parameter NOT supported — do NOT pass ssl= to __init__")

        import samsungtvws
        version = getattr(samsungtvws, "__version__", "unknown")
        info(f"Library version: {version}")

    except ImportError as e:
        fail(f"Cannot import samsungtvws: {e}")
        return


# ─── Test 3: Token File Persistence ─────────────────────────────────────────
def test_token_persistence():
    header("Test 3: Token File Persistence")
    token_path = Path(TOKEN_FILE)
    token_dir = token_path.parent

    info(f"Token file: {TOKEN_FILE}")
    info(f"Token dir:  {token_dir}")

    if token_dir.exists():
        ok(f"Token directory exists")
    else:
        fail(f"Token directory DOES NOT exist")
        return

    # Write test
    test_file = token_dir / ".write_test"
    try:
        test_file.write_text("test")
        ok(f"Directory is writable")
        test_file.unlink()
    except Exception as e:
        fail(f"Directory is NOT writable: {e}")

    if token_path.exists():
        ok(f"Token file EXISTS (size: {token_path.stat().st_size} bytes)")
        try:
            content = token_path.read_text().strip()
            if content:
                ok(f"Token file has content (first 20 chars: {content[:20]}...)")
            else:
                warn(f"Token file is EMPTY")
        except Exception as e:
            warn(f"Could not read token file: {e}")
    else:
        warn(f"Token file does not exist yet (will be created on first successful handshake)")


# ─── Test 4: Live Connection ────────────────────────────────────────────────
async def test_connection():
    header("Test 4: Live WebSocket Connection")
    try:
        from samsungtvws.async_art import SamsungTVAsyncArt

        info(f"Connecting to {TV_IP}:{TV_PORT} as '{TV_NAME}'...")
        info(f"Token file: {TOKEN_FILE}")
        info(f"Timeout: {TIMEOUT}s")

        tv = SamsungTVAsyncArt(
            host=TV_IP,
            port=TV_PORT,
            name=TV_NAME,
            token_file=TOKEN_FILE,
            timeout=TIMEOUT,
        )

        print(f"\n  {YELLOW}⏳ Waiting for connection (if the TV prompts 'Allow/Deny',")
        print(f"     click ALLOW now — you have {TIMEOUT} seconds)...{RESET}\n")

        result = await tv.available()

        if result is not None:
            count = len(result) if isinstance(result, list) else "?"
            ok(f"Connection SUCCESSFUL! Got {count} art items from TV.")
        else:
            ok(f"Connection succeeded (available() returned None)")

        # Check if token was saved
        token_path = Path(TOKEN_FILE)
        if token_path.exists() and token_path.stat().st_size > 0:
            ok(f"Token file was saved! ({token_path.stat().st_size} bytes)")
        else:
            warn(f"Token file was NOT saved (handshake may not have completed)")

        # Try to get device info
        try:
            device_info = await tv.rest_device_info()
            if device_info and "device" in device_info:
                dev = device_info["device"]
                ok(f"Model: {dev.get('modelName', '?')}")
                ok(f"Firmware: {dev.get('firmwareVersion', '?')}")
        except Exception:
            info(f"Could not fetch device info (non-critical)")

        await tv.close()

    except asyncio.TimeoutError:
        fail(f"Connection TIMED OUT after {TIMEOUT}s")
        fail(f"The TV may be off or the 'Allow' prompt was not accepted in time.")
    except TypeError as e:
        fail(f"TypeError: {e}")
        fail(f"This usually means the library API changed. Check Test 2 for valid params.")
    except Exception as e:
        fail(f"Connection FAILED: {type(e).__name__}: {e}")


# ─── Test 5: Mapping File ───────────────────────────────────────────────────
def test_mapping():
    header("Test 5: Artwork Mapping File")
    mapping_file = Path(TOKEN_DIR) / f'tv_{TV_IP.replace(".", "_")}_mapping.json'
    info(f"Mapping file: {mapping_file}")

    if mapping_file.exists():
        try:
            data = json.loads(mapping_file.read_text())
            ok(f"Mapping file exists with {len(data)} entries")
            if data:
                first_key = list(data.keys())[0]
                info(f"Sample: {first_key} → {data[first_key][:30]}...")
        except Exception as e:
            warn(f"Could not parse mapping file: {e}")
    else:
        info(f"No mapping file yet (created after first successful upload)")


# ─── Main ───────────────────────────────────────────────────────────────────
def main():
    print(f"\n{BOLD}🖼️  Frame TV Connection Diagnostics{RESET}")
    print(f"  TV IP:   {TV_IP}")
    print(f"  Port:    {TV_PORT}")
    print(f"  Name:    {TV_NAME}")
    print(f"  Tokens:  {TOKEN_DIR}")

    test_tcp_ports()
    test_library()
    test_token_persistence()
    test_mapping()
    asyncio.run(test_connection())

    header("Done!")
    print()


if __name__ == "__main__":
    main()

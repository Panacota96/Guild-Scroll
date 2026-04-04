"""
CTF platform detection via VPN network interface (tun0).
Detects HTB (HackTheBox) and THM (TryHackMe) based on IP ranges.
"""
from __future__ import annotations

import ipaddress
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# Known IP ranges for CTF platforms
_PLATFORM_RANGES: dict[str, list[str]] = {
    "htb": ["10.10.0.0/16", "10.129.0.0/16"],
    "thm": ["10.8.0.0/16", "10.9.0.0/16"],
}


def _get_tun0_ip() -> Optional[str]:
    """Return the IPv4 address of tun0, or None if not present."""
    tun0_path = Path("/sys/class/net/tun0")
    if not tun0_path.exists():
        return None
    ip_cmd = shutil.which("ip")
    if not ip_cmd:
        return None
    try:
        result = subprocess.run(
            [ip_cmd, "-4", "addr", "show", "tun0"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                # "inet 10.10.14.5/23 ..."
                addr_part = line.split()[1]
                return addr_part.split("/")[0]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def detect_platform() -> Optional[str]:
    """
    Detect the CTF platform based on active VPN (tun0) IP address.
    Returns 'htb', 'thm', or None.
    """
    ip_str = _get_tun0_ip()
    if not ip_str:
        return None

    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return None

    for platform, ranges in _PLATFORM_RANGES.items():
        for cidr in ranges:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return platform

    return None

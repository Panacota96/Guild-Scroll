"""
Map command names to security phase tags (recon / exploit / post-exploit).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

TOOL_TAGS: dict[str, str] = {
    # Recon
    "nmap": "recon", "masscan": "recon", "rustscan": "recon",
    "gobuster": "recon", "ffuf": "recon", "dirb": "recon",
    "dirsearch": "recon", "feroxbuster": "recon",
    "nikto": "recon", "whatweb": "recon", "wpscan": "recon",
    "enum4linux": "recon", "smbclient": "recon", "rpcclient": "recon",
    "dig": "recon", "nslookup": "recon", "whois": "recon", "dnsrecon": "recon",
    "netdiscover": "recon", "arp-scan": "recon",
    # Exploit
    "sqlmap": "exploit", "msfconsole": "exploit", "msfvenom": "exploit",
    "searchsploit": "exploit", "hydra": "exploit", "medusa": "exploit",
    "john": "exploit", "hashcat": "exploit",
    "crackmapexec": "exploit", "nxc": "exploit",
    "impacket-psexec": "exploit", "impacket-smbexec": "exploit",
    "impacket-wmiexec": "exploit",
    "evil-winrm": "exploit", "pth-winexe": "exploit",
    "responder": "exploit", "bloodhound-python": "exploit",
    # Post-exploit
    "linpeas": "post-exploit", "winpeas": "post-exploit",
    "pspy": "post-exploit", "sudo": "post-exploit",
    "chisel": "post-exploit", "socat": "post-exploit", "ligolo": "post-exploit",
    "nc": "post-exploit", "ncat": "post-exploit", "netcat": "post-exploit",
    "python3": "post-exploit", "python": "post-exploit", "php": "post-exploit",
    "ssh": "post-exploit", "scp": "post-exploit",
}


def tag_command(command: str) -> Optional[str]:
    """Return the phase tag for a command, or None if unknown."""
    if not command or not command.strip():
        return None
    # Extract the binary name — first token, strip any path prefix
    binary = command.strip().split()[0]
    binary = Path(binary).name
    return TOOL_TAGS.get(binary)

"""
Map command names to security phase tags (recon / exploit / post-exploit).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ToolClassification:
    phase: str
    mitre_id: str
    mitre_name: str

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


TOOL_CLASSIFICATIONS: dict[str, ToolClassification] = {
    # Recon
    "nmap": ToolClassification("recon", "T1046", "Network Service Discovery"),
    "masscan": ToolClassification("recon", "T1046", "Network Service Discovery"),
    "rustscan": ToolClassification("recon", "T1046", "Network Service Discovery"),
    "gobuster": ToolClassification("recon", "T1595.003", "Wordlist Scanning"),
    "ffuf": ToolClassification("recon", "T1595.003", "Wordlist Scanning"),
    "dirb": ToolClassification("recon", "T1595.003", "Wordlist Scanning"),
    "dirsearch": ToolClassification("recon", "T1595.003", "Wordlist Scanning"),
    "feroxbuster": ToolClassification("recon", "T1595.003", "Wordlist Scanning"),
    "nikto": ToolClassification("recon", "T1595", "Active Scanning"),
    "whatweb": ToolClassification("recon", "T1595", "Active Scanning"),
    "wpscan": ToolClassification("recon", "T1595", "Active Scanning"),
    "enum4linux": ToolClassification("recon", "T1018", "Remote System Discovery"),
    "smbclient": ToolClassification("recon", "T1135", "Network Share Discovery"),
    "dig": ToolClassification("recon", "T1590.002", "DNS"),
    "nslookup": ToolClassification("recon", "T1590.002", "DNS"),
    "whois": ToolClassification("recon", "T1590", "Gather Victim Network Information"),
    "dnsrecon": ToolClassification("recon", "T1590.002", "DNS"),
    # Exploit
    "sqlmap": ToolClassification("exploit", "T1190", "Exploit Public-Facing Application"),
    "msfconsole": ToolClassification("exploit", "T1203", "Exploitation for Client Execution"),
    "msfvenom": ToolClassification("exploit", "T1587.001", "Malware"),
    "hydra": ToolClassification("exploit", "T1110", "Brute Force"),
    "medusa": ToolClassification("exploit", "T1110", "Brute Force"),
    "john": ToolClassification("exploit", "T1110.002", "Password Cracking"),
    "hashcat": ToolClassification("exploit", "T1110.002", "Password Cracking"),
    "crackmapexec": ToolClassification("exploit", "T1021", "Remote Services"),
    "nxc": ToolClassification("exploit", "T1021", "Remote Services"),
    "evil-winrm": ToolClassification("exploit", "T1021.006", "Windows Remote Management"),
    "responder": ToolClassification("exploit", "T1557.001", "LLMNR/NBT-NS Poisoning"),
    # Post-exploit
    "linpeas": ToolClassification("post-exploit", "T1087", "Account Discovery"),
    "winpeas": ToolClassification("post-exploit", "T1087", "Account Discovery"),
    "pspy": ToolClassification("post-exploit", "T1057", "Process Discovery"),
    "chisel": ToolClassification("post-exploit", "T1572", "Protocol Tunneling"),
    "socat": ToolClassification("post-exploit", "T1572", "Protocol Tunneling"),
    "nc": ToolClassification("post-exploit", "T1059", "Command and Scripting Interpreter"),
    "ssh": ToolClassification("post-exploit", "T1021.004", "SSH"),
    "scp": ToolClassification("post-exploit", "T1041", "Exfiltration Over C2 Channel"),
}


def classify_command(command: str) -> Optional[ToolClassification]:
    """Return ToolClassification for a command, or None if unknown."""
    if not command or not command.strip():
        return None
    binary = command.strip().split()[0]
    binary = Path(binary).name
    return TOOL_CLASSIFICATIONS.get(binary)

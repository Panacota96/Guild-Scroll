"""Tests for tool_tagger module."""
import pytest
from guild_scroll.tool_tagger import tag_command


@pytest.mark.parametrize("command,expected", [
    ("nmap -sV 10.10.10.1", "recon"),
    ("masscan -p 80 10.0.0.0/24", "recon"),
    ("gobuster dir -u http://x", "recon"),
    ("ffuf -w wordlist.txt", "recon"),
    ("sqlmap -u http://x", "exploit"),
    ("hydra -l admin -P pass.txt", "exploit"),
    ("hashcat -m 0 hash.txt", "exploit"),
    ("linpeas", "post-exploit"),
    ("nc -lvnp 4444", "post-exploit"),
    ("ssh user@10.0.0.1", "post-exploit"),
    ("ls -la", None),
    ("cat /etc/passwd", None),
    ("", None),
    ("/usr/bin/nmap -sV 10.10.10.1", "recon"),
    ("/opt/linpeas.sh", None),  # .sh suffix — not in TOOL_TAGS
])
def test_tag_command(command, expected):
    assert tag_command(command) == expected


def test_full_path_nmap():
    assert tag_command("/usr/bin/nmap -sV 10.0.0.1") == "recon"


def test_full_path_sqlmap():
    assert tag_command("/usr/local/bin/sqlmap -u http://x") == "exploit"


def test_empty_string_returns_none():
    assert tag_command("") is None


def test_whitespace_only_returns_none():
    assert tag_command("   ") is None

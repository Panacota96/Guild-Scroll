"""Tests for tool_tagger module."""
import pytest
from guild_scroll.tool_tagger import tag_command, classify_command, ToolClassification


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


def test_classify_returns_mitre():
    result = classify_command("nmap -sV 10.0.0.1")
    assert result == ToolClassification("recon", "T1046", "Network Service Discovery")


def test_classify_unknown_none():
    assert classify_command("ls -la") is None


def test_classify_empty_none():
    assert classify_command("") is None


def test_classify_full_path():
    result = classify_command("/usr/bin/nmap -sV 10.0.0.1")
    assert result == ToolClassification("recon", "T1046", "Network Service Discovery")


def test_classify_hydra():
    result = classify_command("hydra -l admin -P pass.txt ssh://10.0.0.1")
    assert result is not None
    assert result.phase == "exploit"
    assert result.mitre_id == "T1110"

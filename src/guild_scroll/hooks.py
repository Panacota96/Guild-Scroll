"""
Generates shell hook scripts and temporary hook directories that inject
recording hooks without modifying the user's own dotfiles.

Supports both zsh (via ZDOTDIR) and bash (via BASH_ENV).
"""
import os
import stat
import tempfile
from pathlib import Path


_ZSH_HOOK_TEMPLATE = """\
# Guild Scroll zsh hooks — auto-generated, do not edit

# Source user's real config first so aliases/prompt/plugins work
_gs_real_zshrc="${{GUILD_SCROLL_REAL_HOME:-$HOME}}/.zshrc"
[ -f "$_gs_real_zshrc" ] && source "$_gs_real_zshrc"

# [REC] prompt indicator
_gs_rec_marker="${{GUILD_SCROLL_REC_MARKER:-[REC]}}"
PROMPT="%F{{red}}${{_gs_rec_marker}}%f %F{{yellow}}{session_name}%f $PROMPT"

# --- Guild Scroll state ---
_gs_hook_file="{hook_events_path}"
_gs_seq=0
_gs_cmd_start=""
_gs_last_cmd=""

# preexec: called just before a command runs
preexec() {{
    _gs_cmd_start=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")
    _gs_last_cmd="$1"
    _gs_pre_snapshot=$(ls -1A "$PWD" 2>/dev/null | sort)
}}

# precmd: called just after a command finishes
precmd() {{
    local _exit=$?
    # Skip if no command was captured (e.g. empty enter)
    [ -z "$_gs_last_cmd" ] && return
    local _end
    _end=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")
    _gs_seq=$(( _gs_seq + 1 ))
    local _cmd_escaped
    _cmd_escaped=$(printf '%s' "$_gs_last_cmd" | sed 's/\\\\/\\\\\\\\/g' | sed 's/"/\\\\"/g')
    local _cwd_escaped
    _cwd_escaped=$(printf '%s' "$PWD" | sed 's/\\\\/\\\\\\\\/g' | sed 's/"/\\\\"/g')
    printf '{{"type":"command","seq":%d,"command":"%s","timestamp_start":"%s","timestamp_end":"%s","exit_code":%d,"working_directory":"%s"}}\n' \
        "$_gs_seq" "$_cmd_escaped" "$_gs_cmd_start" "$_end" "$_exit" "$_cwd_escaped" \
        >> "$_gs_hook_file"
    # Asset detection: diff directory listing
    local _post_snapshot
    _post_snapshot=$(ls -1A "$PWD" 2>/dev/null | sort)
    local _new_files
    _new_files=$(comm -13 <(printf '%s\n' "$_gs_pre_snapshot") <(printf '%s\n' "$_post_snapshot") 2>/dev/null)
    if [ -n "$_new_files" ]; then
        while IFS= read -r _fname; do
            [ -z "$_fname" ] && continue
            local _fpath="$PWD/$_fname"
            local _fsize
            _fsize=$(stat -c%s "$_fpath" 2>/dev/null || echo 0)
            if [ "$_fsize" -le {max_asset_size} ] 2>/dev/null; then
                local _fname_escaped
                _fname_escaped=$(printf '%s' "$_fname" | sed 's/\\\\/\\\\\\\\/g' | sed 's/"/\\\\"/g')
                local _fpath_escaped
                _fpath_escaped=$(printf '%s' "$_fpath" | sed 's/\\\\/\\\\\\\\/g' | sed 's/"/\\\\"/g')
                printf '{{"type":"asset_hint","seq":%d,"trigger_command":"%s","original_path":"%s","timestamp":"%s"}}\n' \
                    "$_gs_seq" "$_cmd_escaped" "$_fpath_escaped" "$_end" \
                    >> "$_gs_hook_file"
            fi
        done <<< "$_new_files"
    fi
    _gs_last_cmd=""
    _gs_pre_snapshot=""
}}
"""

_BASH_HOOK_TEMPLATE = """\
# Guild Scroll bash hooks — auto-generated, do not edit

# Source user's real config first so aliases/plugins work
_gs_real_bashrc="${{GUILD_SCROLL_REAL_HOME:-$HOME}}/.bashrc"
[ -f "$_gs_real_bashrc" ] && source "$_gs_real_bashrc"

# [REC] prompt indicator
_gs_rec_marker="${{GUILD_SCROLL_REC_MARKER:-[REC]}}"
PS1="\\[\\033[31m\\]${{_gs_rec_marker}}\\[\\033[0m\\] \\[\\033[33m\\]{session_name}\\[\\033[0m\\] $PS1"

# --- Guild Scroll state ---
_gs_hook_file="{hook_events_path}"
_gs_seq=0
_gs_cmd_start=""
_gs_last_cmd=""
_gs_pre_snapshot=""
_gs_in_prompt_command=0

_gs_preexec() {{
    # Guard: don't fire inside PROMPT_COMMAND
    [ "$_gs_in_prompt_command" = "1" ] && return
    # Only capture on interactive user commands (BASH_COMMAND != PROMPT_COMMAND itself)
    [ "$BASH_COMMAND" = "_gs_precmd" ] && return
    _gs_cmd_start=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")
    _gs_last_cmd="$BASH_COMMAND"
    _gs_pre_snapshot=$(ls -1A "$PWD" 2>/dev/null | sort)
}}

_gs_precmd() {{
    local _exit=$?
    _gs_in_prompt_command=1
    # Skip if no command was captured
    if [ -n "$_gs_last_cmd" ]; then
        local _end
        _end=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")
        _gs_seq=$(( _gs_seq + 1 ))
        local _cmd_escaped
        _cmd_escaped=$(printf '%s' "$_gs_last_cmd" | sed 's/\\\\/\\\\\\\\/g' | sed 's/"/\\\\"/g')
        local _cwd_escaped
        _cwd_escaped=$(printf '%s' "$PWD" | sed 's/\\\\/\\\\\\\\/g' | sed 's/"/\\\\"/g')
        printf '{{"type":"command","seq":%d,"command":"%s","timestamp_start":"%s","timestamp_end":"%s","exit_code":%d,"working_directory":"%s"}}\n' \
            "$_gs_seq" "$_cmd_escaped" "$_gs_cmd_start" "$_end" "$_exit" "$_cwd_escaped" \
            >> "$_gs_hook_file"
        # Asset detection: diff directory listing
        local _post_snapshot
        _post_snapshot=$(ls -1A "$PWD" 2>/dev/null | sort)
        local _new_files
        _new_files=$(comm -13 <(printf '%s\n' "$_gs_pre_snapshot") <(printf '%s\n' "$_post_snapshot") 2>/dev/null)
        if [ -n "$_new_files" ]; then
            while IFS= read -r _fname; do
                [ -z "$_fname" ] && continue
                local _fpath="$PWD/$_fname"
                local _fsize
                _fsize=$(stat -c%s "$_fpath" 2>/dev/null || echo 0)
                if [ "$_fsize" -le {max_asset_size} ] 2>/dev/null; then
                    local _fpath_escaped
                    _fpath_escaped=$(printf '%s' "$_fpath" | sed 's/\\\\/\\\\\\\\/g' | sed 's/"/\\\\"/g')
                    printf '{{"type":"asset_hint","seq":%d,"trigger_command":"%s","original_path":"%s","timestamp":"%s"}}\n' \
                        "$_gs_seq" "$_cmd_escaped" "$_fpath_escaped" "$_end" \
                        >> "$_gs_hook_file"
                fi
            done <<< "$_new_files"
        fi
        _gs_last_cmd=""
        _gs_pre_snapshot=""
    fi
    _gs_in_prompt_command=0
}}

trap '_gs_preexec' DEBUG
PROMPT_COMMAND='_gs_precmd'
"""


def detect_shell() -> str:
    """Detect the current user shell. Returns 'zsh', 'bash', or 'bash' as fallback."""
    shell_env = os.environ.get("SHELL", "")
    name = Path(shell_env).name.lower()
    if name == "zsh":
        return "zsh"
    if name == "bash":
        return "bash"
    # Fallback: default to bash for unknown shells
    return "bash"


def generate_hook_script(
    hook_events_path: Path,
    max_asset_size: int = 52428800,
    session_name: str = "",
) -> str:
    """Return the zsh hook script as a string (kept for backwards compat)."""
    return _ZSH_HOOK_TEMPLATE.format(
        hook_events_path=str(hook_events_path),
        max_asset_size=max_asset_size,
        session_name=session_name,
    )


def generate_bash_hook_script(
    hook_events_path: Path,
    max_asset_size: int = 52428800,
    session_name: str = "",
) -> str:
    """Return the bash hook script as a string."""
    return _BASH_HOOK_TEMPLATE.format(
        hook_events_path=str(hook_events_path),
        max_asset_size=max_asset_size,
        session_name=session_name,
    )


def create_zdotdir(
    hook_events_path: Path,
    max_asset_size: int = 52428800,
    session_name: str = "",
) -> Path:
    """
    Create a temporary directory to use as ZDOTDIR for zsh.
    Returns the path; caller is responsible for cleanup.
    """
    zdotdir = Path(tempfile.mkdtemp(prefix="guild_scroll_zdotdir_"))
    zshrc = zdotdir / ".zshrc"
    script = generate_hook_script(hook_events_path, max_asset_size, session_name=session_name)
    zshrc.write_text(script, encoding="utf-8")
    zshrc.chmod(zshrc.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR)
    return zdotdir


def create_bash_rcdir(
    hook_events_path: Path,
    max_asset_size: int = 52428800,
    session_name: str = "",
) -> Path:
    """
    Create a temporary directory with a .bashrc for bash hook injection.
    The path is used with BASH_ENV. Returns the path; caller cleans up.
    """
    rcdir = Path(tempfile.mkdtemp(prefix="guild_scroll_bashrc_"))
    bashrc = rcdir / ".bashrc"
    script = generate_bash_hook_script(hook_events_path, max_asset_size, session_name=session_name)
    bashrc.write_text(script, encoding="utf-8")
    bashrc.chmod(bashrc.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR)
    return rcdir


def create_hook_dir(
    hook_events_path: Path,
    max_asset_size: int = 52428800,
    session_name: str = "",
    shell: str = "zsh",
) -> tuple[Path, str]:
    """
    Create the appropriate hook directory for the given shell.
    Returns (hook_dir, shell) tuple. Caller is responsible for cleanup.
    """
    if shell == "zsh":
        return create_zdotdir(hook_events_path, max_asset_size, session_name), "zsh"
    return create_bash_rcdir(hook_events_path, max_asset_size, session_name), "bash"

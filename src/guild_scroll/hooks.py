"""
Generates the zsh hook script and a temporary ZDOTDIR that injects it
without modifying the user's own dotfiles.
"""
import os
import stat
import tempfile
from pathlib import Path


_HOOK_TEMPLATE = """\
# Guild Scroll zsh hooks — auto-generated, do not edit

# Source user's real config first so aliases/prompt/plugins work
_gs_real_zshrc="${{GUILD_SCROLL_REAL_HOME:-$HOME}}/.zshrc"
[ -f "$_gs_real_zshrc" ] && source "$_gs_real_zshrc"

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
    _cmd_escaped=$(printf '%s' "$_gs_last_cmd" | sed 's/\\/\\\\/g; s/"/\\"/g')
    local _cwd_escaped
    _cwd_escaped=$(printf '%s' "$PWD" | sed 's/\\/\\\\/g; s/"/\\"/g')
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
                _fname_escaped=$(printf '%s' "$_fname" | sed 's/\\/\\\\/g; s/"/\\"/g')
                local _fpath_escaped
                _fpath_escaped=$(printf '%s' "$_fpath" | sed 's/\\/\\\\/g; s/"/\\"/g')
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


def generate_hook_script(hook_events_path: Path, max_asset_size: int = 52428800) -> str:
    """Return the zsh hook script as a string."""
    return _HOOK_TEMPLATE.format(
        hook_events_path=str(hook_events_path),
        max_asset_size=max_asset_size,
    )


def create_zdotdir(hook_events_path: Path, max_asset_size: int = 52428800) -> Path:
    """
    Create a temporary directory to use as ZDOTDIR.
    Returns the path; caller is responsible for cleanup.
    """
    zdotdir = Path(tempfile.mkdtemp(prefix="guild_scroll_zdotdir_"))
    zshrc = zdotdir / ".zshrc"
    script = generate_hook_script(hook_events_path, max_asset_size)
    zshrc.write_text(script, encoding="utf-8")
    zshrc.chmod(zshrc.stat().st_mode | stat.S_IRUSR | stat.S_IWUSR)
    return zdotdir

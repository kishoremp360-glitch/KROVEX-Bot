"""Validation rules and safe template rendering engine for Custom Commands.

Provides strict name formatting validation, bidirectional collision prevention,
and an allowlist-only template parser with zero eval/exec/format execution.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# Valid command/alias name: 2-32 lowercase alphanumeric, underscore, or hyphen
COMMAND_NAME_REGEX = re.compile(r"^[a-z0-9_-]{2,32}$")

# Template placeholder pattern: strictly matches {token}
TEMPLATE_TOKEN_REGEX = re.compile(r"\{([a-zA-Z0-9_]+)\}")

# Strict allowlist of permitted template variables
ALLOWED_TEMPLATE_VARS: Set[str] = {
    "user",
    "user_mention",
    "server",
    "member_count",
    "channel",
    "date",
}

# Universal reserved system commands that cannot be overridden
RESERVED_COMMAND_NAMES: Set[str] = {
    "help",
    "ping",
    "play",
    "pause",
    "skip",
    "stop",
    "queue",
    "serverinfo",
    "userinfo",
    "avatar",
    "admin",
    "setup",
    "automod",
    "eco",
    "rate",
    "level",
    "logs",
    "game",
    "music",
    "playlist",
    "vc",
    "rr",
    "security",
    "shop",
    "interact",
    "react",
    "ticket",
    "util",
    "welcome",
    "custom",
}


def normalize_command_name(name: str) -> str:
    """Normalize command name to trimmed lowercase."""
    return name.strip().lower() if name else ""


def validate_command_name_format(name: str) -> Tuple[bool, str]:
    """Validate format constraints: 2-32 chars, lowercase alphanumeric, -, _."""
    normalized = normalize_command_name(name)
    if not normalized:
        return False, "Command name cannot be empty."

    if len(normalized) < 2:
        return False, f"Command name '{normalized}' is too short (minimum 2 characters)."

    if len(normalized) > 32:
        return False, f"Command name '{normalized}' is too long (maximum 32 characters)."

    if not COMMAND_NAME_REGEX.match(normalized):
        return (
            False,
            f"Invalid command name '{normalized}'. Only lowercase letters, numbers, underscores, and hyphens are allowed.",
        )

    return True, ""


async def validate_command_collision(
    name: str,
    guild_id: int,
    bot: Optional[Any] = None,
    repo: Optional[Any] = None,
    is_alias: bool = False,
    existing_command_name: Optional[str] = None,
) -> Tuple[bool, str]:
    """Check name collisions against native commands, reserved words, and guild commands/aliases."""
    norm_name = normalize_command_name(name)

    # 1. Reserved names
    if norm_name in RESERVED_COMMAND_NAMES:
        return False, f"'{norm_name}' is a reserved system command name and cannot be used."

    # 2. Collision with native bot prefix commands and aliases
    if bot:
        # Prefix command registry
        all_prefix_cmds = getattr(bot, "all_commands", {})
        if norm_name in all_prefix_cmds:
            return False, f"'{norm_name}' conflicts with an existing native prefix command."

        # Slash command registry
        tree = getattr(bot, "tree", None)
        if tree:
            for app_cmd in tree.get_commands():
                if app_cmd.name.lower() == norm_name:
                    return False, f"'{norm_name}' conflicts with an existing native slash command."

    # 3. Collision within guild custom commands & aliases
    if repo and guild_id:
        if is_alias:
            # An alias cannot collide with an existing primary command
            existing_primary = await repo.get_command(guild_id, norm_name, resolve_alias=False)
            if existing_primary:
                return False, f"Alias '{norm_name}' conflicts with an existing custom command in this server."

            # An alias cannot collide with another existing alias
            existing_alias = await repo.get_alias(guild_id, norm_name)
            if existing_alias and existing_alias.alias != existing_command_name:
                return False, f"Alias '{norm_name}' already exists in this server."
        else:
            # A primary command cannot collide with an existing alias
            existing_alias = await repo.get_alias(guild_id, norm_name)
            if existing_alias:
                return False, f"Command name '{norm_name}' conflicts with an existing alias in this server."

            # Cannot collide with another existing primary command (unless updating same command)
            existing_cmd = await repo.get_command(guild_id, norm_name, resolve_alias=False)
            if existing_cmd and existing_cmd.name != existing_command_name:
                return False, f"Custom command '{norm_name}' already exists in this server."

    return True, ""


def validate_template_variables(template: str) -> Tuple[bool, str]:
    """Validate that all placeholders in a template belong to the strict allowlist."""
    if not template:
        return True, ""

    # Check for unclosed braces or syntax issues
    tokens = TEMPLATE_TOKEN_REGEX.findall(template)
    
    # Check for any braces that might indicate malformed or unknown tokens
    all_braces = re.findall(r"\{([^{}]*)\}", template)
    for token in all_braces:
        clean_token = token.strip()
        if clean_token not in ALLOWED_TEMPLATE_VARS:
            allowed_list = ", ".join(f"{{{v}}}" for v in sorted(ALLOWED_TEMPLATE_VARS))
            return (
                False,
                f"Unknown or forbidden variable '{{{clean_token}}}'. Allowed variables: {allowed_list}",
            )

    return True, ""


def render_safe_template(template: str, context: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Render a text template by strictly replacing validated allowlist tokens.
    
    Does NOT use eval, exec, str.format, or %-formatting. Direct string replacement only.
    """
    if not template:
        return "", None

    # Step 1: Validate all variables
    is_valid, error_msg = validate_template_variables(template)
    if not is_valid:
        return "", error_msg

    # Step 2: Build safe substitution mapping
    user_str = str(context.get("user", ""))
    user_mention = str(context.get("user_mention", f"<@{context.get('user_id', '')}>")) if context.get("user_mention") or context.get("user_id") else user_str
    server_str = str(context.get("server", ""))
    member_count_str = str(context.get("member_count", ""))
    channel_str = str(context.get("channel", ""))
    date_str = str(context.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")))

    substitutions: Dict[str, str] = {
        "{user}": user_str,
        "{user_mention}": user_mention,
        "{server}": server_str,
        "{member_count}": member_count_str,
        "{channel}": channel_str,
        "{date}": date_str,
    }

    # Step 3: Direct literal replacement
    rendered = template
    for placeholder, value in substitutions.items():
        rendered = rendered.replace(placeholder, value)

    return rendered, None

"""Transcript generation utility for support tickets."""
from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from typing import List, Optional

import discord

from bot.utils.embeds import COLOR_PRIMARY, UI_FONT_BODY, UI_FONT_HEADING, UI_FONT_MONOSPACE


async def generate_transcript(channel: discord.TextChannel, limit: int = 500) -> discord.File:
    """Read channel message history and format into a styled HTML transcript."""
    messages: List[discord.Message] = []
    async for msg in channel.history(limit=limit, oldest_first=True):
        messages.append(msg)

    primary_hex = f"#{COLOR_PRIMARY:06x}"
    html_lines = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "  <meta charset='UTF-8'>",
        f"  <title>Ticket Transcript — #{channel.name}</title>",
        "  <style>",
        f"    body {{ font-family: '{UI_FONT_BODY}', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0f0f13; color: #e2e8f0; margin: 0; padding: 24px; }}",
        f"    .header {{ background: #1a162b; border-left: 4px solid {primary_hex}; padding: 16px 20px; border-radius: 8px; margin-bottom: 24px; }}",
        f"    .header h1 {{ font-family: '{UI_FONT_HEADING}', sans-serif; margin: 0 0 6px 0; font-size: 20px; color: #c084fc; }}",
        "    .header p { margin: 0; font-size: 13px; color: #94a3b8; }",
        "    .message-container { display: flex; flex-direction: column; gap: 14px; }",
        "    .message { display: flex; gap: 14px; background: #161522; padding: 12px 16px; border-radius: 8px; border: 1px solid #2d2b42; }",
        "    .avatar { width: 40px; height: 40px; border-radius: 50%; background: #3b2d54; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #c084fc; flex-shrink: 0; }",
        "    .content { display: flex; flex-direction: column; gap: 4px; width: 100%; }",
        "    .author { font-weight: 600; color: #e2e8f0; font-size: 14px; display: flex; align-items: center; gap: 8px; }",
        f"    .bot-tag {{ background: {primary_hex}; color: #fff; font-size: 10px; padding: 1px 4px; border-radius: 4px; text-transform: uppercase; }}",
        "    .timestamp { font-size: 11px; color: #64748b; font-weight: normal; }",
        "    .text { font-size: 13px; color: #cbd5e1; word-break: break-word; line-height: 1.5; }",
        f"    code, pre {{ font-family: '{UI_FONT_MONOSPACE}', 'Fira Code', monospace; }}",
        "    .attachment { font-size: 12px; color: #a855f7; margin-top: 4px; }",
        "  </style>",
        "</head>",
        "<body>",
        "  <div class='header'>",
        f"    <h1>🎫 Ticket Transcript: #{channel.name}</h1>",
        f"    <p>Channel ID: {channel.id} | Guild: {channel.guild.name} ({channel.guild.id}) | Exported at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | Total Messages: {len(messages)}</p>",
        "  </div>",
        "  <div class='message-container'>",
    ]

    for m in messages:
        author_name = m.author.display_name
        time_str = m.created_at.strftime("%Y-%m-%d %H:%M:%S")
        bot_badge = "<span class='bot-tag'>BOT</span>" if m.author.bot else ""
        content_escaped = (
            m.clean_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            if m.clean_content
            else "<em>(No text content)</em>"
        )

        attachments_html = ""
        if m.attachments:
            att_links = [f"<div class='attachment'>📎 Attachment: <a href='{a.url}' target='_blank' style='color:#c084fc;'>{a.filename}</a></div>" for a in m.attachments]
            attachments_html = "".join(att_links)

        html_lines.append(f"""    <div class='message'>
      <div class='avatar'>{author_name[:2].upper()}</div>
      <div class='content'>
        <div class='author'>{author_name} {bot_badge} <span class='timestamp'>{time_str}</span></div>
        <div class='text'>{content_escaped}</div>
        {attachments_html}
      </div>
    </div>""")

    html_lines.extend(["  </div>", "</body>", "</html>"])
    full_html = "\n".join(html_lines)
    buf = io.BytesIO(full_html.encode("utf-8"))
    buf.seek(0)
    return discord.File(buf, filename=f"transcript-{channel.name}-{channel.id}.html")


async def setup(bot: Any) -> None:
    """Extension dummy setup."""
    pass


import socket
_orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import asyncio
import os
from dotenv import load_dotenv
import discord

load_dotenv("F:/Death Bot/.env")

async def test():
    token = os.getenv("DISCORD_TOKEN", "").strip()
    client = discord.Client(intents=discord.Intents.none())
    await client.login(token)
    print("Successfully logged into Discord REST API!")
    print(f"Bot User: {client.user} (ID: {client.user.id})")
    await client.close()

asyncio.run(test())

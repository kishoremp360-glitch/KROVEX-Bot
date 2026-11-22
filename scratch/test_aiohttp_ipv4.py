import asyncio
import socket
import aiohttp

async def test():
    connector = aiohttp.TCPConnector(family=socket.AF_INET)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get("https://discord.com/api/v10/gateway") as resp:
            print("Status:", resp.status)
            print("Response:", await resp.json())

asyncio.run(test())

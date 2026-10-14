"""Harmless protocol fixtures for real Nmap scans on the Docker network."""

import asyncio
import logging
import struct
import sys
from collections.abc import Awaitable, Callable

LOG = logging.getLogger("demo-target")
BACKDOOR: asyncio.Server | None = None
BACKDOOR_LOCK = asyncio.Lock()


async def backdoor(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while await reader.readline():
        writer.write(b"uid=0(root) gid=0(root) groups=0(root)\n")
        await writer.drain()


async def ftp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    global BACKDOOR
    writer.write(b"220 (vsFTPd 2.3.4)\r\n")
    await writer.drain()
    while line := await reader.readline():
        command, _, argument = line.decode("ascii", errors="replace").strip().partition(" ")
        if command.upper() == "USER":
            if argument.endswith(":)"):
                async with BACKDOOR_LOCK:
                    if BACKDOOR is None:
                        BACKDOOR = await listen(6200, backdoor)
                        LOG.info("Enabled simulated backdoor (no commands are executed)")
            reply = b"331 Please specify the password.\r\n"
        elif command.upper() == "PASS":
            reply = b"530 Login incorrect.\r\n"
        elif command.upper() == "QUIT":
            writer.write(b"221 Goodbye.\r\n")
            await writer.drain()
            return
        elif command.upper() == "SYST":
            reply = b"215 UNIX Type: L8\r\n"
        else:
            reply = b"502 Command not implemented.\r\n"
        writer.write(reply)
        await writer.drain()


async def ssh(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    writer.write(b"SSH-2.0-OpenSSH_4.7p1 Debian-8ubuntu1\r\n")
    await writer.drain()


async def http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    request = await reader.readuntil(b"\r\n\r\n")
    lines = request.decode("iso-8859-1").split("\r\n")
    method = lines[0].split(" ")[0]
    headers = dict(
        (key.lower(), value.strip())
        for line in lines[1:] if ":" in line
        for key, value in [line.split(":", 1)]
    )
    # Only simulate the response; never expand ranges or allocate their payloads.
    partial = headers.get("range", "").lower().startswith("bytes=")
    body = b"<!doctype html><title>Demo target</title><p>Harmless scan fixture.</p>\n"
    status = "206 Partial Content" if partial else "200 OK"
    content_type = "text/html"
    if partial and "," in headers["range"]:
        content_type = "multipart/byteranges; boundary=demo"
        body = (b"--demo\r\nContent-Type: text/html\r\n"
                b"Content-Range: bytes 0-0/69\r\n\r\n<\r\n--demo--\r\n")
    response = (
        f"HTTP/1.1 {status}\r\n"
        "Server: Apache/2.2.8 (Ubuntu)\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Accept-Ranges: bytes\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    writer.write(response + (b"" if method == "HEAD" else body))
    await writer.drain()


async def mysql(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    # Protocol 10 greeting with a fixed, fake authentication challenge.
    payload = (
        b"\x0a5.0.51a-3ubuntu5\x00" + struct.pack("<I", 1)
        + b"abcdefgh\x00" + struct.pack("<H", 0xF7FF)
        + b"\x08" + struct.pack("<H", 2) + struct.pack("<H", 0)
        + b"\x00" + b"\x00" * 10 + b"ijklmnopqrst\x00"
    )
    writer.write(len(payload).to_bytes(3, "little") + b"\x00" + payload)
    await writer.drain()


async def listen(
    port: int,
    handler: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]],
) -> asyncio.Server:
    async def connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        LOG.info("Connection on TCP %s", port)
        try:
            await asyncio.wait_for(handler(reader, writer), timeout=15)
        except (TimeoutError, ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    server = await asyncio.start_server(connection, "0.0.0.0", port, limit=65536)
    LOG.info("Listening on TCP %s", port)
    return server


async def main() -> None:
    servers = [await listen(port, handler) for port, handler in
               [(21, ftp), (22, ssh), (80, http), (3306, mysql)]]
    try:
        await asyncio.Event().wait()
    finally:
        for server in servers:
            server.close()
        if BACKDOOR is not None:
            BACKDOOR.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(message)s")
    asyncio.run(main())

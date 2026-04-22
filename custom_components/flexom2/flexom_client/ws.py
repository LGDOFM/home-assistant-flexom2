"""Minimal STOMP 1.2 client over aiohttp WebSocket for Hemis realtime events.

Flexom (Hemis) pushes ACTUATOR_HARDWARE_STATE / FACTOR_CURRENT_STATE / ... events
on ``jms.topic.{buildingId}.data`` as soon as the hardware acknowledges changes.
This client keeps one persistent WS open, subscribes to that topic, and calls the
provided async handler on each incoming MESSAGE frame.

Reconnect and token refresh are NOT handled here — orchestrate those in the caller.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .errors import FlexomNetworkError

_log = logging.getLogger(__name__)

NUL = "\x00"
EOL = "\n"

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


def _encode_frame(command: str, headers: dict[str, str], body: str = "") -> str:
    lines = [command]
    lines.extend(f"{k}:{v}" for k, v in headers.items())
    lines.append("")
    lines.append(body)
    return EOL.join(lines) + NUL


def _parse_frame(raw: str) -> tuple[str, dict[str, str], str]:
    if raw.endswith(NUL):
        raw = raw[:-1]
    parts = raw.split(EOL + EOL, 1)
    head_lines = parts[0].split(EOL)
    command = head_lines[0]
    headers: dict[str, str] = {}
    for line in head_lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k] = v
    body = parts[1] if len(parts) > 1 else ""
    return command, headers, body


class StompClient:
    HEARTBEAT_MS = 20000

    def __init__(
        self,
        ws_url: str,
        building_id: str,
        token: str,
        handler: EventHandler,
    ) -> None:
        self._ws_url = ws_url
        self._building_id = building_id
        self._token = token
        self._handler = handler
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._closed = asyncio.Event()
        self._connected = asyncio.Event()

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(
                self._ws_url,
                protocols=("v12.stomp", "v11.stomp"),
                heartbeat=self.HEARTBEAT_MS / 1000.0,
            )
        except aiohttp.ClientError as e:
            await self._session.close()
            self._session = None
            raise FlexomNetworkError(f"STOMP ws_connect failed: {e}") from e

        host = urlparse(self._ws_url).hostname or "localhost"
        await self._ws.send_str(
            _encode_frame(
                "CONNECT",
                {
                    "accept-version": "1.2",
                    "host": host,
                    "login": self._building_id,
                    "passcode": self._token,
                    "heart-beat": f"{self.HEARTBEAT_MS},{self.HEARTBEAT_MS}",
                },
            )
        )

        self._reader_task = asyncio.create_task(self._reader_loop(), name="stomp-reader")

        try:
            await asyncio.wait_for(self._connected.wait(), timeout=10.0)
        except TimeoutError as e:
            await self.disconnect()
            raise FlexomNetworkError("STOMP CONNECTED frame timeout") from e

        await self._ws.send_str(
            _encode_frame(
                "SUBSCRIBE",
                {
                    "id": "sub-1",
                    "destination": f"jms.topic.{self._building_id}.data",
                    "ack": "auto",
                },
            )
        )
        _log.info("STOMP subscribed to jms.topic.%s.data", self._building_id)

    async def disconnect(self) -> None:
        self._closed.set()
        if self._ws is not None and not self._ws.closed:
            try:
                await self._ws.send_str(_encode_frame("DISCONNECT", {}))
            except Exception:
                pass
            try:
                await self._ws.close()
            except Exception:
                pass
        for t in (self._reader_task, self._heartbeat_task):
            if t is not None and not t.done():
                t.cancel()
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def _reader_loop(self) -> None:
        assert self._ws is not None
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_raw(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            _log.warning("STOMP reader loop crashed: %s", e)
        finally:
            self._closed.set()

    async def _handle_raw(self, raw: str) -> None:
        if raw.strip() == "":
            return  # heartbeat
        for frame_raw in raw.split(NUL):
            if not frame_raw.strip():
                continue
            try:
                command, headers, body = _parse_frame(frame_raw + NUL)
            except Exception as e:  # noqa: BLE001
                _log.warning("Failed to parse STOMP frame: %s", e)
                continue
            await self._handle_frame(command, headers, body)

    async def _handle_frame(
        self, command: str, headers: dict[str, str], body: str
    ) -> None:
        if command == "CONNECTED":
            _log.info("STOMP connected (server headers=%s)", headers)
            self._connected.set()
        elif command == "MESSAGE":
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                _log.warning("Non-JSON MESSAGE body: %r", body[:200])
                return
            try:
                await self._handler(data)
            except Exception as e:  # noqa: BLE001
                _log.exception("STOMP event handler failed: %s", e)
        elif command == "ERROR":
            _log.error("STOMP ERROR frame: headers=%s body=%s", headers, body[:300])

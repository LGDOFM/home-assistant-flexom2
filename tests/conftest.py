"""Shared fixtures.

These tests talk to the REAL Hemis building (read-only) and therefore need
FLEXOM_EMAIL / FLEXOM_PASSWORD, either in the environment or in a ``.env``
file passed through FLEXOM_DOTENV. Without credentials they are skipped.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
import pytest_socket

pytest_plugins = "pytest_homeassistant_custom_component"


# The HA test plugin calls pytest_socket.disable_socket() before fixtures run,
# which on Windows also breaks the asyncio Proactor loop's internal socketpair.
# These tests are live-network by design, so neutralise it at the source.
pytest_socket.disable_socket = lambda *args, **kwargs: None  # type: ignore[assignment]
pytest_socket.socket_allow_hosts = lambda *args, **kwargs: None  # type: ignore[assignment]

if sys.platform == "win32":
    # aiodns (used by aiohttp) needs a selector loop on Windows. The HA test
    # plugin installs HassEventLoopPolicy (a DefaultEventLoopPolicy subclass,
    # i.e. Proactor on Windows), so swap its loop factory.
    from homeassistant import runner

    runner.HassEventLoopPolicy._loop_factory = asyncio.SelectorEventLoop  # type: ignore[attr-defined]


def _load_dotenv(path: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path or not Path(path).is_file():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@pytest.fixture
def credentials() -> tuple[str, str]:
    env = {**_load_dotenv(os.environ.get("FLEXOM_DOTENV")), **os.environ}
    email, password = env.get("FLEXOM_EMAIL"), env.get("FLEXOM_PASSWORD")
    if not email or not password:
        pytest.skip("FLEXOM_EMAIL / FLEXOM_PASSWORD not set")
    return email, password


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def expected_lingering_tasks() -> bool:
    # The STOMP keep-alive task is cancelled on unload; tolerate the teardown race.
    return True


@pytest.fixture
def expected_lingering_timers() -> bool:
    return True

"""Loopback port allocation for independent OSWorld relay processes."""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass

_issued_ports: set[int] = set()
_lock = threading.Lock()


@dataclass(frozen=True)
class PortBundle:
    control: int
    server: int
    chromium: int
    vlc: int


def _free_loopback_port() -> int:
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with _lock:
            if port not in _issued_ports:
                _issued_ports.add(port)
                return port


def reserve_port_bundle() -> PortBundle:
    return PortBundle(
        control=_free_loopback_port(),
        server=_free_loopback_port(),
        chromium=_free_loopback_port(),
        vlc=_free_loopback_port(),
    )

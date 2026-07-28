import ipaddress
import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from evaluation_workbench.models import ExecutionProfile


class ProfileAuthorizationError(RuntimeError):
    pass


class ExternalNetworkDenied(RuntimeError):
    pass


@contextmanager
def execution_guard(
    profile: ExecutionProfile,
    *,
    synthetic_only: bool,
) -> Iterator[None]:
    if profile is ExecutionProfile.LIVE_INTELLIGENCE:
        if os.environ.get("CLAIMS_RUN_LIVE_AWS") != "1":
            raise ProfileAuthorizationError(
                "LIVE_INTELLIGENCE requires CLAIMS_RUN_LIVE_AWS=1"
            )
        if not synthetic_only:
            raise ProfileAuthorizationError(
                "LIVE_INTELLIGENCE accepts synthetic inputs only"
            )
        yield
        return

    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def guarded_connect(instance: socket.socket, address: Any) -> Any:
        _require_loopback(address)
        return original_connect(instance, address)

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        _require_loopback(address)
        return original_create_connection(address, *args, **kwargs)

    with (
        patch.object(socket.socket, "connect", guarded_connect),
        patch.object(socket, "create_connection", guarded_create_connection),
    ):
        yield


def _require_loopback(address: object) -> None:
    if isinstance(address, str):
        # Unix-domain sockets are local.
        return
    if not isinstance(address, tuple) or not address:
        raise ExternalNetworkDenied("Recorded evaluation denied an unknown network address")
    host = address[0]
    if not isinstance(host, str):
        raise ExternalNetworkDenied("Recorded evaluation denied an unknown network host")
    if host.casefold() == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ExternalNetworkDenied(
        f"Recorded evaluation denied external network host {host}"
    )

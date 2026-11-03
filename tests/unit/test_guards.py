import socket

import pytest

from tests.conftest import NetworkAccessError


def test_internet_sockets_are_blocked_during_tests() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkAccessError),
    ):
        sock.connect(("192.0.2.1", 443))  # TEST-NET-1, never routed


def test_create_connection_is_blocked_too() -> None:
    with pytest.raises(NetworkAccessError):
        socket.create_connection(("192.0.2.1", 443), timeout=1)

import ipaddress
import socket
from unittest.mock import MagicMock, patch

from zeroconf_manager.zeroconf_manager import _get_lan_ip


def test_get_lan_ip_is_not_loopback():
    # The actual regression: socket.gethostbyname(socket.gethostname())
    # can resolve to 127.0.0.1/127.0.1.1 depending on /etc/hosts (this is
    # exactly what happens inside a Docker container under
    # network_mode: host - see the docstring on _get_lan_ip). Whatever
    # this environment's real address is, it must not be loopback.
    ip = _get_lan_ip()
    assert not ipaddress.ip_address(ip).is_loopback


def test_get_lan_ip_uses_a_udp_route_lookup_not_hostname_resolution():
    # Pins the actual mechanism (connect+getsockname on a UDP socket)
    # rather than only the loopback-avoidance outcome, so a future
    # accidental reversion back to gethostbyname()-based resolution
    # would fail here even in an environment where that happened to
    # still return a non-loopback address.
    fake_socket = MagicMock()
    fake_socket.getsockname.return_value = ("192.168.1.42", 54321)
    fake_socket.__enter__.return_value = fake_socket

    with patch("socket.socket", return_value=fake_socket) as mock_socket_cls:
        ip = _get_lan_ip()

    mock_socket_cls.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)
    fake_socket.connect.assert_called_once()
    assert ip == "192.168.1.42"

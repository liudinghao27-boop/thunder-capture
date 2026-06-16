"""Tests for URL security helper."""

from unittest.mock import patch

import pytest

from server.services.url_security import is_safe_webhook_url


@pytest.mark.parametrize("url", [
    "",
    "not-a-url",
    "ftp://example.com/hook",
    "http://example.com/hook",
])
def test_rejects_non_https_or_malformed_urls(url):
    assert is_safe_webhook_url(url) is False


@pytest.mark.parametrize("url", [
    "https://localhost/hook",
    "https://127.0.0.1/hook",
    "https://0.0.0.0/hook",
    "https://10.0.0.1/hook",
    "https://10.255.255.255/hook",
    "https://172.16.0.1/hook",
    "https://172.31.255.255/hook",
    "https://192.168.1.1/hook",
    "https://169.254.1.1/hook",
    "https://224.0.0.1/hook",
    "https://240.0.0.1/hook",
])
def test_rejects_private_reserved_loopback_multicast_urls(url):
    assert is_safe_webhook_url(url) is False


@patch("server.services.url_security.socket.gethostbyname")
def test_rejects_hostname_resolving_to_private_ip(mock_gethost):
    mock_gethost.return_value = "10.0.0.5"
    assert is_safe_webhook_url("https://internal.example.com/hook") is False


@patch("server.services.url_security.socket.gethostbyname")
def test_rejects_hostname_that_fails_resolution(mock_gethost):
    import socket
    mock_gethost.side_effect = socket.gaierror("Name or service not known")
    assert is_safe_webhook_url("https://does-not-exist.example.com/hook") is False


@patch("server.services.url_security.socket.gethostbyname")
def test_accepts_public_https_webhook_url(mock_gethost):
    mock_gethost.return_value = "8.8.8.8"
    assert is_safe_webhook_url("https://example.com/hook") is True


@patch("server.services.url_security.socket.gethostbyname")
def test_blocks_http_url_even_with_public_resolution(mock_gethost):
    mock_gethost.return_value = "8.8.8.8"
    assert is_safe_webhook_url("http://example.com/hook") is False

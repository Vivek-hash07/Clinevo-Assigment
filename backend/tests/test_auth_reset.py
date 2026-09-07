from unittest.mock import MagicMock, patch
import socket

from app.security import normalize_reset_token
from app.services.mail import open_smtp, smtp_ipv4_addresses


def test_normalize_reset_token_strips_mail_wrapping():
    token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_"
    wrapped = f"<\n{token[:20]}\n{token[20:]}>"
    assert normalize_reset_token(wrapped) == token


def test_normalize_reset_token_decodes_query_encoding():
    assert normalize_reset_token("abc%2Ddef") == "abc-def"


def test_smtp_ipv4_addresses_ignore_ipv6():
    v4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("13.60.144.171", 0))
    v6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("64:ff9b::d3c:90ab", 0, 0, 0))
    with patch("app.services.mail.socket.getaddrinfo", return_value=[v6, v4]):
        assert smtp_ipv4_addresses("smtp.example") == ["13.60.144.171"]


def test_open_smtp_connects_via_ipv4_and_keeps_hostname_for_tls():
    v4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("13.60.144.171", 0))
    smtp = MagicMock()

    def connect(ip, port):
        smtp._host = ip

    def starttls(**_kwargs):
        assert smtp._host == "smtp.example"

    smtp.connect.side_effect = connect
    smtp.starttls.side_effect = starttls
    with (
        patch("app.services.mail.socket.getaddrinfo", return_value=[v4]),
        patch("app.services.mail.smtplib.SMTP", return_value=smtp),
    ):
        opened = open_smtp("smtp.example", 587, use_tls=True)
    assert opened is smtp
    smtp.connect.assert_called_once_with("13.60.144.171", 587)
    smtp.starttls.assert_called_once()
    assert smtp._host == "smtp.example"

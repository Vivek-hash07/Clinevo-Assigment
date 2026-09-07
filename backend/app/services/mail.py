from __future__ import annotations

import smtplib
import socket
import ssl
from email import policy
from email.message import EmailMessage
from html import escape

from app.config import Settings, get_settings


def smtp_ipv4_addresses(host: str) -> list[str]:
    """IPv4 only. Dual-stack hosts often return NAT64 AAAA records that hang on Render."""
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return []
    addresses: list[str] = []
    for family, _socktype, _proto, _canon, sockaddr in infos:
        if family != socket.AF_INET:
            continue
        ip = sockaddr[0]
        if ip not in addresses:
            addresses.append(ip)
    return sorted(addresses)


def open_smtp(host: str, port: int, *, use_tls: bool, timeout: float = 20) -> smtplib.SMTP:
    context = ssl.create_default_context()
    implicit_ssl = port == 465
    ipv4s = smtp_ipv4_addresses(host)
    targets = ipv4s or [host]
    last_exc: Exception | None = None
    for target in targets:
        try:
            if implicit_ssl:
                smtp = smtplib.SMTP_SSL(timeout=timeout, context=context)
            else:
                smtp = smtplib.SMTP(timeout=timeout)
            # SNI during SMTP_SSL.connect() reads _host before connect() overwrites it.
            smtp._host = host
            smtp.connect(target, port)
            # Python 3.11+ connect() sets _host to the IP; STARTTLS must see the hostname
            # or certificate verification fails with "IP address mismatch".
            smtp._host = host
            if use_tls and not implicit_ssl:
                smtp.starttls(context=context)
            return smtp
        except Exception as exc:
            last_exc = exc
    assert last_exc is not None
    raise last_exc


def send_mail(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
) -> None:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from:
        raise RuntimeError("SMTP is not available")

    # Default RFC wrapping at 78 chars splits reset URLs and corrupts the token.
    message = EmailMessage(policy=policy.SMTP.clone(max_line_length=998))
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for filename, mime, blob in attachments or []:
        maintype, _, subtype = mime.partition("/")
        message.add_attachment(
            blob,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=filename,
        )

    with open_smtp(
        settings.smtp_host,
        settings.smtp_port,
        use_tls=settings.smtp_use_tls,
    ) as smtp:
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def send_password_reset(to_email: str, name: str, reset_url: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    greeting = name.strip() or "there"
    safe_greeting = escape(greeting)
    safe_reset_url = escape(reset_url, quote=True)
    text = (
        f"Hello {greeting},\n\n"
        "We received a request to reset the password for your Clinevo Smart Inbox account.\n"
        "Open this link within 30 minutes to choose a new password:\n"
        f"<{reset_url}>\n\n"
        "If you did not request this, you can ignore this email.\n"
    )
    html = f"""
    <div style="font-family:Georgia,serif;background:#f3efe6;padding:32px">
      <div style="max-width:520px;margin:0 auto;background:#fffdf8;border:1px solid #d8d0c2;border-radius:16px;padding:28px">
        <p style="color:#1c6b58;letter-spacing:.14em;text-transform:uppercase;font-size:12px;margin:0 0 12px">Clinevo · Smart Inbox</p>
        <h1 style="font-size:22px;color:#14241f;margin:0 0 12px">Reset your password</h1>
        <p style="color:#3d4f48;line-height:1.55">Hello {safe_greeting}, we received a request to reset the password for this account.</p>
        <p style="margin:24px 0">
          <a href="{safe_reset_url}" style="background:#0d3b32;color:#f7f3ea;text-decoration:none;padding:12px 18px;border-radius:10px;font-weight:600">Choose a new password</a>
        </p>
        <p style="color:#3d4f48;font-size:14px;line-height:1.5">This link expires in 30 minutes. If you did not request a reset, you can ignore this message.</p>
      </div>
    </div>
    """
    send_mail(to_email, "Reset your Clinevo password", text, html)

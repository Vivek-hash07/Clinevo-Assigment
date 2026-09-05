from __future__ import annotations

import smtplib
from email.message import EmailMessage
from html import escape

from app.config import Settings, get_settings


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

    message = EmailMessage()
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

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
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
        f"Open this link within 30 minutes to choose a new password:\n{reset_url}\n\n"
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

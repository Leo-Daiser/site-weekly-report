from __future__ import annotations

import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.models import SMTPConfig


def smtp_config_from_env(
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    from_email: str | None = None,
    from_name: str | None = None,
    use_tls: bool | None = None,
) -> SMTPConfig:
    def _env_bool(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on")

    resolved_host = host or os.environ.get("SMTP_HOST", "")
    resolved_from = from_email or os.environ.get("SMTP_FROM_EMAIL", "")
    if not resolved_host:
        raise ValueError("SMTP_HOST is required for sending email")
    if not resolved_from:
        raise ValueError("SMTP_FROM_EMAIL is required for sending email")

    return SMTPConfig(
        host=resolved_host,
        port=port if port is not None else int(os.environ.get("SMTP_PORT", "587")),
        username=username if username is not None else os.environ.get("SMTP_USERNAME"),
        password=password if password is not None else os.environ.get("SMTP_PASSWORD"),
        from_email=resolved_from,
        from_name=from_name or os.environ.get("SMTP_FROM_NAME"),
        use_tls=use_tls if use_tls is not None else _env_bool("SMTP_USE_TLS", True),
    )


def _attach_file(message: EmailMessage, path: Path) -> None:
    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type is None:
        mime_type = "application/octet-stream"
    maintype, subtype = mime_type.split("/", 1)
    message.add_attachment(
        path.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=path.name,
    )


def send_email_with_attachments(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None,
    attachments: list[Path],
    smtp_config: SMTPConfig,
) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = (
        f"{smtp_config.from_name} <{smtp_config.from_email}>"
        if smtp_config.from_name
        else smtp_config.from_email
    )
    message["To"] = to_email
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    for attachment in attachments:
        if attachment.is_file():
            _attach_file(message, attachment)

    with smtplib.SMTP(smtp_config.host, smtp_config.port, timeout=60) as smtp:
        if smtp_config.use_tls:
            smtp.starttls()
        if smtp_config.username:
            smtp.login(smtp_config.username, smtp_config.password or "")
        smtp.send_message(message)

"""Sending an alert by email.

Deliberately small and deliberately quiet about its own failures. This is
called from the watchdog, whose job is to keep watching; a sender that raised
on a refused SMTP connection would take down the only thing that notices the
recorder has stopped, in order to complain that it could not complain.

So `send` returns whether it worked and never raises. The caller logs the
outcome and carries on, and a mail server that is down costs an alert rather
than the watch.

Nothing here logs the password, the recipient or the body. An address in a log
is an address in a log, and the log is what gets pasted into a chat window when
something goes wrong.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from libs.config import Settings
from libs.observability.logging import get_logger

logger = get_logger(__name__)

TIMEOUT_SECONDS = 20.0

# The port that means implicit TLS. Everything else is treated as submission
# with STARTTLS, which is what 587 and 25 both want.
IMPLICIT_TLS_PORT = 465


@dataclass(frozen=True, slots=True)
class Alert:
    """One thing worth telling someone about."""

    subject: str
    body: str


@dataclass(frozen=True, slots=True)
class Delivery:
    """What happened when we tried to send it."""

    attempted: bool
    sent: bool
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"attempted": self.attempted, "sent": self.sent, "error": self.error}


def send(alert: Alert, *, settings: Settings) -> Delivery:
    """Send one alert, or report why it could not be sent.

    Unconfigured alerting is not a failure. It is the default, and a watchdog
    on a host that was never given a mail server should say "nothing to send
    it to" rather than "sending failed" — the two ask different things of
    whoever reads the journal.
    """
    if not settings.alerting_configured:
        return Delivery(attempted=False, sent=False, error="alerting is not configured")

    message = EmailMessage()
    message["Subject"] = alert.subject
    message["From"] = settings.alert_email_from
    message["To"] = settings.alert_email_to
    message.set_content(alert.body)

    try:
        # STARTTLS on the submission port, implicit TLS on 465. Both are in use
        # and guessing wrong fails in a way that reads like a firewall problem.
        if settings.alert_smtp_port == IMPLICIT_TLS_PORT:
            with smtplib.SMTP_SSL(
                settings.alert_smtp_host,
                settings.alert_smtp_port,
                timeout=TIMEOUT_SECONDS,
                context=ssl.create_default_context(),
            ) as server:
                _authenticate(server, settings)
                server.send_message(message)
        else:
            with smtplib.SMTP(
                settings.alert_smtp_host, settings.alert_smtp_port, timeout=TIMEOUT_SECONDS
            ) as server:
                server.starttls(context=ssl.create_default_context())
                _authenticate(server, settings)
                server.send_message(message)
    except Exception as exc:  # noqa: BLE001 - reported, never raised: see the module docstring
        # The type and message only. An SMTP error can quote the envelope back,
        # and the envelope holds the recipient.
        reason = f"{type(exc).__name__}"
        logger.warning("alert_not_sent", extra={"error": reason})
        return Delivery(attempted=True, sent=False, error=reason)

    logger.info("alert_sent", extra={"subject": alert.subject})
    return Delivery(attempted=True, sent=True)


def _authenticate(server: smtplib.SMTP, settings: Settings) -> None:
    """Log in only when a credential was given.

    A relay on localhost usually wants none, and offering an empty username is
    an authentication failure rather than an anonymous send.
    """
    if settings.alert_smtp_user and settings.alert_smtp_password:
        server.login(settings.alert_smtp_user, settings.alert_smtp_password)

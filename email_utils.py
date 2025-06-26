# email_utils.py

import os
from email.message import EmailMessage
import aiosmtplib

from datetime import timedelta
from fastapi import BackgroundTasks

from auth import create_access_token        # your JWT helper
from .email_backend import _actually_send_email  # your existing send function

# SMTP config from .env
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")


async def send_magic_link_email(to_email: str, link_url: str):
    """
    Send the magic-link login email to `to_email`.
    """
    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = "Your Magic Login Link – SigStream"
    msg.set_content(
        f"Click this link to log in:\n\n{link_url}\n\n"
        f"This link is valid for 10 minutes."
    )

    await aiosmtplib.send(
        msg,
        hostname=SMTP_HOST,
        port=SMTP_PORT,
        username=SMTP_USER,
        password=SMTP_PASS,
        use_tls=True
    )


def send_confirmation_email(
    background_tasks: BackgroundTasks,
    to_email: str,
    base_url: str = "https://sigstreamcloud.com/"
):
    """
    Sends a 24-hour confirmation link to `to_email`.
    `base_url` can be overridden, but defaults to your production domain.
    """
    # 1) Create a JWT with a custom “type” claim for email confirmation
    token = create_access_token(
        data={"sub": to_email, "type": "email_confirm"},
        expires_delta=timedelta(hours=24)
    )

    # 2) Build the confirmation URL, stripping any trailing slash
    confirm_link = f"{base_url.rstrip('/')}/confirm-email?token={token}"

    # 3) Compose the email
    subject = "Please Confirm Your Email – SigStream"
    body = (
        f"Hi there!\n\n"
        f"Thanks for signing up. Please confirm your email address by clicking the link below:\n\n"
        f"{confirm_link}\n\n"
        f"This link will expire in 24 hours.\n\n"
        f"If you didn't sign up for SigStream, you can safely ignore this message."
    )

    # 4) Enqueue the send via your backend
    background_tasks.add_task(_actually_send_email, to_email, subject, body)

# email_utils.py

import os
from email.message import EmailMessage
import aiosmtplib
from datetime import timedelta
from fastapi import BackgroundTasks

from auth import create_access_token
from email_backend import _actually_send_email   # absolute import, not relative

# SMTP settings from env
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")


async def send_magic_link_email(to_email: str, link_url: str):
    # """
    # Send a one-time magic login link that expires in 10 minutes.
    # """
    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = "Your Magic Login Link - SigStream"
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
    base_url: str
):
    # """
    # Queue a 24-hour email confirmation link. 
    # base_url should be something like "https://sigstreamcloud.com/".
    # """
    # 1) Create a JWT with a custom "type" claim
    token = create_access_token(
        data={"sub": to_email, "type": "email_confirm"},
        expires_delta=timedelta(hours=24)
    )

    # 2) Build the confirmation URL
    confirm_link = f"{base_url}confirm-email?token={token}"

    # 3) Craft the message
    subject = "Please confirm your email"
    body = (
        f"Hi there!\n\n"
        f"Thanks for signing up. Please confirm your email address by clicking the link below:\n\n"
        f"{confirm_link}\n\n"
        f"This link will expire in 24 hours.\n\n"
        f"If you didn't sign up, you can ignore this email."
    )

    # 4) Hand off to your existing SMTP sender
    background_tasks.add_task(_actually_send_email, to_email, subject, body)




    BUG_REPORT_TO = os.getenv("BUG_REPORT_TO", "admin@sigstreamcloud.com")

def send_bug_report_email(
    background_tasks: BackgroundTasks,
    subject: str,
    body: str,
    to_email: str | None = None,
):
    """
    Queue a bug-report email via the existing SMTP backend.
    """
    background_tasks.add_task(
        _actually_send_email,
        to_email or BUG_REPORT_TO,
        subject,
        body,
    )

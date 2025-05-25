# email_utils.py

import os
from email.message import EmailMessage
import aiosmtplib

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")


async def send_magic_link_email(to_email: str, link_url: str):
    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = "Your Magic Login Link - SigStream"
    msg.set_content(f"Click this link to log in:\n\n{link_url}\n\nThis link is valid for 10 minutes.")

    await aiosmtplib.send(
        msg,
        hostname=SMTP_HOST,
        port=SMTP_PORT,
        username=SMTP_USER,
        password=SMTP_PASS,
        use_tls=True
    )

# email_backend.py

import os
from email.message import EmailMessage
import aiosmtplib

# Pull these in from your environment
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

async def _actually_send_email(to_email: str, subject: str, body: str):
    # """
    # Send a plain‐text email via SMTP. Used by send_confirmation_email()
    # and can also be reused elsewhere.
    # """
    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname=SMTP_HOST,
        port=SMTP_PORT,
        username=SMTP_USER,
        password=SMTP_PASS,
        use_tls=True,
    )

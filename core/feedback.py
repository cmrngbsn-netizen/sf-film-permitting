"""Bug reports and feature requests from the app, sent to the feedback inbox through Gmail.

The address and its Gmail app password live in Streamlit's secrets, never in this public repo:

    [feedback]
    address = "the inbox"
    app_password = "from the Google account's App passwords page"
"""

import re
import smtplib
from email.message import EmailMessage

KINDS = ["Bug", "Feature request", "Other"]
MAX_TEXT = 5000
MAX_PER_VISIT = 5  # the link is public, so one visit can only send so many
MIN_GAP_S = 20     # seconds between reports from one visit
SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 587
TIMEOUT_S = 15
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def problem(text, reply_to=""):
    """What's wrong with a report, in words for the person writing it, or None."""
    if not text.strip():
        return "Write a few words first."
    if reply_to.strip() and not EMAIL.fullmatch(reply_to.strip()):
        return "That email doesn't look right. Leave it blank if you don't need a reply."
    return None


def too_soon(sent_at, at):
    """Why this visit can't send another report at time `at`, given when it sent the others, or None."""
    if len(sent_at) >= MAX_PER_VISIT:
        return "Thanks, that's the most one visit can send. Reload the page to send more."
    if sent_at and at - sent_at[-1] < MIN_GAP_S:
        return "Just sent one. Give it a few seconds and try again."
    return None


def build(address, kind, text, reply_to="", details=(), request_json=None):
    """The email for a report. `details` are (label, value) pairs about where it was sent from."""
    text = text.strip()
    message = EmailMessage()
    message["Subject"] = f"[SF Parking {kind}] {' '.join(text.split())[:60]}"
    message["From"] = address
    message["To"] = address
    if reply_to.strip():
        message["Reply-To"] = reply_to.strip()
    lines = [text, "", "---", f"Reply to: {reply_to.strip() or 'not given'}"]
    message.set_content("\n".join(lines + [f"{label}: {value}" for label, value in details]))
    if request_json:
        message.add_attachment(request_json.encode(), maintype="application", subtype="json",
                               filename="request.json")
    return message


def send(settings, message):
    """Sends through the inbox's own Gmail account. Raises smtplib.SMTPException or OSError."""
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT_S) as server:
        server.starttls()
        server.login(settings["address"], settings["app_password"].replace(" ", ""))
        server.send_message(message)

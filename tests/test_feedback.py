"""Feedback reports: checks, limits and the email they become."""

import smtplib

from core import feedback
from core.feedback import MAX_PER_VISIT, MIN_GAP_S, build, problem, send, too_soon


def test_problems():
    assert problem("  ") == "Write a few words first."
    assert problem("It broke", "not an email").startswith("That email")
    assert problem("It broke") is None and problem("It broke", "a@b.co") is None


def test_limits():
    assert too_soon([], 100) is None
    assert too_soon([100], 100 + MIN_GAP_S - 1).startswith("Just sent")
    assert too_soon([100], 100 + MIN_GAP_S) is None
    assert too_soon([0] * MAX_PER_VISIT, 10000).startswith("Thanks")


def test_email():
    message = build("inbox@example.com", "Bug", "The map\nwon't load " + "x" * 100, "tester@example.com",
                    [("Step", "2 · Locations & curbs")])
    # A line break in the report can't reach the headers.
    assert message["Subject"].startswith("[SF Parking Bug] The map won't load x")
    assert len(message["Subject"]) < 90
    assert message["To"] == message["From"] == "inbox@example.com"
    assert message["Reply-To"] == "tester@example.com"
    body = message.get_content()
    assert "Reply to: tester@example.com" in body and "Step: 2 · Locations & curbs" in body
    assert not list(message.iter_attachments())


def test_email_without_reply_address_or_with_a_request():
    message = build("inbox@example.com", "Other", "Hi", request_json='{"a": 1}')
    assert message["Reply-To"] is None and "Reply to: not given" in message.get_body().get_content()
    attached = next(message.iter_attachments())
    assert attached.get_filename() == "request.json" and attached.get_content() == b'{"a": 1}'


def test_send_logs_in_and_sends(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append((host, port))
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def starttls(self):
            calls.append("tls")
        def login(self, user, password):
            calls.append((user, password))
        def send_message(self, message):
            calls.append(message["Subject"])

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    message = build("inbox@example.com", "Bug", "Hi")
    # Google shows app passwords with spaces in them.
    send({"address": "inbox@example.com", "app_password": "abcd efgh"}, message)
    assert calls == [(feedback.SMTP_HOST, feedback.SMTP_PORT), "tls", ("inbox@example.com", "abcdefgh"),
                     "[SF Parking Bug] Hi"]

import imaplib
import sys
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.email_models import EmailEnvelope, EmailQuery


class FakeImapConnection:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.search_result = ("OK", [b"1 2 3 4"])
        self.fetch_failures: set[bytes] = set()

    def login(self, username, password):
        self.calls.append(("login", username, password))
        return "OK", [b"logged in"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"4"]

    def search(self, *args):
        self.calls.append(("search", *args))
        return self.search_result

    def fetch(self, message_id, query):
        self.calls.append(("fetch", message_id, query))
        if message_id in self.fetch_failures:
            return "NO", [b"private-body-must-not-leak"]
        return "OK", [(b"RFC822", b"raw-" + message_id)]

    def logout(self):
        self.calls.append(("logout",))
        return "BYE", [b"logged out"]

    def store(self, *args):
        raise AssertionError(f"write command store called: {args!r}")

    def copy(self, *args):
        raise AssertionError(f"write command copy called: {args!r}")

    def move(self, *args):
        raise AssertionError(f"write command move called: {args!r}")

    def expunge(self, *args):
        raise AssertionError(f"write command expunge called: {args!r}")


def parsed_envelope(raw_message: bytes, *, max_body_chars: int) -> EmailEnvelope:
    message_number = int(raw_message.rsplit(b"-", 1)[-1])
    return EmailEnvelope(
        message_id=f"message-{message_number}",
        subject=f"Subject {message_number}",
        sender="sender@example.invalid",
        recipients=("student@example.invalid",),
        sent_at=datetime(2026, 7, message_number, tzinfo=timezone.utc),
        body_text="Body"[:max_body_chars],
        attachments=(),
    )


class EmailImapServiceTests(unittest.TestCase):
    def setUp(self):
        self.connection = FakeImapConnection()
        self.query = EmailQuery(date(2026, 7, 21), date(2026, 7, 22), limit=2)

    def service(self, **overrides):
        from apps.qq_ai_bridge.services.email_imap_service import EmailImapService

        values = {
            "host": "imap.example.invalid",
            "port": 993,
            "username": "private-user@example.invalid",
            "password": "private-client-password",
            "mailbox": "INBOX",
            "timeout_seconds": 17,
            "parser": parsed_envelope,
            "max_body_chars": 1234,
        }
        values.update(overrides)
        return EmailImapService(**values)

    def fetch(self, **service_overrides):
        with patch(
            "apps.qq_ai_bridge.services.email_imap_service.imaplib.IMAP4_SSL",
            return_value=self.connection,
        ) as factory:
            result = self.service(**service_overrides).fetch(self.query)
        return result, factory

    def test_connects_with_ssl_and_timeout(self):
        _, factory = self.fetch()

        factory.assert_called_once_with("imap.example.invalid", 993, timeout=17)

    def test_logs_in_and_selects_mailbox_readonly(self):
        self.fetch()

        self.assertIn(
            ("login", "private-user@example.invalid", "private-client-password"),
            self.connection.calls,
        )
        self.assertIn(("select", "INBOX", True), self.connection.calls)

    def test_search_uses_since_and_before_end_plus_one(self):
        self.fetch()

        self.assertIn(
            ("search", None, "SINCE", "21-Jul-2026", "BEFORE", "23-Jul-2026"),
            self.connection.calls,
        )

    def test_fetches_newest_ids_up_to_limit(self):
        envelopes, _ = self.fetch()

        fetch_calls = [call for call in self.connection.calls if call[0] == "fetch"]
        self.assertEqual(
            fetch_calls,
            [("fetch", b"4", "(RFC822)"), ("fetch", b"3", "(RFC822)")],
        )
        self.assertEqual([item.message_id for item in envelopes], ["message-3", "message-4"])

    def test_empty_search_returns_empty_list(self):
        self.connection.search_result = ("OK", [b""])

        envelopes, _ = self.fetch()

        self.assertEqual(envelopes, [])
        self.assertFalse(any(call[0] == "fetch" for call in self.connection.calls))

    def test_partial_fetch_failure_is_reported_without_secret(self):
        from apps.qq_ai_bridge.services.email_imap_service import EmailImapError

        self.connection.fetch_failures.add(b"3")
        with (
            patch(
                "apps.qq_ai_bridge.services.email_imap_service.imaplib.IMAP4_SSL",
                return_value=self.connection,
            ),
            self.assertRaises(EmailImapError) as caught,
        ):
            self.service().fetch(self.query)

        self.assertEqual(caught.exception.code, "email_protocol_error")
        error_text = str(caught.exception)
        self.assertNotIn("private-user", error_text)
        self.assertNotIn("private-client-password", error_text)
        self.assertNotIn("private-body", error_text)

    def test_logout_runs_after_parser_failure(self):
        from apps.qq_ai_bridge.services.email_imap_service import EmailImapError

        def failing_parser(_raw_message: bytes, *, max_body_chars: int):
            raise ValueError(f"parser saw secret body at limit {max_body_chars}")

        with self.assertRaises(EmailImapError) as caught:
            self.fetch(parser=failing_parser)

        self.assertEqual(caught.exception.code, "email_parse_error")
        self.assertEqual(self.connection.calls[-1], ("logout",))
        self.assertNotIn("secret body", str(caught.exception))

    def test_client_never_calls_store_copy_move_or_expunge(self):
        self.fetch()

        called_names = {call[0] for call in self.connection.calls}
        self.assertTrue({"store", "copy", "move", "expunge"}.isdisjoint(called_names))

    def test_missing_credentials_raise_config_error(self):
        from apps.qq_ai_bridge.services.email_imap_service import EmailImapError

        with self.assertRaises(EmailImapError) as caught:
            self.service(password="").fetch(self.query)

        self.assertEqual(caught.exception.code, "email_config_error")

    def test_login_failure_is_auth_error(self):
        from apps.qq_ai_bridge.services.email_imap_service import EmailImapError

        def reject_login(_username, _password):
            raise imaplib.IMAP4.error("server echoed private-client-password")

        self.connection.login = reject_login
        with (
            patch(
                "apps.qq_ai_bridge.services.email_imap_service.imaplib.IMAP4_SSL",
                return_value=self.connection,
            ),
            self.assertRaises(EmailImapError) as caught,
        ):
            self.service().fetch(self.query)

        self.assertEqual(caught.exception.code, "email_auth_error")
        self.assertNotIn("private-client-password", str(caught.exception))

    def test_connection_failure_is_network_error(self):
        from apps.qq_ai_bridge.services.email_imap_service import EmailImapError

        with (
            patch(
                "apps.qq_ai_bridge.services.email_imap_service.imaplib.IMAP4_SSL",
                side_effect=OSError("network includes private-client-password"),
            ),
            self.assertRaises(EmailImapError) as caught,
        ):
            self.service().fetch(self.query)

        self.assertEqual(caught.exception.code, "email_network_error")
        self.assertNotIn("private-client-password", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import auth


class _FakeDeleteQuery:
    def __init__(self) -> None:
        self.deleted = False

    def filter(self, *args):  # noqa: ANN002
        return self

    def delete(self, synchronize_session=False):  # noqa: ANN001
        self.deleted = True
        return 1


class _FakeSession:
    def __init__(self) -> None:
        self.query_object = _FakeDeleteQuery()
        self.committed = False
        self.closed = False

    def query(self, model):  # noqa: ANN001
        return self.query_object

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


class AuthSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        auth.reset_login_rate_limiter()
        self.settings = SimpleNamespace(
            admin_username="admin",
            admin_password_hash="unused",
            session_secret="test-session-secret",
            session_ttl_seconds=3600,
            login_max_attempts=2,
            login_window_seconds=60,
            login_block_seconds=120,
        )

    def tearDown(self) -> None:
        auth.reset_login_rate_limiter()

    def test_session_token_has_expiry_and_rejects_expired_payload(self) -> None:
        with patch("app.auth.settings", self.settings), patch(
            "app.auth.time.time", return_value=1_000
        ):
            token, token_id = auth.create_session_token("admin")
            payload = auth.verify_session_token(token)

        self.assertEqual(payload["tid"], token_id)
        self.assertEqual(payload["iat"], 1_000)
        self.assertEqual(payload["exp"], 4_600)

        with patch("app.auth.settings", self.settings), patch(
            "app.auth.time.time", return_value=4_601
        ):
            with self.assertRaisesRegex(ValueError, "Token expired"):
                auth.verify_session_token(token)

    def test_login_rate_limit_blocks_username_and_client_buckets(self) -> None:
        with patch("app.auth.settings", self.settings):
            self.assertEqual(auth.check_login_rate_limit("admin", "1.2.3.4"), 0)
            self.assertEqual(auth.record_login_failure("admin", "1.2.3.4"), 0)
            retry_after = auth.record_login_failure("admin", "1.2.3.4")
            self.assertGreater(retry_after, 0)
            self.assertGreater(auth.check_login_rate_limit("admin", "9.9.9.9"), 0)
            auth.clear_login_failures("admin", "1.2.3.4")
            self.assertEqual(auth.check_login_rate_limit("admin", "1.2.3.4"), 0)

    def test_logout_revokes_server_side_session_row(self) -> None:
        from app.main import logout

        fake_session = _FakeSession()
        with patch("app.main.SessionLocal", return_value=fake_session):
            result = logout({"sub": "admin", "tid": "token-1"})

        self.assertEqual(result, {"ok": True})
        self.assertTrue(fake_session.query_object.deleted)
        self.assertTrue(fake_session.committed)
        self.assertTrue(fake_session.closed)


if __name__ == "__main__":
    unittest.main()

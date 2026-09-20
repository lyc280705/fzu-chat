from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
import redis

from app import auth, runtime_state, session_crypto
from app.jwch_client import JwchClient


class SessionSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        executable = shutil.which("redis-server")
        if not executable:
            raise unittest.SkipTest("A local Redis executable is required for integration checks")
        cls.directory = tempfile.TemporaryDirectory(prefix="fzu-redis-test-", dir="/tmp")
        cls.socket = str(Path(cls.directory.name) / "redis.sock")
        cls.process = subprocess.Popen([executable, "--port", "0", "--unixsocket", cls.socket,
                                        "--save", "", "--appendonly", "no"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.redis = redis.Redis(unix_socket_path=cls.socket, decode_responses=True)
        for _ in range(100):
            try:
                cls.redis.ping()
                break
            except redis.ConnectionError:
                time.sleep(0.02)
        else:
            cls.process.terminate()
            cls.directory.cleanup()
            raise RuntimeError("Test Redis did not start")

    @classmethod
    def tearDownClass(cls):
        cls.redis.close()
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.directory.cleanup()

    def setUp(self):
        self.redis.flushdb()  # Dedicated temporary test instance only.
        self.enterContext(patch.object(runtime_state, "REDIS_URL", "redis://test-only"))
        self.enterContext(patch.object(runtime_state, "_redis_client", self.redis))
        self.enterContext(patch.object(runtime_state, "_redis_checked", True))
        self.enterContext(patch.dict(os.environ, {"FZU_CHAT_SESSION_ENCRYPTION_KEY": Fernet.generate_key().decode()}))
        self.enterContext(patch.object(auth, "USERS_DIR", Path(self.directory.name) / "users"))
        session_crypto.session_cipher.cache_clear()
        self.addCleanup(session_crypto.session_cipher.cache_clear)

    def connected_state(self):
        return {"edu_authenticated": True, "edu_cookies": [{"name": "sid", "value": "sensitive-test-cookie-value"}],
                "edu_identifier": "sensitive-test-identifier", "edu_status_message": "", "edu_session_expires_at": time.time() + 300}

    def test_redis_credentials_are_encrypted_and_token_keys_are_hashed(self):
        first = auth.create_session("student")
        second = auth.create_session("student")
        auth.update_user_edu_session("student", self.connected_state())
        self.assertTrue(auth.get_session(second)["edu_authenticated"])
        for key in self.redis.scan_iter():
            self.assertNotIn(first, key)
            self.assertNotIn(second, key)
            value = self.redis.get(key)
            self.assertNotIn("sensitive-test-cookie-value", value)
            self.assertNotIn("sensitive-test-identifier", value)
            self.assertIn("ciphertext", value)

    def test_atomic_revision_protects_reconnected_redis_session(self):
        token = auth.create_session("student")
        auth.update_user_edu_session("student", self.connected_state())
        old_revision = auth.get_session(token)["edu_revision"]
        auth.update_user_edu_session("student", self.connected_state())
        changed = auth.update_user_edu_session("student", {"edu_authenticated": False}, expected_revision=old_revision)
        self.assertFalse(changed)
        self.assertTrue(auth.get_session(token)["edu_authenticated"])

    def test_legacy_session_migration_preserves_token_and_expiry(self):
        token = "legacy-test-token"
        legacy = {"user_id": "student", "student_type": "undergraduate", "created_at": time.time(), **self.connected_state()}
        self.redis.set(f"session:{token}", json.dumps(legacy), ex=120)
        self.assertEqual(auth.migrate_legacy_sessions(), 1)
        self.assertFalse(self.redis.exists(f"session:{token}"))
        self.assertTrue(auth.get_session(token)["edu_authenticated"])
        self.assertLessEqual(self.redis.ttl(auth._session_key(token)), 120)
        self.assertEqual(auth.migrate_legacy_sessions(), 0)

    def test_tampered_or_plaintext_new_session_is_rejected(self):
        token = auth.create_session("student")
        self.redis.set(auth._session_key(token), json.dumps({"user_id": "another-student", "created_at": time.time()}))
        self.assertIsNone(auth.get_session(token))

    def test_account_revocation_removes_shared_ciphertext(self):
        first = auth.create_session("student")
        second = auth.create_session("student")
        auth.update_user_edu_session("student", self.connected_state())
        self.assertEqual(auth.invalidate_user_sessions("student"), 2)
        self.assertIsNone(auth.get_session(first))
        self.assertIsNone(auth.get_session(second))
        self.assertFalse(self.redis.exists(auth._edu_session_key("student")))

    def test_corrupt_shared_state_does_not_reactivate_legacy_cookies(self):
        token = auth.create_session("student", edu_authenticated=True, edu_cookies=[{"name": "sid", "value": "old"}])
        self.redis.set(auth._edu_session_key("student"), json.dumps({"edu_authenticated": True}))
        session = auth.get_session(token)
        self.assertFalse(session["edu_authenticated"])
        self.assertIsNone(session["edu_cookies"])

    def test_production_missing_key_fails_closed(self):
        with patch.dict(os.environ, {"FZU_CHAT_SESSION_ENCRYPTION_KEY": "", "FZU_CHAT_SESSION_ENCRYPTION_KEY_FILE": "/nonexistent/test-key"}):
            session_crypto.session_cipher.cache_clear()
            with self.assertRaises(RuntimeError):
                session_crypto.session_cipher()

    def test_teaching_system_tls_verification_is_enabled(self):
        with patch.dict(os.environ, {"FZU_CHAT_JWCH_CA_BUNDLE": ""}):
            self.assertIs(JwchClient("test-student").session.verify, True)

    def test_key_generator_creates_private_key_and_refuses_overwrite(self):
        path = Path(self.directory.name) / "generated.key"
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/generate-session-key.py"), "--path", str(path)]
        result = subprocess.run(command, check=True, text=True, capture_output=True)
        original = path.read_bytes()
        Fernet(original.strip())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(original.decode().strip(), result.stdout)
        repeated = subprocess.run(command, text=True, capture_output=True)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()

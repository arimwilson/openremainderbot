"""usage.claude(): a 401 with a stored token triggers one CLI refresh and one retry."""
import os
import unittest
from unittest import mock

from remainderbot import usage

BODY = {
    "five_hour": {"utilization": 11.0, "resets_at": "2026-09-23T20:30:00Z"},
    "seven_day": {"utilization": 9.0, "resets_at": "2026-09-23T23:20:00Z"},
}


def unauthorized(*_a, **_k):
    raise usage.UsageError("claude: HTTP 401 from usage endpoint")


class ClaudeRefreshOn401(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("CLAUDE_OAUTH_TOKEN", None)
        self.addCleanup(self.env.stop)
        # tokens as read before and after the refresh
        self.tokens = mock.patch.object(usage, "claude_token", side_effect=["stale", "fresh"])
        self.token_mock = self.tokens.start()
        self.addCleanup(self.tokens.stop)
        self.refresh = mock.patch.object(usage, "refresh_claude_token")
        self.refresh_mock = self.refresh.start()
        self.addCleanup(self.refresh.stop)

    def test_401_then_refresh_then_retry_succeeds(self):
        calls = []

        def fetch(token, timeout):
            calls.append(token)
            if token == "stale":
                unauthorized()
            return BODY

        with mock.patch.object(usage, "_fetch_claude_usage", side_effect=fetch):
            u = usage.claude()
        self.assertEqual(u.weekly.used_pct, 9.0)
        self.assertEqual(calls, ["stale", "fresh"])
        self.refresh_mock.assert_called_once_with()

    def test_401_persists_after_refresh(self):
        with mock.patch.object(usage, "_fetch_claude_usage", side_effect=unauthorized):
            with self.assertRaises(usage.UsageError) as cm:
                usage.claude()
        self.assertIn("after a CLI token refresh", str(cm.exception))
        self.refresh_mock.assert_called_once_with()

    def test_refresh_failure_is_reported_not_retried(self):
        self.refresh_mock.side_effect = usage.UsageError("claude: token refresh via CLI exited 1: logged out")
        with mock.patch.object(usage, "_fetch_claude_usage", side_effect=unauthorized) as fetch:
            with self.assertRaises(usage.UsageError) as cm:
                usage.claude()
        self.assertIn("token refresh via CLI", str(cm.exception))
        self.assertEqual(fetch.call_count, 1)

    def test_non_401_errors_do_not_refresh(self):
        def too_many(*_a, **_k):
            raise usage.UsageError("claude: HTTP 429 from usage endpoint")

        with mock.patch.object(usage, "_fetch_claude_usage", side_effect=too_many):
            with self.assertRaises(usage.UsageError) as cm:
                usage.claude()
        self.assertIn("429", str(cm.exception))
        self.refresh_mock.assert_not_called()

    def test_env_token_is_never_refreshed(self):
        os.environ["CLAUDE_OAUTH_TOKEN"] = "from-env"
        with mock.patch.object(usage, "_fetch_claude_usage", side_effect=unauthorized) as fetch:
            with self.assertRaises(usage.UsageError) as cm:
                usage.claude()
        self.assertIn("401", str(cm.exception))
        self.assertEqual(fetch.call_count, 1)
        self.refresh_mock.assert_not_called()


class RefreshCommand(unittest.TestCase):
    def test_runs_cli_from_home_and_reports_nonzero_exit(self):
        done = mock.Mock(returncode=1, stdout="", stderr="Not logged in\nPlease run /login\n")
        with mock.patch.object(usage.subprocess, "run", return_value=done) as run:
            with self.assertRaises(usage.UsageError) as cm:
                usage.refresh_claude_token()
        self.assertIn("exited 1: Please run /login", str(cm.exception))
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:2], ["claude", "-p"])
        self.assertIn("--model", cmd)
        self.assertEqual(run.call_args.kwargs["stdin"], usage.subprocess.DEVNULL)

    def test_success_is_silent(self):
        done = mock.Mock(returncode=0, stdout="ok\n", stderr="")
        with mock.patch.object(usage.subprocess, "run", return_value=done):
            usage.refresh_claude_token()


class ParseClaude(unittest.TestCase):
    def test_idle_five_hour_window_has_no_reset(self):
        body = {**BODY, "five_hour": {"utilization": 0.0, "resets_at": None}}
        u = usage.parse_claude(body)
        self.assertEqual(u.five_hour, usage.Window(0.0, None))
        self.assertEqual(u.weekly.used_pct, 9.0)

    def test_null_weekly_reset_is_a_usage_error(self):
        body = {**BODY, "seven_day": {"utilization": 9.0, "resets_at": None}}
        with self.assertRaises(usage.UsageError):
            usage.parse_claude(body)


if __name__ == "__main__":
    unittest.main()

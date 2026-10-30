"""origin.strip_credentials(): what is left of a push URL before it reaches a log line,
doctor's output, or gh's `--repo`."""
import unittest

from remainderbot import origin


class StripCredentials(unittest.TestCase):
    def test_credentials_are_dropped(self):
        cases = {
            "https://x-access-token:secret@github.com/you/bot.git": "https://github.com/you/bot.git",
            "https://oauth2:ghp_abc123@github.com/you/bot.git": "https://github.com/you/bot.git",
            "https://token@github.com/you/bot.git": "https://github.com/you/bot.git",
            "http://user:pw@github.example.com:8443/you/bot.git": "http://github.example.com:8443/you/bot.git",
            "HTTPS://user:pw@github.com/you/bot.git": "HTTPS://github.com/you/bot.git",
            # an unencoded "/" or "@" in the password: the first used to survive whole, the
            # second used to leave its tail behind as a user name
            "https://user:hunter/2+x@github.com/you/bot.git": "https://github.com/you/bot.git",
            "https://user:hunter@2@github.com/you/bot.git": "https://github.com/you/bot.git",
            "https://user:a/b@c/d=@github.com/you/bot.git": "https://github.com/you/bot.git",
        }
        for url, want in cases.items():
            with self.subTest(url=url):
                self.assertEqual(origin.strip_credentials(url), want)

    def test_urls_without_a_password_are_unchanged(self):
        for url in ("https://github.com/you/bot.git",
                    "https://github.example.com:8443/you/bot.git",
                    "git@github.com:you/bot.git",
                    "ssh://git@github.com/you/bot.git",
                    "/srv/git/bot.git",
                    "file:///srv/git/bot.git"):
            with self.subTest(url=url):
                self.assertEqual(origin.strip_credentials(url), url)


class Redact(unittest.TestCase):
    def test_git_errors_lose_the_password(self):
        cases = {
            "fatal: unable to access 'https://user:hunter/2+x@github.com/you/bot.git/': URL rejected":
                "fatal: unable to access 'https://github.com/you/bot.git/': URL rejected",
            'fatal: repository "https://tok@github.com/you/bot.git" not found':
                'fatal: repository "https://github.com/you/bot.git" not found',
            "error: failed to push some refs to 'https://user:hunter@2@github.com/you/bot.git'":
                "error: failed to push some refs to 'https://github.com/you/bot.git'",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(origin.redact(text), want)

    def test_other_text_is_unchanged(self):
        for text in ("fatal: unable to access 'https://github.com/you/bot.git/': Could not resolve host",
                     "fatal: 'git@github.com:you/bot.git' does not appear to be a git repository",
                     "To https://github.com/you/bot.git rejected; ask admin@example.com"):
            with self.subTest(text=text):
                self.assertEqual(origin.redact(text), text)


if __name__ == "__main__":
    unittest.main()

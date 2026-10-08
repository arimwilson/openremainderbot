"""sources.toml validation: defaults, and every error naming the file and the source."""
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from remainderbot import sources
from remainderbot.config import Config

REPO_SOURCES = Path(__file__).resolve().parent.parent / "sources.toml"


class Valid(unittest.TestCase):
    def test_defaults(self):
        [tasks, issues] = sources.parse(
            'version = 1\n[[sources]]\nname = "tasks"\ntype = "gws-tasks"\n'
            '[[sources]]\nname = "issues"\ntype = "gh-issues"\nowner = "you"\nprivate = true\n'
            'description = "mine"\nrecheck = "look again"\nenabled = false\nmax_chars = 10\n')
        self.assertEqual((tasks.name, tasks.type, tasks.filename), ("tasks", "gws-tasks", "tasks.md"))
        self.assertEqual((tasks.private, tasks.enabled, tasks.max_chars), (False, True, sources.DEFAULT_MAX_CHARS))
        self.assertEqual(tasks.description, "Open Google Tasks with due dates and notes")  # the adapter's
        self.assertIn("still open", tasks.recheck)
        self.assertEqual((issues.private, issues.enabled, issues.max_chars), (True, False, 10))
        self.assertEqual((issues.description, issues.recheck), ("mine", "look again"))
        self.assertEqual(issues.fields, {"name": "issues", "type": "gh-issues", "owner": "you", "private": True,
                                         "description": "mine", "recheck": "look again", "enabled": False,
                                         "max_chars": 10})

    def test_no_sources(self):
        self.assertEqual(sources.parse("version = 1\nsources = []\n"), [])

    def test_parts_take_a_glob_or_an_array(self):
        [notes] = sources.parse(
            'version = 1\n[[sources]]\nname = "notes"\ntype = "gh-markdown"\nrepo = "you/notes"\n'
            '[[sources.parts]]\ninclude = "a/*.md"\n'
            '[[sources.parts]]\ninclude = ["b.md", "c/**"]\nexclude = "c/x.md"\n')
        self.assertEqual(notes.fields["parts"], [{"include": "a/*.md"},
                                                 {"include": ["b.md", "c/**"], "exclude": "c/x.md"}])

    @unittest.skipUnless(REPO_SOURCES.exists(), "this checkout has no sources.toml")
    def test_this_instance(self):
        srcs = sources.load(Config(repo_dir=REPO_SOURCES.parent))
        self.assertTrue(srcs)


class Errors(unittest.TestCase):
    def assertError(self, text: str, message: str):
        """`message` is the whole error after `sources.toml:` (with the line, for syntax)."""
        with self.assertRaises(sources.ConfigError) as cm:
            sources.parse(text)
        self.assertEqual(str(cm.exception), f"sources.toml:{message}")

    def assertErrorStarts(self, text: str, prefix: str):
        with self.assertRaises(sources.ConfigError) as cm:
            sources.parse(text)
        self.assertTrue(str(cm.exception).startswith(f"sources.toml: {prefix}"), str(cm.exception))

    def test_syntax_errors_name_the_line(self):
        self.assertError('version = 1\n[[sources]]\nname = "t\n', "3: Illegal character '\\n'")
        self.assertError('version = 1\nversion = 2\n', "2: Cannot overwrite a value")
        self.assertError('version = 1\nsources = [\n', " Invalid value (at end of document)")

    def test_top_level(self):
        self.assertError("", " missing `version = 1`")
        self.assertError("sources = []\n", " missing `version = 1`")
        self.assertError("version = 2\nsources = []\n", " unsupported version 2; this remainderbot reads version 1")
        self.assertError("version = true\nsources = []\n", " unsupported version True; this remainderbot reads version 1")
        self.assertError('version = "1"\nsources = []\n', " unsupported version '1'; this remainderbot reads version 1")
        self.assertError("version = 1\n", " missing `sources`; add a [[sources]] table for each source")
        self.assertError('version = 1\nsources = "tasks"\n', " `sources` must be an array of tables, one [[sources]] per source")
        self.assertError("version = 1\nsources = []\nextra = 1\n", " unknown key 'extra'; the top level has `version` and `sources`")
        self.assertError('version = 1\nsources = ["tasks"]\n', " source 1 must be a table ([[sources]])")

    def test_name_and_type(self):
        self.assertError('version = 1\n[[sources]]\ntype = "gws-tasks"\n', " source 1 is missing `name`")
        self.assertError('version = 1\n[[sources]]\nname = "t"\n', " source 1 is missing `type`")
        self.assertError('version = 1\n[[sources]]\nname = "Tasks"\ntype = "gws-tasks"\n',
                         " source 1: name 'Tasks' must be lowercase letters, digits, and dashes")
        self.assertErrorStarts('version = 1\n[[sources]]\nname = "t"\ntype = "gmail"\n',
                               "source 't': unknown type 'gmail'; known types: command, file, gh-issues")
        self.assertError('version = 1\n[[sources]]\nname = "t"\ntype = "gws-tasks"\n'
                         '[[sources]]\nname = "u"\ntype = "gws-tasks"\n'
                         '[[sources]]\nname = "t"\ntype = "gws-tasks"\n', " duplicate name 't' (sources 1 and 3)")

    def test_fields(self):
        head = 'version = 1\n[[sources]]\nname = "s"\n'
        self.assertErrorStarts(head + 'type = "gh-roadmaps"\nrepo = ["you/app"]\n', "source 's': unknown field 'repo'; allowed: ")
        self.assertError(head + 'type = "gh-roadmaps"\n', " source 's': missing `repos`")
        self.assertError(head + 'type = "gh-roadmaps"\nrepos = "you/app"\n', " source 's': `repos` must be an array of strings")
        self.assertError(head + 'type = "gh-roadmaps"\nrepos = ["you/app", 3]\n', " source 's': `repos` must be an array of strings")
        self.assertError(head + 'type = "gh-issues"\nowner = "you"\nlimit = "lots"\n', " source 's': `limit` must be an integer")
        self.assertError(head + 'type = "gh-issues"\nowner = "you"\nlimit = 1.5\n', " source 's': `limit` must be an integer")
        self.assertError(head + 'type = "gh-issues"\nowner = "you"\nlimit = true\n', " source 's': `limit` must be an integer")
        self.assertError(head + 'type = "gws-tasks"\nprivate = "yes"\n', " source 's': `private` must be true or false")
        self.assertError(head + 'type = "gws-tasks"\nmax_chars = 0\n', " source 's': `max_chars` must be at least 1")
        self.assertError(head + 'type = "gws-doc"\ndoc_id = 12345\n', " source 's': `doc_id` must be a string")

    def test_adapter_checks(self):
        head = 'version = 1\n[[sources]]\nname = "s"\n'
        either = " source 's': set either `owner` (every repo it owns) or `repos`, not both"
        self.assertError(head + 'type = "gh-issues"\n', either)
        self.assertError(head + 'type = "gh-issues"\nowner = "you"\nrepos = ["you/app"]\n', either)
        self.assertError(head + 'type = "gh-issues"\nowner = "you"\nlimit = 0\n', " source 's': `limit` must be at least 1")
        self.assertError(head + 'type = "gh-roadmaps"\nrepos = []\n', " source 's': `repos` is empty")
        self.assertErrorStarts(head + "type = \"gh-roadmaps\"\nrepos = [\"a/b\"]\npattern = '(todo'\n",
                               "source 's': `pattern` is not a valid regular expression")

    def test_parts(self):
        head = 'version = 1\n[[sources]]\nname = "s"\ntype = "gh-markdown"\nrepo = "you/notes"\n'
        self.assertError(head + 'parts = "wiki/*.md"\n', " source 's': `parts` must be an array of tables")
        self.assertError(head + "parts = []\n", " source 's': `parts` is empty; add a [[sources.parts]] table")
        self.assertError(head + 'parts = ["wiki/*.md"]\n', " source 's': `parts` item 1 must be a table")
        self.assertError(head + '[[sources.parts]]\ninclude = "a.md"\n[[sources.parts]]\ntitle = "x"\n',
                         " source 's': `parts` item 2: missing `include`")
        self.assertErrorStarts(head + '[[sources.parts]]\ninclude = "a.md"\nsection = ["Now"]\n',
                               "source 's': `parts` item 1: unknown field 'section'")
        self.assertError(head + '[[sources.parts]]\ninclude = "a.md"\nlatest = "yes"\n',
                         " source 's': `parts` item 1: `latest` must be true or false")
        self.assertError(head + '[[sources.parts]]\ninclude = ["a.md", 2]\n',
                         " source 's': `parts` item 1: `include` must be a string or an array of strings")
        self.assertError(head + '[[sources.parts]]\ninclude = "a.md"\nsections = ["A"]\nfrontmatter = ["b"]\n',
                         " source 's': `parts` item 1: set `sections` or `frontmatter`, not both")
        self.assertError(head + '[[sources.parts]]\ninclude = "a.md"\nsections = []\n',
                         " source 's': `parts` item 1: `sections` is empty")


class Load(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td, True)

    def test_missing_file(self):
        with self.assertRaisesRegex(sources.ConfigError, r"^sources\.toml: not found$"):
            sources.load(Config(repo_dir=self.td))

    def test_bytes_that_are_not_utf8_name_their_line(self):
        (self.td / "sources.toml").write_bytes(b"version = 1\n# caf\xe9\nsources = []\n")
        with self.assertRaises(sources.ConfigError) as cm:
            sources.load(Config(repo_dir=self.td))
        self.assertEqual(str(cm.exception), "sources.toml:2: not valid UTF-8 (invalid continuation byte)")
        (self.td / "sources.toml").write_bytes("version = 1\n# café\nsources = []\n".encode())
        self.assertEqual(sources.load(Config(repo_dir=self.td)), [])

    def test_sources_file_relative_to_the_repo_or_absolute(self):
        (self.td / "conf").mkdir()
        (self.td / "conf" / "s.toml").write_text('version = 1\n[[sources]]\nname = "t"\ntype = "nope"\n')
        with mock.patch.dict(os.environ, {"REPO_DIR": str(self.td), "SOURCES_FILE": "conf/s.toml"}):
            config = Config.from_env()
        self.assertEqual(config.sources_path, self.td.resolve() / "conf" / "s.toml")
        with self.assertRaisesRegex(sources.ConfigError, r"^conf/s\.toml: source 't': unknown type"):
            sources.load(config)
        elsewhere = Config(repo_dir=self.td / "repo", sources_file=str(self.td / "conf" / "s.toml"))
        self.assertEqual(elsewhere.sources_path, self.td / "conf" / "s.toml")
        with self.assertRaisesRegex(sources.ConfigError, "^" + re.escape(f"{self.td}/conf/s.toml: source 't'")):
            sources.load(elsewhere)


if __name__ == "__main__":
    unittest.main()

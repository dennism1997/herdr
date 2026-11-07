"""Offline integration tests against real disposable Git repositories."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import sync_upstream


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream = self.root / "upstream"
        self.origin = self.root / "origin.git"
        self.work = self.root / "work"
        self.run_git(self.root, "init", "-b", "master", str(self.upstream))
        self.commit(self.upstream, "shared.txt", "base\n")
        self.run_git(self.root, "clone", "--bare", str(self.upstream), str(self.origin))
        self.run_git(self.root, "clone", str(self.origin), str(self.work))

    def run_git(self, repo, *args):
        result = subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=Test", "-c",
             "user.email=test@example.invalid", "-c", "commit.gpgsign=false", *args],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        return result.stdout.strip()

    def commit(self, repo, filename, contents):
        (repo / filename).write_text(contents, encoding="utf-8")
        self.run_git(repo, "add", filename)
        self.run_git(repo, "commit", "-m", "test: change " + filename)
        return self.run_git(repo, "rev-parse", "HEAD")

    def sync(self):
        return sync_upstream.sync(self.work, str(self.upstream))

    def tip(self):
        return self.run_git(self.origin, "rev-parse", "master")

    def test_up_to_date_is_noop(self):
        before = self.tip()
        self.assertIn("Already up to date", self.sync())
        self.assertEqual(before, self.tip())

    def test_fast_forward_and_repeat(self):
        incoming = self.commit(self.upstream, "incoming.txt", "upstream\n")
        self.assertIn("Synced upstream", self.sync())
        self.assertEqual(incoming, self.tip())
        self.assertIn("Already up to date", self.sync())

    def test_merge_preserves_local_commits_and_unrelated_refs(self):
        local = self.commit(self.work, "local.txt", "our patch\n")
        self.run_git(self.work, "push", "origin", "master", "master:custom")
        self.run_git(self.work, "tag", "local-release")
        self.run_git(self.work, "push", "origin", "refs/tags/local-release")
        incoming = self.commit(self.upstream, "incoming.txt", "upstream\n")
        self.sync()
        self.run_git(self.origin, "merge-base", "--is-ancestor", local, "master")
        self.run_git(self.origin, "merge-base", "--is-ancestor", incoming, "master")
        self.assertEqual("our patch", self.run_git(self.origin, "show", "master:local.txt"))
        self.assertEqual(local, self.run_git(self.origin, "rev-parse", "custom"))
        self.assertEqual(local, self.run_git(self.origin, "rev-parse", "local-release"))
        self.assertTrue(self.run_git(self.origin, "show", "-s", "--format=%s", "master").startswith("chore:"))

    def test_local_commits_ahead_of_upstream_are_preserved(self):
        local = self.commit(self.work, "local.txt", "our patch\n")
        self.run_git(self.work, "push", "origin", "master")
        self.assertIn("Already up to date", self.sync())
        self.assertEqual(local, self.tip())

    def test_conflict_aborts_without_changing_remote(self):
        self.commit(self.work, "shared.txt", "our change\n")
        self.run_git(self.work, "push", "origin", "master")
        before = self.tip()
        self.commit(self.upstream, "shared.txt", "upstream change\n")
        with self.assertRaisesRegex(RuntimeError, "shared.txt"):
            self.sync()
        self.assertEqual(before, self.tip())
        self.assertEqual(before, self.run_git(self.work, "rev-parse", "HEAD"))
        self.assertEqual("", self.run_git(self.work, "status", "--porcelain"))

    def test_dirty_checkout_is_rejected(self):
        (self.work / "untracked").write_text("keep me", encoding="utf-8")
        before = self.tip()
        with self.assertRaisesRegex(RuntimeError, "clean disposable checkout"):
            self.sync()
        self.assertEqual(before, self.tip())
        self.assertEqual("keep me", (self.work / "untracked").read_text())

    def test_missing_upstream_does_not_push(self):
        before = self.tip()
        with self.assertRaises(subprocess.CalledProcessError):
            sync_upstream.sync(self.work, str(self.root / "missing"))
        self.assertEqual(before, self.tip())

    def test_concurrent_destination_update_is_not_overwritten(self):
        self.commit(self.upstream, "incoming.txt", "upstream\n")
        other = self.root / "other"
        self.run_git(self.root, "clone", str(self.origin), str(other))
        concurrent = self.commit(other, "concurrent.txt", "someone else's patch\n")
        original_git = sync_upstream.git

        def git_with_race(repo, *args, **kwargs):
            if args and args[0] == "push":
                self.run_git(other, "push", "origin", "master")
            return original_git(repo, *args, **kwargs)

        with patch.object(sync_upstream, "git", side_effect=git_with_race):
            with self.assertRaises(subprocess.CalledProcessError):
                self.sync()
        self.assertEqual(concurrent, self.tip())
        self.sync()
        self.assertEqual("someone else's patch", self.run_git(self.origin, "show", "master:concurrent.txt"))
        self.assertEqual("upstream", self.run_git(self.origin, "show", "master:incoming.txt"))


if __name__ == "__main__":
    unittest.main()

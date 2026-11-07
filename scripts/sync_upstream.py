"""Merge upstream master into origin/master without rewriting either history.

Run only in a disposable, clean checkout (as the sync workflow does).
"""

import os
from pathlib import Path
import subprocess
import sys


UPSTREAM = "https://github.com/herdrdev/herdr.git"


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check,
    )


def sync(repo, upstream=UPSTREAM):
    if git(repo, "status", "--porcelain").stdout:
        raise RuntimeError("Sync requires a clean disposable checkout")
    git(repo, "fetch", "--no-tags", "origin", "master")
    git(repo, "checkout", "--detach", "refs/remotes/origin/master")
    original = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "fetch", "--no-tags", upstream, "master")
    incoming = git(repo, "rev-parse", "FETCH_HEAD").stdout.strip()
    if git(repo, "merge-base", "--is-ancestor", incoming, "HEAD", check=False).returncode == 0:
        return "Already up to date with upstream master."

    merge = git(repo, "-c", "user.name=github-actions[bot]",
                "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "-c", "commit.gpgsign=false", "merge", "--no-edit",
                "-m", f"chore: sync upstream master ({incoming[:12]})", incoming, check=False)
    if merge.returncode:
        conflicts = git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip()
        if git(repo, "rev-parse", "--verify", "MERGE_HEAD", check=False).returncode == 0:
            git(repo, "merge", "--abort")
        raise RuntimeError("Upstream merge failed; origin/master was not changed.\n"
                           + (conflicts or merge.stderr or merge.stdout))

    # A normal push rejects concurrent changes to master; never force or retry
    # by replacing the destination with our stale checkout.
    git(repo, "push", "origin", "HEAD:refs/heads/master")
    merged = git(repo, "rev-parse", "HEAD").stdout.strip()
    return f"Synced upstream master {incoming} into master: {original} → {merged}."


def main():
    try:
        message = sync(Path.cwd())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        message = str(error)
        if isinstance(error, subprocess.CalledProcessError):
            message += "\n" + error.stderr
        status = 1
    else:
        status = 0
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            # Indent untrusted Git output so it stays plain text in Markdown.
            output.write("## Upstream sync\n\n" + "\n".join("    " + line for line in message.splitlines()) + "\n")
    return status


if __name__ == "__main__":
    sys.exit(main())

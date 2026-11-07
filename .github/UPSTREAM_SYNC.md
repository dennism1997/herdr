# Upstream syncing

This personal fork automatically merges `herdrdev/herdr:master` into
`dennism1997/herdr:master` every six hours, at 00:17, 06:17, 12:17 and 18:17 UTC.
GitHub may delay scheduled runs. Run it immediately from **Actions → Sync
upstream → Run workflow**, selecting `master`, or with:

```sh
gh workflow run sync-upstream.yml --repo dennism1997/herdr --ref master
```

Local commits are preserved with a normal Git merge. An already incorporated
upstream commit is a no-op. Conflicts abort the merge and fail the workflow;
the run summary lists conflicting paths and `master` stays unchanged. Resolve
those conflicts manually in a PR, then rerun the sync. Concurrent updates to
`master` cause a rejected push rather than overwriting someone else's work;
the next run starts again from the latest `master`.

Only `master` is synced. Other branches, tags and releases are not updated or
deleted. Documentation CI fetches upstream release tags into its temporary
checkout for provenance checks; it does not push those tags to this fork.
No upstream issues or PRs are created. The workflow uses the built-in
`GITHUB_TOKEN` with `contents: write`, without an additional secret. Its pushes
do not trigger GitHub's push workflows, so a sync does not automatically run
the full application CI or publish builds/releases. The sync's Git integration
tests run before every attempt; application CI can be run through a normal PR.

For local validation, use `just sync-upstream-test`. The script itself must only
run in a disposable checkout: it detaches HEAD at the current `origin/master`.

# Development and CI policy

Use CI.md for all subsequent development. The revised user policy supersedes the
former all-OS required matrix. Use a branch and PR. The sole normal required check
is `StarRoute / FreeBSD required`: all existing regression tests, CLI and isolated
Telnet scenarios on FreeBSD / Python 3.12. Missing, failed or cancelled runs block merge.

Linux-dependent changes and Linux release candidates require the manual Linux
Compatibility workflow on Rocky; it runs selected OS tests and a short real Door smoke.
Ubuntu Compatibility is manual for Ubuntu-specific work. Extended Tests selects one
hosted OS and Python version manually. Solaris is not required. Linux distribution
installation/service packages are not implemented or claimed verified by runtime smoke.

Reuse existing successful results for the same commit; do not rerun them unnecessarily.
New commits cancel superseded runs of the same workflow/branch. No automatic retries
or automatic fix loops. Investigate existing failure logs and run only needed checks.
PR and main push are distinct commit checks; do not manually duplicate either.

Only trusted main and owner-authored same-repository PRs can use the home runner.
External PRs never access it and cannot pass the required gate without review and
porting to an owner-authored branch. Preserve the root-owned admission hook, existing
SSH host verification, shared per-VM lock and heartbeat cancellation. Manual native
workflows are main-only. No production data, deployment, Liner CI changes or service restarts.

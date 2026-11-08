# Development and CI policy

Use the CI in `CI.md` for every subsequent feature, fix, refactor and release candidate.
Start from current main, use a branch and PR, and update relevant tests. Never disable tests or
relax the gate to obtain a passing result. Require both `StarRoute / Required` and `StarRoute / Native required` before merging.
After integration verify `StarRoute / Native required` for the exact main commit on FreeBSD,
Rocky Linux and Ubuntu. Failed or incomplete native CI blocks release/package promotion.

External PRs use GitHub-hosted runners only. Home runners/SSH hosts execute main and
owner-authored same-repository PRs to main. Review external contributions and port them to
an owner-authored same-repository PR before integration. Manual dispatch is main-only. Preserve the root-owned runner admission hook; workflow guards alone are not
the trust boundary. Never use production keys/worlds, deploy, or restart shared services for CI.
Keep Liner Notes and StarRoute workspaces/artifacts separate. Use the shared per-host lock and
heartbeat cancellation. Cleanup only the current StarRoute run. Report skipped/unsupported
platforms and distinguish synthetic, native and actual Telnet results.

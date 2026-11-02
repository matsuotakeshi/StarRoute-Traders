# GitHub update: v0.20.0

Private publication authorized on 2026-11-02. This update contains the v0.20.0 implementation, three private Ports, compiled FreeBSD packages, test-signed local repository, and immutable acceptance evidence under distribution/v0.20.0. The self-contained ZIP is distribution/starroute-traders-0.20.0-freebsd.zip (SHA-256 592aefcc0482386c5473815e266b5f655ad0352a2e6124907457973f07f730b5).

Both Windows and FreeBSD passed 485 tests (468 existing + 17 new). Actual pkg install/upgrade/rollback/delete, all 39 database tables, 11 runtime/config/log files, non-root rc.d operation, and Liner notes Telnet workflows were verified in isolation. The runtime source and distfile bytes are unchanged by publication. The frozen acceptance snapshot records github_pushed=false at its original completion; it is retained as historical evidence, not current publication status.

Only a test repository public key and signatures are included, never its private key. No live DB, site profile, SSH configuration, authentication token, or generated private universe package is included. Do not treat the test signing key as the production repository trust anchor. Packages are private deployment artifacts, not a public FreeBSD Ports submission.

Production migration has not been performed in this publication task. docs/PKG_MIGRATION_V020.md uses the user's previously reported standalone paths and includes initial installation, backup, Door switch, rollback, and future signed-repository commands. Liner notes itself is not packaged by this release. Its existing Door integration and the current world remain under administrator control.

# GitHub update: v0.19.0

Verified BBS UI source, 468 passing tests on Windows and FreeBSD (430 regression + 38 UI), and isolated Liner notes Telnet evidence are in verification/bbs-ui-v0.19.0. See BBS_UI_COMPLETE.md and docs/BBS_UI_DEPLOYMENT.md. Production has not been changed. Runtime/test source bytes match the tested source-manifest; publication adds documentation and curated evidence only. Large release archives and protected-server file inventories remain local.

# GitHub snapshot: v0.18.0

This repository imports the completed Phase 5 source snapshot and its verification evidence. It includes the prior Phase 3/4 acceptance records, but does not invent Git commit history for earlier releases.

- Windows / Python 3.14.7: 430 tests passed.
- FreeBSD / Python 3.12.15: 430 tests passed.
- Actual isolated Liner notes Telnet and two-site shared-world scenarios passed.
- See verification/phase5/REPORT.md and PHASE5_COMPLETE.md.
- verification/phase5/source-manifest.json records the original tested source snapshot. Only .gitignore was extended for publication; .gitattributes, this note and verification/ were added. Runtime and test source bytes are preserved.
- No runtime databases, generated private universe packages, credentials, TLS private keys or SSH settings are included.
- This is a source repository, not the universe distribution repository. Do not upload active universe packages here or distribute the full repository to participant BBS sites.
- Production deployment is a separate authorized operation.

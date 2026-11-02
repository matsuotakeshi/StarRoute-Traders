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

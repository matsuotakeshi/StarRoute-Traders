# StarRoute Traders 0.20.0 — private Ports and long-duration rules

This document describes the implementation and operating boundaries. Actual acceptance results and package hashes are supplied separately in the release's verification checklist and logs.

## Package boundaries

games/starroute-traders-client owns only starroute_bbs, Door/node launchers and remote.json.sample. It has no engine, generator, world database or signing keys.
games/starroute-traders owns the common engine, offline generator and trusted management tools. It depends on the matching client version for standalone Door operation. LocalDoor shares the master operation implementation, so those Python modules belong to this common package, not to the thin client.
games/starroute-traders-master depends on the matching common package and adds the rc.d service and master.json.sample. No files overlap.

Python is selected by USES=python:3.10+,run; launchers use the framework's PYTHON_CMD with isolated mode. The client declares the matching py-sqlite3 dependency (FreeBSD packages SQLite separately); the common engine inherits it. Code is installed under libexec/starroute-traders, not mixed with mutable data. Packages do not create worlds, change Door registrations, rotate keys, stop/start services or run migrations.

## Local distfiles and build

The private source repository is not a universe-data repository or pkg repository. There is no assumed GitHub release URL. Run scripts/build_ports_distfile.py to create a deterministic source archive and SHA-256 distinfo, then preseed poudriere DISTFILES_CACHE. Use an independent poudriere configuration, FreeBSD 15.1 amd64 jail and private Ports overlay. Build all three games/starroute-traders origins. Do not edit the host's production Ports or pkg configuration.

## Configuration and service

@sample installs defaults only if the target is absent; edited settings survive updates/deletion. Runtime DBs, hall records, private packages, keys, certificates and logs are not in any pkg plist.
The master service is disabled by default. Explicitly provision a dedicated non-root account and private data/log directories, configure starroute_master_user/config, then use service starroute_master start/stop/restart/status. No package hooks perform these operations. The service does not restart endlessly after crashes; inspect logs and restart explicitly. Standalone/clients have no daemon.

## Maintenance and recovery

Stop game writers and reconcile pending request IDs before changing installed program versions. Save the old pkg files and private configuration. starroute-maintain --db PATH check performs read-only schema/integrity/FK checks. backup --output NEW_DB creates an exclusive SQLite backup. migrate-copy --backup NEW_BACKUP --output NEW_MIGRATED_DB migrates only a new copy, records success/failure and never switches a live DB. Inspect and activate it separately while writers remain stopped. Old runtime's historical migration compatibility is retained; pkg never invokes it.
Before restoring an old pkg, use check --supported-max-schema N --supported-rules-version VERSION and confirm that its rules are supported too. A schema number alone does not certify new rule semantics. Do not use 0.19.0 with a new world_events rule catalog. Keep compatible source/pkg and DB snapshots together; never overwrite a DB with post-backup committed trades without reconciling them.
pkg delete removes program files, not operational data. Full data removal remains a separate explicit administrator action.

## Time rules

Existing DB catalogs remain authoritative and unchanged by installation. The new game.json.sample / examples/long-duration-template.json is an opt-in template for new universes: normal ship navigation is provisionally 720 seconds per generated distance unit, with a provisional minimum time-distance of 10 units (nearby routes=at least 2h, 10 units=2h,30=6h,60=12h,120=24h). Engineering ships retain slower travel; warp ratios and fuel prices remain explicit tables. Use starroute-universe with this template and the example generator/industry-level parameters, then the existing registry/activation workflow. No live universe is automatically regenerated or switched.
Global world-event intervals are 7200 seconds. Provisional occurrence probability is 100/10000 (1%) and kind weights are 1:1:1; these are adjustable shared rules, not final balance. Each UTC interval makes at most one global draw and selects one planet if it occurs. Misses and hits persist, and disaster effects/news share the same transaction. Old catalogs retain legacy behavior until an explicit new-world transition. Voyage events and mining retain their independent existing interval; production and market cycles are unchanged. New rules change the configuration hash; dynamic time-slot records do not.
World progress is computed from authoritative wall time with persisted slots. No standalone daemon is needed: later operations recover elapsed time in bounded transactions, including after process restart. Administrators may explicitly schedule starroute-maintain --db PATH tick for eager materialization; pkg does not install a cron job. No simulated extra time is advanced by a screen redraw. Closed rounds do not advance. Long-duration tests use injected clocks, not hours of real waiting.

## Liner notes

After explicit approval, change the existing administrator-owned Door wrapper to exec PREFIX/bin/starroute-door --config EXISTING_DOOR_JSON. Preserve BBS-provided identity, existing paths and the native PTY/NAWS adapter. Do not automatically append doors.conf. Keep the prior wrapper for rollback. No Liner notes package is supplied in this change.

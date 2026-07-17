# Turnkey workflow

## New vault

Run bootstrap with an explicit `HERMES_HOME`, profile, owner, and absolute vault path. Review dry-run output, apply, install, then run doctor with smoke testing. Repeating bootstrap must create nothing new.

## Existing vault

The first pass is read-only. Record missing roots, metadata coverage, sensitivity markers, optional OKF markers, and Git state. Do not move notes. Apply only runtime config and managed skills until a separate migration plan is approved.

## Daily operation

Pull by intent, write a Brain Delta, run health-check, rebuild FTS5, and verify with a representative query. Git commit/push follows config policy and may remain disabled.

## Rollback

The install inventory records managed runtime files and hashes. Uninstall removes unmodified managed artifacts only. The vault path is reported and preserved.

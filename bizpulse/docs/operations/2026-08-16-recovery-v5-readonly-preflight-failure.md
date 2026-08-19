# Recovery V5 Read-Only Preflight Failure — 2026-08-16

Status: V5 approved once, invoked once, stopped before receipt and retired.

## Bound package

- Package: `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md`
- SHA-256: `656e8df0951f4b98d67eaf00067a2a2ba99571dfb92d64c1142040b49791f4ab`
- Authorization ID: `75bbbbb4-69e9-4b38-921e-08f64b0bd6cf`
- Controller result: `deployed_execution_readonly_stage_failed`
- V5 execution receipt: absent

## Exact stop boundary

The first Azure `containerapp show` returned exit code `0`. The local
deployed-state verifier then stopped before revision, Job, registry, Keychain,
health, browser, capacity, expiry, restart or rollback work.

The app retained the approved candidate image/revision, 100% traffic,
single-revision mode, external ingress, AI-disabled environment and replica
bounds `minReplicas=1`, `maxReplicas=1`. Azure also returned platform-owned
defaults `cooldownPeriod=300`, `pollingInterval=30` and `rules=null`. V5
incorrectly compared the whole scale mapping with only the two approved bounds.

No Keychain item or OpenAI Key was read. No paid request or Azure mutation was
made. V5 is retired and must not be replayed or manually resumed.

# Deployed Release Diagnostic D2 Failure Closeout

Status: failed and permanently consumed. This record grants no replay,
successor execution, or hosted-state authority.

## Immutable safe receipt facts

- Package SHA-256:
  `b53e8b8215eec8c208085999ff6a0046b8415b722e5844a1ac4e0d729a18e08f`
- Authorization ID: `ce1811a2-2d89-4f11-b1ba-3dcb40e4a6fb`
- Status: `failed`
- Completed reads: `6`
- Failure: `diagnostic_application_drift / application / application`
- Observation: absent

## Boundary

D2 does not identify the field that caused this result. It does not prove a
hosted failure. D2 is immutable and must never be replayed: do not regenerate
it under the D2 identity, retry it, delete a receipt to reuse it, or issue a
manual diagnostic request on its behalf.

This closeout contains only the safe receipt facts above. It intentionally does
not include ARM values, resource values, subscription identifiers, tokens,
passwords, or command output.

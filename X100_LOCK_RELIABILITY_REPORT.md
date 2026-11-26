# X100 JobLock reliability report

Audit date: 2026-11-26
Repository: Ayushjaiswal0001/youtube
Verified main: b16c4b5fd0d8cd6731d11dde40fc3a7d49b52d8f
Focused candidate: 7d6ffe0 on codex/fix-joblock-ownership; not merged

## Previous failure mode

The pre-fix lock relied on expiring metadata and did not renew ownership throughout production rendering. Concurrent stale-lock cleanup could remove a replacement instance, and a shared job ID could not distinguish successive owners. The prior owner reported PR #22 merged; live GitHub verification confirms PR #22 merged as commit 6c52d38ac48963f9a37d1aadd5139e0e3453d768, producing current main b16c4b5. The remaining JobLock repair is separate and remains a branch candidate.

## Ownership protocol

- A stable sibling file with suffix .guard is opened and locked by the OS. The guard is never deleted or atomically replaced by JobLock.
- POSIX uses nonblocking exclusive flock. Windows uses nonblocking exclusive LockFileEx on byte range zero.
- A cryptographically random UUID token is created for every successful acquisition and stored with protocol version, PID, host, job identity, and heartbeat time.
- Metadata updates use an owner-token-specific temporary file and atomic replacement. The heartbeat confirms both that the open guard is still the same filesystem object and that metadata still carries this owner's token.
- Heartbeat renewal begins on acquisition and repeats every 30 seconds for the production 3,600-second TTL. Age alone never establishes staleness.
- Reclamation consists of acquiring the kernel lock. The kernel serializes competing reclaimers; there is no unlink-and-recreate window. An old owner releases only its retained OS handle and cannot unlock a successor's handle.
- If metadata from the previous protocol has no guard, same-host PID state is inspected conservatively. Remote hosts, inaccessible process state, and malformed legacy metadata fail closed.
- Kernel locks are released when the process exits and by operating-system restart semantics. A physical machine restart was not induced in this audit. A shared/network filesystem must provide reliable byte-range lock semantics.

## Production lifecycle

render_episode acquires the lock before reading or transitioning the shared journal. A losing contender raises LockBusy and cannot write state or call a renderer. The owner checks lock health after the expensive render, before packaging, and before READY_TO_PUBLISH. Heartbeat loss is surfaced as LockHeartbeatError and production fails closed. Exceptions attempt to write FAILED while preserving the original exception, then release the handle in a finally path. SIGTERM or process termination may leave an intermediate journal state; OS lock release permits a later recovery run.

A malformed protocol-2 metadata file does not authorize stealing a live guard. If the guard remains held, the contender fails. Once the OS handle is released, a new owner can acquire and replace corrupt metadata. If both ownership metadata and the expected guard evidence are absent or ambiguous in a legacy state, recovery intentionally requires manual investigation rather than guessing that the owner is dead.

## Test evidence

Focused reliability/control/workflow regression suite on Windows 11, Python 3.12.7: 114 passed, 1 skipped in 18.97 seconds. The full local suite later completed with 1,469 passed, 1 skipped, and 5 subtests passed in 1,054.07 seconds. After editorial JSON updates, the focused content suite passed 78 tests in 6.04 seconds. The candidate was then committed as 7d6ffe0; the executable source in that commit is the source tested by the full suite, and branch CI is still required.

Coverage includes active owners with expired heartbeat metadata, the original one-hour TTL, renderer execution beyond a short TTL, dead legacy owners, remote legacy metadata, simultaneous stale reclaimers, replacement during reclamation, former-owner release, identical job IDs in separate processes, heartbeat renewal and failure, normal/abrupt termination, hard process kill, corrupt/missing metadata, missing lock files, and a 12-process acquisition stress test. The stress test observed exactly one owner. The Windows LockFileEx path ran locally. The POSIX flock test is skipped on Windows and must be covered by the branch's Ubuntu CI before merge. Windows process kill is not POSIX SIGKILL; a real SIGKILL test is conditional on POSIX CI.

## Residual risks and release gate

- This candidate is not on protected main. Do not characterize main as fixed until reviewed, merged, and main CI passes.
- POSIX CI and the new pull request's security jobs are not yet evidence in this report.
- No physical reboot or shared-network-filesystem lock test was performed.
- Exact lock acquisition latency and post-crash recovery time were not benchmarked.
- Legacy corrupt metadata without sufficient owner evidence intentionally fails closed and may require owner recovery.

See X100_FINAL_PROJECT_COMPLETION_REPORT.md for the final A-T evidence matrix.

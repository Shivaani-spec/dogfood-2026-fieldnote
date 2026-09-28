# Threat model

## Assets

- Participant credentials and active sessions.
- Private judge ballots, comments and assignment scopes.
- Organizer-only results and the event audit history.
- Submissions, team membership, event configuration and data archives.
- Vote totals and judging outcome integrity.

## Actors and trust boundaries

The server accepts anonymous gallery requests, participant submissions, judge requests and organizer/admin operations. An attacker may create accounts, guess passwords, alter browser requests, reuse an invite, probe APIs, submit malformed bodies or try to access another judge's ballot. A local machine administrator and someone with write access to the SQLite volume are trusted; this build does not defend a compromised host.

## Abuse cases and controls

| Abuse | Control |
| --- | --- |
| Read or overwrite a peer ballot | Backend role checks; judge lookup is bound to the caller; writes require an owned assignment |
| Review a different track | Judge track scope checked on writes and assignment generation |
| Submit after the deadline | Server checks open and close dates on creates and edits; gallery lists only submitted records |
| Steal a session with script | Random HTTP-only SameSite cookie; only token hashes are stored |
| Cross-site browser mutation | Origin must match the request host when supplied |
| Guess passwords | PBKDF2-SHA256, generic errors and process-local attempt throttle |
| Duplicate or concentrate votes | Unique voter/project row, event-wide 16-credit quadratic budget, team self-vote check, throttle and audit record |
| Replay or guess an invite | High-entropy token, stored hash, seven-day expiry and one-time acceptance |
| SQL injection or oversized body | Parameterized SQL, 1 MiB JSON limit and type/range validation |
| Alter history silently | Each audit entry links to the prior SHA-256 hash; the verifier recalculates the chain |
| SSRF through project links | URLs are stored and never fetched |

## Limits

Open-link voter cookies can be cleared. Throttles reset after restart. Email mode does not verify mailbox ownership. There is no CAPTCHA, IP reputation or independent asymmetric signing key. A host administrator able to rewrite the database can recompute the entire audit chain. HTTPS termination and host firewalling belong to the self-hosting operator. Outbound webhook delivery is absent, so there is no webhook URL surface.

For a high-stakes production event, use authenticated voting, terminate TLS at a local reverse proxy, retain off-host backups, review the audit chain and publish after the review window.

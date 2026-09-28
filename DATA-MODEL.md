# Data model and portability

The SQLite schema uses event-scoped records and explicit foreign keys. IDs are opaque strings, timestamps use UTC ISO 8601, and flexible event configuration is stored as JSON on its event.

| Record | Purpose |
| --- | --- |
| events | Dates, tracks, prizes, questions, voting mode, rubric and result publication state |
| users, sessions | Role accounts, PBKDF2 verifiers, hashed expiring session tokens |
| teams, team_members, invites | Event teams and expiring single-use invitations |
| projects | Submission fields, image URLs, tags, custom answers and draft/submitted state |
| judge_tracks | Per-judge allowed track scope |
| assignments, scores | Private judge-to-project work and one replaceable ballot per assignment |
| comments, votes | Project discussion and quadratic-budget ballots |
| audit_log | Application actions linked by previous and current SHA-256 hashes |
| meta | Active event, first-run marker and persisted attestation HMAC key |

Projects reference their owning team. A score references an assignment, making the assigned reviewer the authorization source. Session rows contain only SHA-256 hashes of bearer tokens.

## Import and export

GET /api/export.json emits format fieldnote-event-export-v1 with event settings, teams, team memberships, projects, assignments, scores, comments and votes. Password verifiers and sessions are excluded. POST /api/export/import creates a new event and remaps team, project and assignment IDs. Team memberships are linked only where the destination already has the same user IDs; fixture-to-fixture restores preserve those links. Custom account migration requires those members to be re-created and invited.

CSV export supports kind=projects, assignments, scores, results, votes and audit. Python's CSV writer correctly quotes commas and newlines.

A clean local SQLite backup is also complete. Prefer the JSON archive for event-to-event migration because it avoids copying live sessions and password data.

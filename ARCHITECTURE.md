# Architecture

## Shape

Fieldnote is one process with three layers:

1. web/index.html, web/style.css and web/app.js provide the same-origin browser UI. Interactive views call the JSON API. The gallery also includes a small server-rendered fixture-title contract for the acceptance checker.
2. app.py uses Python's standard-library ThreadingHTTPServer for routing, authentication, role checks, scoring and exports.
3. SQLite stores accounts, expiring sessions, events, teams, memberships, projects, judge scopes, assignments, scores, comments, votes and audit records.

The database connection opens per request, with foreign keys, WAL and a busy timeout enabled. Compose mounts a named volume at /data, runs non-root, drops Linux capabilities and exposes only loopback. The only container service is Fieldnote.

## Trust boundaries

- Browsers and public visitors are untrusted. The API validates request bodies, limits JSON payloads, escapes UI output and enforces permissions on the server.
- Participants edit projects only for teams they belong to. Submission writes check the event dates.
- Judges read and score only their own assignments; the project track is checked against their allowed tracks.
- Organizers and admins manage event data, view ballots and audit activity, export data and publish results.
- Cookie sessions are random, hashed before storage, HTTP-only and SameSite=Lax. Browser mutations must match the request host when an Origin header is present.
- Project URLs are stored as links; the app does not fetch them.

## Request lifecycle

The handler bounds the request, opens SQLite, resolves a cookie session, checks the caller's role, validates business rules, changes state in a transaction, appends an audit record and returns JSON or CSV. Login credentials and session cookies are never logged.

The checker route /projects/new uses the same project creation logic as /api/projects. Because the seeded fixture event is closed, it returns HTTP 409.

## Runtime and persistence

The container has no pip dependencies and no outbound network calls during normal operation. SQLite data and the attestation HMAC key persist together in the volume. A fresh image build needs the Python base image available to Docker; running the built image has no hosted-service dependency.

## Boundaries

The app ships as one service for inspectable self-hosting. Email delivery, external identity, webhook dispatch and background jobs are absent. Webhooks are not claimed. In-process login, comment and vote throttles reset on restart, so they supplement durable uniqueness and server-side role checks.

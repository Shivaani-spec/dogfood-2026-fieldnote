# Fieldnote

Fieldnote is a local-first workspace for the hackathon lifecycle: event setup, team invitations, project submissions, private judge assignments, weighted reviews, normalization, community voting and publication.

It is Python 3.12 plus SQLite, serves its own interface, and has no runtime calls to a hosted database, identity provider, font CDN, analytics service or external API. Its CSS and JavaScript come from the same process.

## Start

    docker compose up

Open http://localhost:8080. Compose builds the local image and persists the SQLite database in the fieldnote_data volume. The application needs no network access after the image is available locally.

For a direct development run, use Python 3.12 or newer:

    python app.py

The app seeds DOGFOOD fixtures on first start and prints the four acceptance-checker auth headers to stdout. No package installation is required. A direct run stores the database in data/.

The Dockerfile and Compose configuration are included. Docker was unavailable in the build environment, so the Compose launch path has not been verified here.

## Public preview

Browse the [Fieldnote Vercel preview](https://fieldnote-dogfood-2026-demo.vercel.app/). It is a static, read-only gallery built from the challenge's fictional checker fixtures. Search, track filters and sorting work; it does not accept accounts, submissions, or judge scores. The standalone preview source is in the vercel-demo directory; the complete Python and SQLite portal runs locally.

## Demo accounts

| Role | Email | Password |
| --- | --- | --- |
| Organizer | organizer@dogfood.local | raptors2026 |
| Judge | tomas.varga@example.org | demo-pass |
| Judge | wei.lindqvist@example.org | demo-pass |
| Participant | participant@example.org | demo-pass |

The seed includes all fixture judges and participant teams. Fixture accounts use the demo-pass password. Use them only for a local demonstration. An organizer can create a track-scoped judge account; its temporary password is displayed once.

## First-run walkthrough

1. Sign in as organizer and open Event control, then Manage event. The fixture submission deadline is 2026-03-01T18:00:00Z exactly as published, so late submissions are refused. To try submission, move the opening and closing dates into the future.
2. Sign out and register a participant account, or use the seeded participant. Create a team, optionally invite teammates, save a draft and submit an entry.
3. Sign in as organizer. Add judges for the event tracks if needed, then generate balanced assignments. Only judges scoped to a project's track are eligible.
4. Sign in as a judge, review assigned projects, score each weighted criterion from 1 to 5 and leave private feedback.
5. Return to Event control to inspect progress, compare raw and normalized results, export CSV/JSON, verify the audit chain and publish results. The fixture voting dates are historical too; update them before trying the ballot.

## Acceptance checker

From this directory, run the official standard-library checker:

    python3 run.py .dogfood.toml > acceptance-report.txt

The checker is included unchanged from the official spec. Keep its generated report at the repository root, even when it contains a failure. The config claims T1 and T2; it does not claim the partially implemented public and stretch tiers.

## Submission presentation

An editable five-slide pitch deck is included at [submission-artifact/Fieldnote-DOGFOOD-2026-Pitch.pptx](submission-artifact/Fieldnote-DOGFOOD-2026-Pitch.pptx). It summarizes the product, judging controls, local operation, and verified T1/T2 results. The deck states that Docker Compose was not run on the build machine.

## What works

- Per-account salted PBKDF2 password verifiers, random expiring sessions, HTTP-only same-site cookies, server-side role checks and a login throttle.
- Visitor, participant, judge, organizer and admin roles.
- Event creation and editing, UTC deadlines, tracks, prizes, custom questions, voting dates and weighted rubrics.
- Team creation and single-use seven-day invite links. Project drafts and edits obey the event's submission window.
- Public search and track filters with all fixture projects loaded from the official fixtures.json.
- Track-scoped, workload-balanced judging assignments. A judge can read and submit only ballots assigned to them. Peer ballots and aggregate results are protected in the API.
- Organizer progress, weighted rubric scoring, cross-judge normalization, CSV exports for submissions, assignments, raw scores and results, and JSON event export/import.
- Optional community voting with a 16-credit quadratic budget, one editable ballot entry per voter and project, team self-vote prevention for signed-in participants, duplicate detection, rate limits and audit records. Each ballot has stable randomized project ordering. Public result endpoints and the gallery leaderboard stay closed until publication.
- Project comments, a read-only embeddable gallery, OpenAPI JSON, judge participation attestations and an append-only hash-linked activity ledger.

## Honest limits

- Only T1 and T2 are claimed. T3 email-gated mode means an account with an email address, not control of that mailbox. Open-link ballots rely on a browser cookie and are not sybil-proof. Rate limits are process-local. Do not treat community votes as a fraud-resistant public poll.
- The organizer can publish results after the configured voting window ends. Pairwise judging is not implemented.
- Participation attestations use HMAC-SHA256 and are verified by the same running Fieldnote instance. They are not asymmetric signatures verifiable offline by a third party.
- Stretch webhooks are not implemented. The embed, REST API, certificates and event archive cover selected T4 capabilities, not the complete T4 tier.
- This demo does not send email, accept file uploads, scan external links or include SMTP. Invite URLs are generated for the organizer to share.
- Fixture data are fictional. The public gallery includes the repository and demo URLs in those fixtures.

See ARCHITECTURE.md, DATA-MODEL.md, JUDGING.md, THREAT-MODEL.md and openapi.json.

## Data and reset

Back up an event using Full event backup or GET /api/export.json. Restore a Fieldnote archive with Event control or POST /api/export/import.

To reset the Compose demo and delete its database, stop the app and run docker compose down -v, then docker compose up. This removes the persistent demo volume.

## License

MIT. See LICENSE.

# Collection-link protocol, version 1

Collections Studio imports a read-only JSON snapshot from a user-pasted URL:
`https://example.invalid/api/v1/collections/{token}`. The token is a 43-character
URL-safe capability. Anyone holding a real link can read that snapshot; never
commit real links, tokens, private collection names or saved responses.

Only HTTPS is accepted, except explicitly pasted loopback HTTP during development.
The client sends no cookies or authorization headers and refuses redirects. The
server may revoke a link; 401, 403 and 404 produce an unavailable-link error.

The response must be `200 application/json`, within 32 MiB, with `Format` equal
to `maps-collection` and integer `Version` equal to 1. `Collections` contains 1–100
objects with a nonblank `Name` (up to 80 characters) and `Hashes` (at most 10,000
valid difficulty MD5s each). `CollectionCount` and `MembershipCount` must agree
with the payload. `Beatmaps` optionally supplies labels keyed by included MD5;
remote metadata never marks a map as installed. `ExportedAt` records the server's
snapshot creation time. Synthetic JSON is in
[`tests/fixtures/collection-link-v1.json`](../tests/fixtures/collection-link-v1.json).

Imports merge exact collection names, deduplicate hashes case-insensitively,
preserve Unicode and empty collections, and retain valid unresolved hashes.
Importing twice adds no duplicate memberships. Invalid or incomplete snapshots
fail before changing the working session. Imported edits remain staged until Save.

`GET /api/v1/collections/{token}/collection.db` exposes the equivalent legacy
binary. It contains collection names and MD5 memberships, with no notes, accounts,
map archives or filesystem destinations. The test fixture's hex text represents
the exact expected bytes. Both projects test the same fixtures independently;
incompatible protocol changes require versioning and coordinated fixture review.

The desktop client also accepts public osu!collector collection URLs or numeric
IDs through Import link. The Maps producer remains a separate optional service;
Collections Studio runs without it.

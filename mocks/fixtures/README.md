# Fixture overrides

A file named `{domain}/{operation}.json` replaces the demo world or the generated value for that allowlisted read.

`pbm-mock` reads this directory on each request. When the server is started from the repo, the directory is `mocks/fixtures` next to `specs/`. Leave it empty unless a tool needs a specific shape.

Fictional demonstration data lives in `mocks/world`. Do not put real member data in either directory.

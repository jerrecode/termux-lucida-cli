# Development plan: Termux Lucida CLI

This project prioritizes **native Android compatibility before feature breadth**.
A checked item indicates source code and automated offline verification, not a
claim that upstream availability or physical Android behavior was tested.

## Phase 0: first runnable prototype (v0.1.0)

- [x] Portable Python 3.10+ package and console entry point
- [x] Pure-Python JSON5 parsing of Lucida's SvelteKit page data
- [x] Search tracks and albums, display exact upstream source URLs
- [x] Resolve a direct track/album URL, obtain metadata and tokens
- [x] Handoff request, polling and binary streaming protocol
- [x] Sequential album and text-file batch processing
- [x] Basic filename sanitation, atomic part-file saving, no-overwrite behavior
- [x] Consistent errors and nonzero exit codes
- [x] Safe session-cookie handling (do not forward cookie on redirects)
- [x] Pure-Python offline unittest suite
- [x] GitHub Actions Linux Python 3.10-3.13 test matrix
- [ ] Test package installation inside real native Android Termux
- [ ] Validate a successful live download on an authorized accessible item
- [ ] Test Lucida's current response shapes, regional provider limits and 403 behavior

## Phase 1: Android hardening

- [ ] Termux device test matrix: Android 14/15/16 and arm64
- [ ] Permission and storage chooser diagnostics (private home vs shared storage)
- [ ] Download progress, bytes per second, ETA, cancellation and SIGINT cleanup
- [ ] Network interruptions, storage exhaustion and corrupted-content detection
- [ ] Durable deduplication and resumable batch state
- [ ] User-configurable retries and documented rate limits

## Phase 2: library workflow

- [ ] Accurate album/disc/track order, tags and cover art
- [ ] Optional native Termux FFmpeg conversion
- [ ] Structured JSON output for automation
- [ ] Public playlist metadata adapters (without assuming Chromium)
- [ ] Review/search/match workflow to avoid incorrect artist/track picks
- [ ] Safe concurrent downloads with token-expiry handling

## Phase 3: optional enhancements

- [ ] Touch-friendly Termux:GUI frontend (separate optional package)
- [ ] Android system share/open intents through Termux:API
- [ ] Account/session integration only if authorized and portable without bypassing protection
- [ ] Optional API server, separated from core minimal CLI dependencies

## Constraints

Do not ship unofficial Chromium wheel hacks, proot requirements or browser anti-bot
circumvention as mandatory dependencies. Upstream Lucida API behavior is not a
published stable contract, so each HTTP response shape requires regression tests.
Only work with media for which the user has download rights.

# Development plan: Termux Lucida CLI

This project prioritizes **native Android compatibility and correct file handling** over feature count. Checked tasks mean the implementation exists and **offline tests** passed, never a claim of live Lucida availability or a physical Android test.

## Phase 0: initial CLI (v0.1.0)

- [x] Python 3.10+ package, console entry point, install script
- [x] Pure Python HTTP transport and JSON5 SvelteKit metadata parsing
- [x] Interactive-free search, explicit result selection, direct URL resolution
- [x] Album and batch workflows, sequential handoff/poll/download implementation
- [x] Filesystem output paths and baseline validation
- [x] Offline unit tests and Python 3.10–3.13 CI

## Phase 1: reliability hardening (v0.2.0)

- [x] Read balanced JSON5 payload regardless of trailing SvelteKit `uses` fields
- [x] Reject unexpected media errors and conflicting filename extensions
- [x] Create unique partial files and publish without clobbering a destination
- [x] Support shared Android storage when hardlinks are unavailable
- [x] Explicit existing-file policies: skip, rename, fail; distinguish skip from save
- [x] Prevent cross-origin redirects for metadata/API requests and reject unsafe hosts
- [x] Avoid repeating non-idempotent POST handoff requests on network errors
- [x] Validate malformed result types, nonempty files, and Unicode byte-length limits
- [x] Synthetic protocol integration tests for an entire successful track download
- [x] Package installation smoke test under Linux/Python 3.13
- [ ] Test package installation inside native Android Termux
- [ ] Validate a successful live download of an authorized accessible item
- [ ] Test live regional service availability and 403 error paths

## Phase 1b: response integrity and Android filesystem safety (v0.3.0)

- [x] Reject lookalike Amazon music-service hosts
- [x] Validate common audio/archive magic bytes; reject bogus media responses
- [x] Infer file extensions from binary stream headers when the MIME type is generic
- [x] Reject invalid Content-Length values and interrupted response reads
- [x] Preserve never-overwrite semantics during restricted Android storage fallback
- [x] Add disk-full and collision tests for Android no-hardlink fallback
- [x] Reject malformed poll status immediately
- [x] Expand local regression suite to at least 37 offline tests
- [ ] Confirm Android shared-storage device-level semantics under concurrent writers and force-stop
- [ ] Verify real files using a full media decoder and checksums

## Phase 2: Android field verification and recovery

- [ ] Verify Android 14/15/16 on arm64 with private and shared storage targets
- [ ] Test across foreground/background termination and storage permission denial
- [ ] Support resumable transfer when upstream advertises HTTP ranges
- [ ] Durable manifest for download history, hashes, retries and interrupted batches
- [ ] Progress: current bytes, rate, percentage and estimated remaining time
- [ ] Limit retries, honor server rate limits and capture actionable diagnostics
- [ ] Native device performance/storage stress tests

## Phase 3: library-quality features

- [ ] Artist/disc/track organization, tags, cover art and library verification
- [ ] Optional native Termux FFmpeg transcoding with quality safeguards
- [ ] Public-playlist import without mandatory Playwright
- [ ] Match review to avoid downloading wrong versions
- [ ] Safe optional parallel downloads and token expiry refresh
- [ ] Structured JSON output for scripts

## Phase 4: optional interfaces

- [ ] Touch-friendly Termux:GUI (separate optional frontend)
- [ ] Termux:API integration for file picker and Android share intents
- [ ] Optional HTTP API separated from minimal CLI installation

## Hard constraints

No required Chromium, desktop, Playwright, proot, anti-bot circumvention or DRM bypass. Browser authentication/Cloudflare challenges are not solved by this browser-free project. lucida.to has no stable public protocol contract. Document and test all service assumptions and use the tool only for authorized content.

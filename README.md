# Termux Lucida CLI

A lightweight **native Termux / Android** Python command-line client for [lucida.to](https://lucida.to). No Playwright, Chromium, Node.js, VNC, proot, or Linux desktop are required for the core HTTP workflow. Inspired by the publicly documented Lucida request flow used in [lucidadl](https://github.com/Jude-A/lucidadl) and [lucida-flow](https://github.com/ryanlong1004/lucida-flow), but implemented independently for Termux.

**Release status: 0.2.0 experimental.** The offline parser, CLI and file-writing tests pass; end-to-end downloads on an Android phone and current live Lucida service access **have not been verified**. Lucida's website and endpoints may change, and the service may require browser verification that a browser-free client cannot perform automatically.

Only download content for which you have the necessary rights and permissions. This project is independent of Lucida and streaming services; it does not decrypt DRM or defeat access controls.

## Install on native Termux

Use a recent [F-Droid Termux build](https://f-droid.org/packages/com.termux/) and update packages:

```sh
pkg update && pkg upgrade
pkg install python python-setuptools git
termux-setup-storage  # optional: grants access to Android's shared Music folder

git clone https://github.com/jerrecode/termux-lucida-cli.git
cd termux-lucida-cli
python -m pip install --no-build-isolation .
termux-lucida doctor
```

`--no-build-isolation` prevents pip from creating an unnecessarily complicated build environment. `json5` is the sole runtime dependency and is pure Python. If setup tooling is missing, run `pkg install python-setuptools`, then retry. To run without installing, from the checkout use `python termux_lucida.py ...`, after installing `json5`.

**Android storage:** After `termux-setup-storage` and granting permission, the default output is `~/storage/music` if that directory exists, otherwise `~/Music` in Termux's private home. You can specify `--output /path` explicitly. Termux cannot silently bypass Android's file permissions.

## Commands

```sh
termux-lucida doctor
termux-lucida doctor --live
termux-lucida services
termux-lucida search 'artist track title' --service amazon
termux-lucida search 'album name' --service qobuz --albums
termux-lucida info 'https://play.qobuz.com/track/123456'
termux-lucida download 'https://play.qobuz.com/track/123456' --output ~/Music
termux-lucida download 'artist track title' --service amazon --pick 1
termux-lucida download 'album name' --service qobuz --album --pick 1 --format flac
termux-lucida batch tracks.txt --output ~/storage/music
termux-lucida download "https://play.qobuz.com/track/123456" --on-existing rename
termux-lucida --help
```

URLs above are **format examples**, not claimed available tracks. Supported commands are `search`, `info`, `download`, `batch`, `services`, `doctor`. For an arbitrary search phrase, run `search` first and then `download --pick N`; automatic first-result downloading can silently choose a remix or cover and is intentionally disabled. `batch` reads one URL or (when combined with `--pick`) one explicit search term per non-comment line. Blank lines and `#` comments are ignored.

By default, files are placed under `Artist/Album/` folders. `--flat` disables folders. Existing nonempty files are skipped by filename rather than overwritten. **Skipping does not prove that the existing file is the same song.** Use `--on-existing rename` to save a numbered alternative or `--on-existing fail` to make collisions an error. All download content is written to a uniquely named `.part` file first, checked against the advertised byte count, and published without overwriting existing files. Android shared storage uses a safe fallback when hard links are unsupported. A failed item returns a nonzero exit status. `--format` passes Lucida's `original`, `flac`, `mp3`, `ogg-vorbis`, `opus`, `m4a-aac`, or `wav` format request directly to its server; *this is not local FFmpeg transcoding*.

## Browser verification and limitations

Lucida may respond with HTTP 403 due to bot protection. This project **does not** bundle a desktop browser, work around browser verification, or guarantee that a cookie from an Android browser can be reused. You can optionally use a session cookie you legitimately control and are authorized to use, sent only to the exact `lucida.to` host. Use the same user-agent as the session if necessary:

```sh
# Do not paste secrets as command-line flags or into a public issue.
read -rs LUCIDA_COOKIE; export LUCIDA_COOKIE; printf '\n'
export LUCIDA_USER_AGENT='your actual Android browser user agent'
termux-lucida doctor --live
```

If the service denies access, use the website in an authorized browser instead. Cookies are sensitive credentials: do not commit or share them; `unset LUCIDA_COOKIE` to clear the shell variable. This client does not access or capture browser cookies automatically.

What is **not** included in v0.1.0: automatic Cloudflare browser setup, public-playlist extraction, local transcoding/tag editing, parallel downloads, range-based resume, or a native Android GUI. These require separate, independently tested implementations. The server protocol is reverse-engineered from publicly visible clients and might change.

## Development and verification

```sh
python -m unittest discover -s tests -v
python -m compileall -q termux_lucida.py tests
```

Offline tests cover changing SvelteKit terminators, metadata, tokens, URL restrictions, redirects, worker host validation, synthetic end-to-end HTTP protocol flow, Android-storage fallback, partial-file cleanup, atomic downloads, collision handling and CLI errors. Actual physical Android testing and live service integration remain outstanding.

## Credits and license

Original implementation, MIT license. API request design informed by the MIT-licensed [Jude-A/lucidadl](https://github.com/Jude-A/lucidadl) and [ryanlong1004/lucida-flow](https://github.com/ryanlong1004/lucida-flow), without copying their implementation.

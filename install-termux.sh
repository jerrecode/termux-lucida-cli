#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
if [[ "${PREFIX:-}" != /data/data/com.termux/files/usr ]]; then
    printf 'This installer is specifically for native Termux. Use python -m pip install . elsewhere.\n' >&2
    exit 1
fi
pkg install -y python git
python -m pip install --no-build-isolation .
printf '\nInstalled. For shared Music storage, run termux-setup-storage and approve Android permissions.\n'
termux-lucida doctor

#!/usr/bin/env bash
# Install actionlint (lints .github/workflows) from its official release,
# checked against a known SHA-256 before anything is installed.
#
#   bash tools/install-actionlint.sh            # installs to /usr/local/bin (uses sudo)
#   PREFIX=~/.local/bin bash tools/install-actionlint.sh   # no sudo
#
# CI uses this script too, so the pinned version lives in one place. To
# upgrade: change VERSION and SHA256 (from the release's checksums file).
set -euo pipefail

VERSION=1.7.12
SHA256=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8  # linux_amd64
PREFIX=${PREFIX:-/usr/local/bin}

if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
    echo "install-actionlint: this script knows the checksum for Linux x86_64 only." >&2
    echo "Get actionlint for $(uname -s) $(uname -m) from https://github.com/rhysd/actionlint/releases" >&2
    exit 1
fi

if command -v actionlint >/dev/null && [ "$(actionlint -version | head -1)" = "$VERSION" ]; then
    echo "actionlint $VERSION is already installed: $(command -v actionlint)"
    exit 0
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
tarball="actionlint_${VERSION}_linux_amd64.tar.gz"

echo "Downloading actionlint $VERSION..."
curl -fsSL -o "$tmp/$tarball" "https://github.com/rhysd/actionlint/releases/download/v${VERSION}/${tarball}"

echo "Checking SHA-256..."
echo "$SHA256  $tmp/$tarball" | sha256sum -c --quiet - || {
    echo "install-actionlint: checksum mismatch, nothing installed." >&2
    exit 1
}

tar -xzf "$tmp/$tarball" -C "$tmp" actionlint
if [ -w "$PREFIX" ] || { [ ! -e "$PREFIX" ] && mkdir -p "$PREFIX" 2>/dev/null; }; then
    install -m 755 "$tmp/actionlint" "$PREFIX/actionlint"
else
    echo "Installing to $PREFIX (needs sudo)..."
    sudo install -m 755 "$tmp/actionlint" "$PREFIX/actionlint"
fi

echo "Installed: $("$PREFIX/actionlint" -version | head -1) at $PREFIX/actionlint"

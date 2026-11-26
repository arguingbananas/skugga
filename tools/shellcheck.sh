#!/usr/bin/env bash
# Run shellcheck on every tracked shell script, and on each npm script in
# package.json (npm runs those with sh). Shell commands inside workflows are
# covered by actionlint, which uses shellcheck too.
#
#   bash tools/shellcheck.sh
set -euo pipefail

cd "$(dirname "$0")/.."
status=0

mapfile -t scripts < <(git ls-files '*.sh')
if [ "${#scripts[@]}" -gt 0 ]; then
    shellcheck "${scripts[@]}" || status=1
fi

# Each npm script on its own, as a POSIX sh script.
while IFS=$'\t' read -r name command; do
    if ! printf '%s\n' "$command" | shellcheck --shell=sh --exclude=SC2148 -; then
        echo "  (in package.json script \"$name\")" >&2
        status=1
    fi
done < <(node -e '
    const s = require("./package.json").scripts || {};
    for (const [k, v] of Object.entries(s)) console.log(k + "\t" + v);')

exit "$status"

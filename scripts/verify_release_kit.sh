#!/bin/sh
# Verify the archive as the delivery user, before extracting or invoking pkg.
set -eu
if [ "$#" -ne 3 ]; then
    echo 'Usage: sh verify_release_kit.sh KIT.zip KIT.zip.sig TRUSTED_PUBLISHER.pem' >&2
    exit 2
fi
for path in "$@"; do
    case "$path" in /*) ;; *) echo 'Use absolute paths' >&2; exit 2 ;; esac
    test -f "$path"
done
openssl dgst -sha256 -verify "$3" -signature "$2" "$1"

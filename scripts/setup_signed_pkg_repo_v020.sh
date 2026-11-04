#!/bin/sh
# Explicit bootstrap for the approved v0.20.0 repository, not a package installer.
set -eu
umask 077
if [ "$#" -ne 2 ]; then
    echo "Usage: sh $0 --verify-only|--activate /absolute/path/starroute-pkg-repo-v0.20.0.tar.gz" >&2
    exit 2
fi
ACTION=$1
case "$ACTION" in --verify-only|--activate) ;; *) exit 2 ;; esac
ARCHIVE=$2
case "$ARCHIVE" in /*) ;; *) echo 'Archive path must be absolute' >&2; exit 2 ;; esac
test "$(id -u)" -eq 0
test -f "$ARCHIVE"
test "$(sha256 -q "$ARCHIVE")" = ad5d854342c37f001a6b0b1c29053a8ed21837d96ca1b1e5970be9d78c540314
WORK=$(mktemp -d /var/tmp/starroute-repo-check.XXXXXX)
printf 'Verification logs: %s\n' "$WORK"
mkdir "$WORK/unpack" "$WORK/repos" "$WORK/db" "$WORK/cache"
# The exact archive is pinned above before extraction.
tar -xzf "$ARCHIVE" -C "$WORK/unpack"
test "$(sha256 -q "$WORK/unpack/repository.pub")" = 4a1be877f157f60e26d712f3ae00734445e3bad104be90e9136ec2d1b6978ebd
cat > "$WORK/repos/StarRoute.conf" <<EOF
StarRoute: {
  url: "file://$WORK/unpack/repo",
  enabled: yes,
  signature_type: "pubkey",
  pubkey: "$WORK/unpack/repository.pub"
}
EOF
isolated_pkg() {
    pkg -o REPOS_DIR="$WORK/repos" -o PKG_DBDIR="$WORK/db" -o PKG_CACHEDIR="$WORK/cache" "$@"
}
isolated_pkg update -f -r StarRoute > "$WORK/update.log" 2>&1
isolated_pkg rquery -r StarRoute '%n %v' | sort > "$WORK/packages.txt"
printf '%s\n' 'starroute-traders 0.20.0' 'starroute-traders-client 0.20.0' 'starroute-traders-master 0.20.0' | sort > "$WORK/expected.txt"
cmp "$WORK/expected.txt" "$WORK/packages.txt"
isolated_pkg fetch -y -r StarRoute -a -o "$WORK/fetched" > "$WORK/fetch.log" 2>&1
for f in "$WORK/unpack/repo/All/"*.pkg; do
    cmp "$f" "$WORK/fetched/All/$(basename "$f")"
done
echo 'Signature, catalogue and all 3 packages verified in an isolated pkg database.'
if [ "$ACTION" = --verify-only ]; then
    echo 'No system repository configuration or installed packages changed.'
    exit 0
fi
DEST=/var/db/starroute-pkg-repo/v0.20.0
KEY=/usr/local/etc/pkg/keys/starroute.pub
CONF=/usr/local/etc/pkg/repos/StarRoute.conf
for target in "$DEST" "$KEY" "$CONF"; do
    if [ -e "$target" ] || [ -L "$target" ]; then
        echo "Already exists; nothing overwritten: $target" >&2
        exit 1
    fi
done
# No concurrent repository administration during activation.
install -d -m 0755 /var/db/starroute-pkg-repo /usr/local/etc/pkg/keys /usr/local/etc/pkg/repos
mkdir -m 0755 "$DEST"
cp -Rp "$WORK/unpack/repo/." "$DEST/"
chown -R root:wheel "$DEST"
chmod -R u+rwX,go+rX,go-w "$DEST"
KEYTMP=$(mktemp /usr/local/etc/pkg/keys/.starroute.XXXXXX)
cp "$WORK/unpack/repository.pub" "$KEYTMP"
chown root:wheel "$KEYTMP"
chmod 0644 "$KEYTMP"
ln "$KEYTMP" "$KEY"
rm "$KEYTMP"
CONFTMP=$(mktemp /usr/local/etc/pkg/repos/.starroute.XXXXXX)
cat > "$CONFTMP" <<EOF
StarRoute: {
  url: "file://$DEST",
  enabled: yes,
  signature_type: "pubkey",
  pubkey: "$KEY"
}
EOF
chown root:wheel "$CONFTMP"
chmod 0644 "$CONFTMP"
ln "$CONFTMP" "$CONF"
rm "$CONFTMP"
pkg update -f -r StarRoute > "$WORK/system-update.log" 2>&1
pkg rquery -r StarRoute '%n %v' | sort > "$WORK/system-packages.txt"
cmp "$WORK/expected.txt" "$WORK/system-packages.txt"
cat "$WORK/system-packages.txt"
echo 'StarRoute repository activated. No package upgrade, DB change or service restart performed.'

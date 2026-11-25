#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then
    printf '%s\n' 'Usage (from verified source): sh distribution/make-runtime-archive.sh /new/output.tar.gz' >&2
    exit 1
fi
out=$1
case $out in /*.tar.gz) ;; *) printf '%s\n' 'Use an absolute .tar.gz output path.' >&2; exit 1;; esac
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
[ ! -e "$out" ] && [ ! -L "$out" ] || { printf '%s\n' 'Output path already exists.' >&2; exit 1; }
temp=$(mktemp -d)
pending=
cleanup(){ [ -z "$pending" ] || rm -f -- "$pending"; rm -rf -- "$temp"; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
version=CL-PCGM-0.163
prefix=$temp/$version
stamp=$(make -s stage-offline "PREFIX=$prefix")
tar --sort=name --mtime='UTC 2026-11-23' --owner=0 --group=0 --numeric-owner -cf "$temp/payload.tar" -C "$temp" "$version"
gzip -n -c "$temp/payload.tar" >"$temp/payload.tar.gz"
check=$temp/inspect
mkdir "$check"
tar -xzf "$temp/payload.tar.gz" -C "$check"
python3 "$check/$version/share/cl/verify-runtime.py" verify "$check/$version" "$stamp" >/dev/null
pending=$(mktemp "$(dirname -- "$out")/.cl-runtime-archive-XXXXXXXX")
cat "$temp/payload.tar.gz" >"$pending"
chmod 0644 "$pending"
python3 - "$pending" "$out" <<'PYARCHIVE'
import os, sys
pending, destination = sys.argv[1:]
with open(pending, "rb") as stream:
    os.fsync(stream.fileno())
os.link(pending, destination, follow_symlinks=False)
os.unlink(pending)
parent = os.open(os.path.dirname(destination), os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(parent)
finally:
    os.close(parent)
PYARCHIVE
printf 'manifest_sha256=%s\n' "$stamp"
sha256sum "$out"

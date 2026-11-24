#!/usr/bin/env python3
"""Verify, join and extract the archived data/results into the repository root.

Usage: python3 reproduction/unpack_archives.py [--only NAME ...] [--keep-joined]
Standard library only. Every part and every extracted file is checked against SHA-256 lists.
"""
import argparse
import hashlib
import io
import json
import lzma
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / 'archives'


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', nargs='*', help='archive names, e.g. results-E05 analysis')
    args = parser.parse_args()
    index = json.loads((ARCH / 'index.json').read_text(encoding='utf-8'))
    names = args.only or list(index)
    for name in names:
        entry = index[name]
        blob = bytearray()
        for part in entry['parts']:
            data = (ARCH / part['file']).read_bytes()
            if len(data) != part['bytes'] or sha_bytes(data) != part['sha256']:
                raise SystemExit('Corrupted part: ' + part['file'])
            blob += data
        if sha_bytes(bytes(blob)) != entry['sha256']:
            raise SystemExit('Joined archive hash mismatch: ' + name)
        members = {m['path']: m for m in json.loads((ARCH / (name + '.members.json')).read_text(encoding='utf-8'))}
        with tarfile.open(fileobj=lzma.LZMAFile(io.BytesIO(bytes(blob))), mode='r:') as tar:
            for info in tar:
                target = (ROOT / info.name).resolve()
                if ROOT.resolve() not in target.parents or not info.isfile() or info.name not in members:
                    raise SystemExit('Unexpected archive member: ' + info.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                data = tar.extractfile(info).read()
                if sha_bytes(data) != members[info.name]['sha256']:
                    raise SystemExit('Member hash mismatch: ' + info.name)
                target.write_bytes(data)
        print('%-13s %6d files verified and extracted' % (name, len(members)))


if __name__ == '__main__':
    main()

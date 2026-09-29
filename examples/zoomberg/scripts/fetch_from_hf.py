#!/usr/bin/env python3
"""Check (or refresh) the vendored Zoomberg data against the published Hugging Face dataset.

    python examples/zoomberg/scripts/fetch_from_hf.py --check              # verify byte-identity
    python examples/zoomberg/scripts/fetch_from_hf.py --revision <sha>     # pull a newer release

Why the data is vendored rather than downloaded on first use: `supportrl validate`,
`eval --replay` and the test suite must work offline and without an account, the files are
small (about 300 KB), and a pinned copy guarantees that the frozen results in results/ are
scored against exactly the data they were produced on. This script is how the copy stays
honest: --check fails if any vendored file differs from the pinned revision on the Hub.

When a new dataset release adds episodes (for example more train episodes), pull it with
--revision, re-run `supportrl validate examples/zoomberg`, and update REVISION below. Test and
dev episodes must not change under a published result; if they do, the frozen runs in
results/ no longer describe the current split and must be re-run or labelled as history.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

REPO = "KartiOS/fintech-support-triage"
REVISION = "6469529a20f9b8420534ba1ab42cd89a6f2e20b6"
HERE = Path(__file__).resolve().parents[1]
FILES = {  # hub path -> vendored path
    "data/train.jsonl": "data/train.jsonl",
    "data/validation.jsonl": "data/validation.jsonl",
    "data/test.jsonl": "data/test.jsonl",
    "policies/policies.md": "policies.md",
}
# docs/ started as the dataset's docs and carry small wording edits here (see
# examples/zoomberg/README.md), so they are not byte-checked.


def fetch(path: str, revision: str) -> bytes:
    url = f"https://huggingface.co/datasets/{REPO}/resolve/{revision}/{path}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--revision", default=REVISION)
    ap.add_argument("--check", action="store_true", help="verify only; write nothing")
    a = ap.parse_args()
    bad = 0
    for hub, local in FILES.items():
        remote = fetch(hub, a.revision)
        dest = HERE / local
        same = dest.exists() and dest.read_bytes() == remote
        status = "same" if same else "DIFFERS"
        print(f"{status:8s} {local}  sha256 {hashlib.sha256(remote).hexdigest()[:16]}")
        if not same:
            bad += 1
            if not a.check:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(remote)
    if a.check:
        return 1 if bad else 0
    if bad:
        print(f"updated {bad} file(s); now run: supportrl validate {HERE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

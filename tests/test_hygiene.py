"""Nothing private or internal ships in the repo.

The denylist of private names (people, hosts, internal projects) is stored only as sha256
digests of lowercased tokens, so the test does not publish the list it guards. Every word,
every hyphen/dot part of a token, every dot-suffix and every pair of adjacent words in the tree
is hashed and compared. To check extra terms locally, put one term per line in an untracked
file and point SUPPORTRL_EXTRA_DENYLIST at it.
"""

import hashlib
import os
import re
import subprocess
from pathlib import Path

from helpers import ROOT

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "runs", "build", "dist", ".pytest_cache", ".ruff_cache"}
TEXT = {".py", ".md", ".yaml", ".yml", ".toml", ".json", ".jsonl", ".txt", ".cfg", ".sh", ""}
DENY_SHA256 = {
    "634c994592e182e3666815b60e7cec0eece3c758f4026146d0ed6762c4a6abc0",
    "0ecc7147ff4491d05fbe124a6ebfff709c8f8998dbbfc721e3e9c4740159e067",
    "999e6d71fe545a658033df6d8daffb19f004775c0f87580e03ab5776be9d03e7",
    "6ccce4863b70f258d691f59609d31b4502e1ba5199942d3bc5d35d17a4ce771d",
    "dd641cdd0eec9f11c9451c39d9550f1862558c85093ca10e457bf6d5ee105bc0",
    "c359e4edaa37aa1fb14c09d1c2412aae229fbf95fb4e81f37ec9b11f1277938f",
    "536d9f839fb587191bfe15fdd89a1c077b8add1880f92acb17b8c52504fa71be",
    "c283924511a37a29b2ff090d6bd5613f6a2084659a87f5abe4007069a8f23d4c",
    "ae9ea3c22f00baeb6990b2d5c13314bce33d0323aca66e68e4323b2218b4fcdb",
    "e3315cdff93e6c03403216c157cf3570b1be4168d1de64adfa3fcc033c866e37",
    "6f35b7f8bdf8b336da0a42f4fc5de4639e462569d1c0ee8e3d039f02fc7d5c82",
    "2eb7d8b079950d1af82b09ff705466086335217bb98458f5ed80aff7fa274ec7",
    "9bb62a961c6aa968bd40989c4eaeb031cc8027132943f694fb14c81d8d4f8064",
    "82d3042b941378bc994b8c2596fa69e4370bd2cb5400c4c043c996dc197fda7c",
    "8cbbcf29d9cef89675c5f5c1dcfe827d0570416a5aaba30dd0de159661ad905b",
    "ec6f049478046f72becb006a2339202eae93911281dd610a7c869adec1ba3297",
    "9c2c431ce731298cb3b0a8d47a11d98efe8c606df8d5ecc49f471e1e0e970f8f",
    "930a68a51a2db950f58fd3b0b5f1d76f56afaa16e12a418d71ca6c25f2390424",
    "16363f6c1b7514b3043fc9a7e5cbf0a001f58be18e811d25237d88040d21df5f",
    "34391b064c1543e66e37ab26b567196988e51a8819318a6bc0d0bf9f3547bab6",
    "e4d6ba4352274f34ba2f7ee49d384d9d92b44485265d8422eae15b526d4f8d54",
    "05a331a7f4f1929faaca289a66f98d5a05b387d9cbeb4f8c2dd8204a6b023a14",
    "55e471e8a22ff53ae767767472beb25780971d9e570ae4b525b1e3c90bc06900",
}
TOKEN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
LITERAL = [
    re.compile(r"/home/[a-z]|/Users/[A-Za-z]"),  # absolute home paths
    re.compile(
        r"\b(?:sk-[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{30,}|ghp_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16})\b"
    ),  # keys
]


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def candidates(text: str) -> set[str]:
    toks = TOKEN.findall(text.lower())
    out = set(toks)
    for t in toks:
        parts = re.split(r"[._-]", t)
        out.update(parts)
        dots = t.split(".")
        out.update(".".join(dots[i:]) for i in range(1, len(dots)))
    words = re.findall(r"[a-z0-9]+", text.lower())
    out.update(f"{a} {b}" for a, b in zip(words, words[1:]))
    return out


def files():
    # In a git checkout, scan exactly what git tracks, so a local
    # virtualenv or cache under any name is never mistaken for repo content.
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout.decode()
    except (OSError, subprocess.CalledProcessError):
        out = None
    if out is not None:
        for rel in filter(None, out.split("\0")):
            p = ROOT / rel
            if p.suffix in TEXT and p.is_file():
                yield p
        return
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for f in filenames:
            p = Path(dirpath) / f
            if p.suffix in TEXT:
                yield p


def deny_digests() -> set[str]:
    deny = set(DENY_SHA256)
    extra = os.environ.get("SUPPORTRL_EXTRA_DENYLIST")
    if extra and Path(extra).exists():
        deny |= {_h(w.strip().lower()) for w in Path(extra).read_text().splitlines() if w.strip()}
    return deny


def test_denylist_self_check():
    assert _h("example") not in DENY_SHA256 and len(DENY_SHA256) >= 20


def test_no_internal_names_paths_or_secrets():
    deny = deny_digests()
    bad = []
    for p in files():
        text = p.read_text(encoding="utf-8", errors="replace")
        hits = {_h(c) for c in candidates(text)} & deny
        if hits:
            bad.append(f"{p.relative_to(ROOT)}: denylisted term (sha256 {sorted(hits)[0][:12]}...)")
        for rx in LITERAL:
            for m in rx.finditer(text):
                bad.append(f"{p.relative_to(ROOT)}: {m.group(0)!r}")
    assert not bad, "\n".join(bad[:20])

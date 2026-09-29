import json
import subprocess
import sys

from helpers import ROOT, ZOOMBERG
from supportrl.sitedata import SCHEMA, export


def test_export_schema(zpack):
    runs = [{"key": "base-9b", "label": "base", "path": str(ZOOMBERG / "results/test/qwen3.5-9b-base")},
            {"key": "v1", "label": "v1", "path": str(ZOOMBERG / "results/test/support-9b-v1")}]  # fmt: skip
    d = export(zpack, "test", runs, ["H1_disclosure_before_verification", "H4_advice_given"])
    assert d["schema"] == SCHEMA and len(d["episodes"]) == 32 and len(d["policies"]) == 63
    assert [round(m["summary"]["composite"], 3) for m in d["models"]] == [0.531, 0.706]
    ep = d["episodes"][0]
    assert {"id", "family", "difficulty", "context", "turns", "decisions", "results"} <= set(ep)
    dec = ep["decisions"][0]
    assert {"decision_point", "target", "models"} <= set(dec)
    m = dec["models"]["v1"]
    assert {
        "raw",
        "format_valid",
        "reply",
        "action",
        "components",
        "graded",
        "score",
        "hard_hits",
        "gates",
    } <= set(m)
    # mean of per-episode rewards == composite
    mean = sum(e["results"]["v1"]["reward"] for e in d["episodes"]) / 32
    assert abs(mean - d["models"][1]["summary"]["composite"]) < 1e-6
    # a hard hit carries its evidence
    hits = [h for e in d["episodes"] for x in e["decisions"] for h in x["models"]["v1"]["hard_hits"]]
    assert len(hits) == 1 and hits[0]["short"] == "H1" and hits[0]["evidence"]


def test_export_script(tmp_path):
    out = tmp_path / "o.json"
    r = subprocess.run([sys.executable, str(ROOT / "site-data/export.py"), "--project", str(ZOOMBERG), "--split", "dev",
                        "--run", f"v1=v1={ZOOMBERG / 'results/dev/support-9b-v1'}", "--out", str(out)],
                       capture_output=True, text=True)  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text())["models"][0]["summary"]["episodes"] == 18


def test_committed_site_data_is_current(tmp_path):
    """site-data/out/*.json must equal a fresh export (re-run site-data/export.py after changes)."""
    import shutil

    shutil.copytree(ROOT / "site-data", tmp_path / "site-data", ignore=shutil.ignore_patterns("out"))
    shutil.copytree(ROOT / "examples", tmp_path / "examples")
    r = subprocess.run([sys.executable, str(tmp_path / "site-data/export.py"), str(tmp_path / "site-data/zoomberg.yaml")],
                       capture_output=True, text=True)  # fmt: skip
    assert r.returncode == 0, r.stderr
    for name in ("zoomberg-test.json", "zoomberg-dev.json"):
        assert (tmp_path / "site-data/out" / name).read_bytes() == (
            ROOT / "site-data/out" / name
        ).read_bytes(), name


def test_export_floats_are_rounded(zpack):
    runs = [{"key": "v1", "label": "v1", "path": str(ZOOMBERG / "results/test/support-9b-v1")}]
    text = json.dumps(export(zpack, "test", runs))
    import re

    assert not re.search(r"\d\.\d{7,}", text)  # no float with more than 6 decimals

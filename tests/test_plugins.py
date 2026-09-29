import json

import pytest

from helpers import gold_obj
from supportrl.data import load_split
from supportrl.pack import Pack
from supportrl.scaffold import init_project
from supportrl.scorer import Scorer

PLUGIN = """
from supportrl.detectors import Detector, Hit, register_detector

@register_detector("refund_promise_test")
class RefundPromise(Detector):
    def detect(self, inp):
        return [Hit("guaranteed_refund", inp.reply[:40])] if "guaranteed refund" in inp.reply.lower() else []
"""


def test_project_plugin_detector(tmp_path):
    d = init_project(tmp_path / "p")
    (d / "my_detectors.py").write_text(PLUGIN)
    cfg = (d / "supportrl.yaml").read_text()
    cfg = cfg.replace("  # plugins: [my_detectors.py]", "  plugins: [my_detectors.py]")
    cfg = cfg.replace(
        "  hard_criteria:\n",
        "  hard_criteria:\n    - code: H9_refund_promise\n      detector: refund_promise_test\n",
    )
    (d / "supportrl.yaml").write_text(cfg)
    pack = Pack(d)
    sc = Scorer(pack)
    ep = load_split(pack, "train")[0]
    t = next(iter(ep["decisions"].values()))
    o = gold_obj(t)
    assert sc.score_episode(ep, [json.dumps(o)]).reward == pytest.approx(1.0)
    o["reply"] += " You have a guaranteed refund."
    r = sc.score_episode(ep, [json.dumps(o)])
    assert r.hard_failed and r.decisions[0].hard_zeroing == ["H9_refund_promise"]


def test_unknown_detector_is_a_clear_error(tmp_path):
    d = init_project(tmp_path / "p")
    cfg = (d / "supportrl.yaml").read_text().replace("detector: timeline", "detector: no_such_detector")
    (d / "supportrl.yaml").write_text(cfg)
    with pytest.raises(KeyError, match="unknown detector"):
        Scorer(Pack(d))

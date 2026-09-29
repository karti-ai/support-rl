"""End-to-end CLI: every command a README quickstart uses, offline (mock endpoints)."""

import json

import pytest

from helpers import ZOOMBERG, MockServer, ScriptServer
from supportrl.cli import main
from supportrl.data import load_split, read_jsonl
from supportrl.pack import Pack

Z = str(ZOOMBERG)


def test_validate_and_probes(capsys):
    assert main(["validate", Z]) == 0
    assert "0 error(s)" in capsys.readouterr().out
    assert main(["probes", Z]) == 0
    out = capsys.readouterr().out
    assert "h4.holdout.jsonl" in out and "advisory" in out


def test_replay_saved_outputs(capsys, tmp_path):
    assert main(["eval", Z, "--replay", str(ZOOMBERG / "results/test/support-9b-v1")]) == 0
    assert "composite            0.706" in capsys.readouterr().out
    assert main(["eval", Z, "--replay", str(ZOOMBERG / "results/test/support-9b-v1"), "--scoring", "v5",
                 "--out", str(tmp_path / "v5")]) == 0  # fmt: skip
    assert "composite            0.666" in capsys.readouterr().out
    assert (tmp_path / "v5" / "scores.jsonl").exists()


def test_report(capsys, tmp_path):
    md = tmp_path / "r.md"
    runs = [str(ZOOMBERG / "results/test" / r) for r in ("qwen3.5-9b-base", "support-9b-v1")]
    assert main(["report", Z, *runs, "--labels", "base", "v1", "--md", str(md)]) == 0
    text = md.read_text()
    assert "| **Composite** (a hard violation zeroes the episode) | **0.531** | **0.706** |" in text
    assert "+0.175" in text


def test_baseline_against_mock_endpoint(tmp_path, capsys):
    srv = MockServer(Pack(ZOOMBERG))
    try:
        rc = main(["baseline", Z, "--model", "mock", "--base-url", srv.url, "--split", "dev_val",
                   "--out", str(tmp_path), "--name", "b"])  # fmt: skip
    finally:
        srv.close()
    assert rc == 0
    s = json.loads((tmp_path / "b" / "summary.json").read_text())
    assert s["all"]["composite"] == pytest.approx(1.0) and s["all"]["decisions"] == 13
    assert len(srv.requests) == 13  # one request per decision point: multi-turn replay
    body = srv.requests[0]
    assert body["temperature"] == 0.0 and body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"][0]["role"] == "system" and "Policy pack" in body["messages"][0]["content"]
    # a frozen run is never overwritten
    assert main(["baseline", Z, "--model", "mock", "--base-url", srv.url, "--split", "dev_val",
                 "--out", str(tmp_path), "--name", "b"]) == 2  # fmt: skip


def test_eval_refuses_locked_split_without_flag(tmp_path, capsys):
    rc = main(
        [
            "eval",
            Z,
            "--model",
            "m",
            "--base-url",
            "http://127.0.0.1:9/v1",
            "--split",
            "test",
            "--out",
            str(tmp_path),
        ]
    )
    assert rc == 2 and "locked" in capsys.readouterr().err


def test_bad_model_output_fails_format_gate(tmp_path):
    srv = MockServer(Pack(ZOOMBERG), mode="bad")
    try:
        assert (
            main(
                [
                    "eval",
                    Z,
                    "--model",
                    "m",
                    "--base-url",
                    srv.url,
                    "--split",
                    "dev_val",
                    "--out",
                    str(tmp_path),
                    "--name",
                    "x",
                ]
            )
            == 0
        )
    finally:
        srv.close()
    s = json.loads((tmp_path / "x" / "summary.json").read_text())["all"]
    assert s["composite"] == 0.0 and s["format_invalid"] == 13 and s["format_errors"] == {"not_json": 13}


def test_init_then_validate(tmp_path, capsys):
    assert main(["init", str(tmp_path / "mydesk")]) == 0
    assert main(["validate", str(tmp_path / "mydesk")]) == 0


def test_simulate_writes_unreviewed_candidates(tmp_path, capsys):
    personas = tmp_path / "p.yaml"
    personas.write_text(
        "- id: wire\n  family: wire_recall\n  turns: 2\n  persona: A curt small-business owner.\n"
        "  goal: Recall a wire sent this morning.\n  context: {verified: false, account_masked: '****1234',"
        " account_type: cash, account_age_days: 90, local_time_et: '2026-05-12T10:00:00-04:00'}\n"
    )
    cust = ScriptServer(
        ["I sent a wire this morning to the wrong account, can you stop it?", "OK, what happens now?"]
    )
    agent = ScriptServer(
        [
            json.dumps(
                {
                    "reply": "I can help. Please verify your identity first.",
                    "action": {
                        "type": "ask_verification",
                        "queue": None,
                        "escalate_to": None,
                        "priority": None,
                        "flags": [],
                        "policy_ids": ["IDV-01"],
                    },
                }
            )
        ]
    )
    out = tmp_path / "cand.jsonl"
    try:
        rc = main(["simulate", Z, "--personas", str(personas), "--out", str(out),
                   "--model", "agent", "--base-url", agent.url, "--customer-model", "cust", "--customer-base-url", cust.url])  # fmt: skip
    finally:
        cust.close()
        agent.close()
    assert rc == 0
    (c,) = read_jsonl(out)
    assert c["review"]["status"] == "unreviewed" and c["decisions"] == []
    assert [t["role"] for t in c["turns"]] == ["customer", "agent", "customer", "agent"]
    assert c["turns"][2]["text"] == "OK, what happens now?"
    # the customer model saw the agent's reply text, not its JSON
    assert cust.requests[1]["messages"][-1]["content"] == "I can help. Please verify your identity first."
    # the agent saw the real system prompt and the rendered session context
    assert "Identity verified this conversation: no" in agent.requests[0]["messages"][1]["content"]
    assert main(["validate", Z, "--candidates", str(out)]) == 0
    # a candidate dropped into a split is skipped until reviewed
    assert all(e["id"] != c["id"] for e in load_split(Pack(ZOOMBERG), "train"))


def test_play_scripted_input(monkeypatch, capsys):
    agent = ScriptServer(
        [
            json.dumps(
                {
                    "reply": "Your balance is $5,120.",
                    "action": {
                        "type": "resolve",
                        "queue": None,
                        "escalate_to": None,
                        "priority": None,
                        "flags": [],
                        "policy_ids": [],
                    },
                }
            )
        ]
    )
    inputs = iter(["What's my balance?", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    ctx = json.dumps({"verified": False, "account_masked": "****1234", "account_type": "cash",
                      "account_age_days": 10, "local_time_et": "2026-05-12T10:00:00-04:00"})  # fmt: skip
    try:
        assert main(["play", Z, "--model", "a", "--base-url", agent.url, "--context", ctx]) == 0
    finally:
        agent.close()
    out = capsys.readouterr().out
    assert "H1 would fire" in out and "Your balance is $5,120." in out

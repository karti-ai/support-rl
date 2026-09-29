"""supportrl command line.

supportrl init PATH                      scaffold a project from the starter template
supportrl validate PROJECT               schema, vocab, policy IDs, label rules, leakage, probes
supportrl probes PROJECT                 detector recall / precision on the probe sets
supportrl baseline PROJECT --model ...   frozen before-numbers from an OpenAI-compatible endpoint
supportrl eval PROJECT --model ...       the same, for a trained model
supportrl eval PROJECT --replay RUN      re-score saved outputs offline (no model calls)
supportrl train PROJECT --backend prime|trl|select
supportrl report PROJECT RUN [RUN ...]   markdown before/after table
supportrl simulate PROJECT --personas F  LLM customer -> new unlabelled candidate episodes
supportrl play PROJECT --model ...       chat with a model under the real prompt
supportrl env build PROJECT --out DIR    self-contained verifiers environment package
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__


def _pack(a):
    from .pack import Pack

    return Pack(a.project, getattr(a, "scoring", None))


def _advisory(pack, spec: str | None) -> list[str]:
    if not spec or spec == "none":
        return []
    if spec == "auto":
        from .probes import probe_files, report

        return report(pack)["advisory"] if probe_files(pack) else []
    return [pack.resolve_code(x.strip()) for x in spec.split(",") if x.strip()]


def _client(a, prefix: str = ""):
    from .client import ChatClient

    g = lambda k: getattr(a, f"{prefix}{k}")  # noqa: E731
    pack_inf = getattr(a, "_inference", {})
    thinking = g("thinking")
    return ChatClient.from_args(
        g("base_url"), g("model"), g("api_key_env"),
        temperature=g("temperature") if g("temperature") is not None else float(pack_inf.get("temperature", 0.0)),
        max_tokens=g("max_tokens") or int(pack_inf.get("max_tokens", 1024)),
        thinking=None if thinking == "server" else thinking == "on" if thinking else bool(pack_inf.get("thinking", False)),
        extra_body=json.loads(g("extra_body")) if g("extra_body") else {},
    )  # fmt: skip


def _endpoint_args(p, prefix: str = "", required: bool = True, what: str = "the model under test"):
    d = prefix.replace("_", "-")
    p.add_argument(f"--{d}model", required=required, help=f"model name for {what}")
    p.add_argument(
        f"--{d}base-url", required=required, help="OpenAI-compatible base URL, e.g. http://localhost:8000/v1"
    )
    p.add_argument(f"--{d}api-key-env", help="name of the env var holding the API key (never the key itself)")
    p.add_argument(f"--{d}temperature", type=float, help="default: supportrl.yaml inference.temperature")
    p.add_argument(f"--{d}max-tokens", type=int, help="default: supportrl.yaml inference.max_tokens")
    p.add_argument(f"--{d}thinking", choices=["on", "off", "server"],
                   help="off sends chat_template_kwargs.enable_thinking=false (default: supportrl.yaml)")  # fmt: skip
    p.add_argument(f"--{d}extra-body", help="JSON merged into the request body")


# ---------------------------------------------------------------------------- commands
def cmd_init(a) -> int:
    from .scaffold import init_project

    d = init_project(a.path, a.name, a.force)
    print(f"created {d}/ (starter project: a fictional parcel carrier)\n"
          f"next:  supportrl validate {d}\n       then replace policies.md, prompt.md, data/ and "
          "supportrl.yaml with your own (recipe/README.md)")  # fmt: skip
    return 0


def cmd_validate(a) -> int:
    from .validate import validate, validate_candidates

    r = validate_candidates(a.project, a.candidates) if a.candidates else validate(a.project, a.split)
    print(r.format(a.max_warnings))
    return 0 if r.ok else 1


def cmd_probes(a) -> int:
    from .probes import dump, format_report, report

    r = report(_pack(a))
    print(format_report(r, a.verbose))
    if a.json:
        dump(r, a.json)
    return 0


def cmd_eval(a, baseline: bool = False) -> int:
    from .data import load_split
    from .runs import base_meta, format_summary, load_outputs, score_outputs, summarise_run, write_run

    pack = _pack(a)
    advisory = _advisory(pack, a.advisory)
    if a.replay:
        rows, meta = load_outputs(a.replay)
        split = a.split or meta.get("split")
        if not split:
            print("error: the saved run has no split recorded; pass --split", file=sys.stderr)
            return 2
        eps = {e["id"]: e for e in load_split(pack, split, allow_locked=True)}
        unknown = [r["episode_id"] for r in rows if r["episode_id"] not in eps]
        if unknown:
            print(
                f"error: {len(unknown)} outputs are not in split {split!r} (e.g. {unknown[0]})",
                file=sys.stderr,
            )
            return 2
        scored = score_outputs(pack, eps, rows)
        summary = summarise_run(pack, split, scored, advisory)
        label = meta.get("model") or Path(a.replay).name
        print(format_summary(f"replay {label} [{split}, scoring {pack.scorer_version}]", summary))
        if a.out:
            write_run(
                a.out, {**meta, **base_meta(pack, split, replayed_from=str(a.replay))}, rows, scored, summary
            )
            print(f"wrote {a.out}")
        return 0
    if not a.model:
        print(
            "error: give --model/--base-url to run a model, or --replay RUN to re-score saved outputs",
            file=sys.stderr,
        )
        return 2
    split = a.split or ("dev" if baseline else None)
    if not split:
        print("error: --split is required", file=sys.stderr)
        return 2
    episodes = load_split(pack, split, allow_locked=a.allow_locked)
    if a.max_episodes:
        episodes = episodes[: a.max_episodes]
    a._inference = pack.inference
    client = _client(a)
    name = (
        a.name
        or f"{'baseline' if baseline else 'eval'}-{split}-{a.model.replace('/', '_').replace(':', '_')}"
    )
    out = Path(a.out or "runs") / name
    if (out / "outputs.jsonl").exists() and not a.force:
        print(
            f"error: {out} exists; a frozen run is never overwritten (use --name or --force)", file=sys.stderr
        )
        return 2
    from .rollout import run_many

    t0 = time.time()
    rows = run_many(pack, episodes, client.chat, a.concurrency,
                    progress=lambda i, n, r: print(f"\r  {i}/{n} episodes", end="", file=sys.stderr))  # fmt: skip
    print(file=sys.stderr)
    rows.sort(key=lambda r: r["episode_id"])
    eps = {e["id"]: e for e in episodes}
    scored = score_outputs(pack, eps, rows)
    summary = summarise_run(pack, split, scored, advisory)
    body = client.body([])
    body.pop("messages")
    meta = base_meta(pack, split, model=a.model, base_url=a.base_url, sampling=body, frozen=baseline,
                     rollouts_per_episode=1, seconds=round(time.time() - t0, 1),
                     label=a.label or a.model)  # fmt: skip
    write_run(out, meta, rows, scored, summary)
    print(format_summary(f"{a.label or a.model} [{split}]", summary))
    print(f"wrote {out}/  (re-score any time: supportrl eval {a.project} --replay {out})")
    return 0


def cmd_report(a) -> int:
    from .report import load_run, render

    pack = _pack(a)
    advisory = _advisory(pack, a.advisory)
    runs = [load_run(pack, r, a.split, advisory) for r in a.runs]
    for r, lab in zip(runs, a.labels or []):
        r["label"] = lab
    md = render(pack, runs, a.title)
    if a.md:
        Path(a.md).write_text(md)
        print(f"wrote {a.md}")
    print(md)
    return 0


def cmd_train(a) -> int:
    if a.backend == "prime":
        from supportrl_train.prime import launch, prepare

        d = lambda v, default: default if v is None else v  # noqa: E731
        run = prepare(a.project, a.model, a.owner, a.out, a.name, a.env_version,
                      max_steps=d(a.max_steps, 21), batch_size=d(a.batch_size, 64), rollouts=d(a.rollouts, 8),
                      lr=d(a.learning_rate, 1e-4), lora_alpha=d(a.lora_alpha, 16),
                      max_tokens=d(a.max_tokens, 512))  # fmt: skip
        print(f"environment package: {run.env_dir}\nrun config:          {run.config}\n")
        import shlex

        for c in run.commands:
            print("  " + shlex.join(c))
        if a.launch:
            launch(run)
        else:
            print(
                "\nnot launched (pass --launch to run these; the prime CLI must be logged in, and it bills your account)"
            )
        return 0
    if a.backend == "trl":
        from supportrl_train import trl_grpo

        argv = [
            a.project,
            "--model",
            a.model,
            "--output-dir",
            a.output_dir or f"runs/trl-{Path(a.model).name}",
        ]
        if a.dry_run:
            argv.append("--dry-run")
        for flag, val in (("--max-steps", a.max_steps), ("--learning-rate", a.learning_rate),
                          ("--lora-alpha", a.lora_alpha), ("--max-completion-length", a.max_tokens),
                          ("--num-generations", a.rollouts)):  # fmt: skip
            if val is not None:
                argv += [flag, str(val)]
        return trl_grpo.main(argv + list(a.extra))
    if a.backend == "select":
        from supportrl_train import select

        pack = _pack(a)
        if a.candidates:
            cands = {n: runs.split(",") for n, runs in (c.split("=", 1) for c in a.candidates)}
            guard = a.ask_guard.split(",") if a.ask_guard else None
            print(select.report_runs(select.select_runs(pack, cands, a.subset, guard), pack))
            return 0
        else:
            res = select.from_checkpoints(pack, a.model, a.checkpoints, a.out)
        print(select.report(res, pack))
        return 0
    return 2


def cmd_simulate(a) -> int:
    from supportrl_sim.llm import LLMCustomer, generate_episode, load_personas

    from .data import write_jsonl
    from .validate import validate_candidates

    pack = _pack(a)
    a._inference = pack.inference
    agent = _client(a)
    cust_args = argparse.Namespace(**{k: getattr(a, k) for k in vars(a) if k.startswith("customer_")})
    cust_args._inference = {"temperature": 1.0, "max_tokens": 300, "thinking": False}
    customer_client = _client(cust_args, "customer_")
    rows = []
    for persona in load_personas(a.personas):
        for i in range(a.n):
            ep = generate_episode(pack, persona, LLMCustomer(customer_client, pack, persona), agent.chat, i)
            rows.append(ep)
            print(
                f"  {ep['id']}: {sum(t['role'] == 'customer' for t in ep['turns'])} customer turns",
                file=sys.stderr,
            )
    write_jsonl(a.out, rows)
    print(validate_candidates(a.project, a.out).format())
    print(f"\nwrote {len(rows)} UNREVIEWED candidates to {a.out}. Label each (decisions) against the pack, set "
          "review.status to reviewed, then move it into a split file and run supportrl validate.")  # fmt: skip
    return 0


def cmd_play(a) -> int:
    from supportrl_sim.play import play

    pack = _pack(a)
    a._inference = pack.inference
    agent = _client(a)
    context = json.loads(a.context) if a.context else {}
    if a.customer_model:
        from supportrl_sim.llm import LLMCustomer, Persona

        cust_args = argparse.Namespace(**{k: getattr(a, k) for k in vars(a) if k.startswith("customer_")})
        cust_args._inference = {"temperature": 1.0, "max_tokens": 300, "thinking": False}
        customer = LLMCustomer(_client(cust_args, "customer_"), pack,
                               Persona("play", a.persona or "An ordinary customer.", a.goal or "Get help.", context))  # fmt: skip
        transcript: list = []
        turns = iter(range(a.turns))

        def read():
            if next(turns, None) is None:
                return None
            msg = customer.next_message(transcript)
            if msg:
                print(f"customer: {msg}")
                transcript.append(("customer", msg))
            return msg

        def out(text):
            print(text)
            if "  agent: " in text:
                transcript.append(("agent", text.split("  agent: ", 1)[1].split("\n")[0]))
    else:
        print("type the customer's messages; an empty line ends the chat")

        def read():
            try:
                return input("customer> ").strip()
            except EOFError:
                return None

        out = print
    play(pack, agent.chat, context, read, out)
    return 0


def cmd_env(a) -> int:
    from .envbuild import build_env

    d = build_env(a.project, a.out, a.name, a.version, a.include_locked)
    print(
        f"built {d}\n  local:  pip install -e {d}\n  hosted: prime env push --path {d} --visibility PRIVATE"
    )
    return 0


# ---------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="supportrl", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)  # fmt: skip
    ap.add_argument("--version", action="version", version=f"supportrl {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="scaffold a new project")
    p.add_argument("path")
    p.add_argument("--name")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("validate", help="validate a project")
    p.add_argument("project")
    p.add_argument("--split")
    p.add_argument("--candidates", help="structure-check a file of generated (unlabelled) candidates")
    p.add_argument("--max-warnings", type=int, default=50)
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("probes", help="detector recall/precision on the probe sets")
    p.add_argument("project")
    p.add_argument("--scoring", help="a named scoring variant")
    p.add_argument("--json")
    p.add_argument("-v", "--verbose", action="store_true", help="list misclassified probes")
    p.set_defaults(fn=cmd_probes)

    for name, bl in (("baseline", True), ("eval", False)):
        p = sub.add_parser(name, help="run a model on a split and score it" if not bl else
                           "frozen before-numbers for a base model (default split: dev)")  # fmt: skip
        p.add_argument("project")
        _endpoint_args(p, required=False)
        p.add_argument("--split", help="split or subset (dev, dev_val, test, ...)")
        p.add_argument(
            "--allow-locked",
            action="store_true",
            help="required for a locked split: the one approved final run",
        )
        p.add_argument(
            "--replay", help="re-score saved outputs (run dir, outputs.jsonl or vf-eval results.jsonl)"
        )
        p.add_argument("--scoring", help="a named scoring variant from supportrl.yaml (e.g. v5)")
        p.add_argument("--advisory", default="auto", help="auto (from probes) | none | H1,H4")
        p.add_argument("--name", help="run directory name")
        p.add_argument("--label", help="column label for reports")
        p.add_argument("--out", help="runs root (default runs/); with --replay: write the re-scored run here")
        p.add_argument("--concurrency", type=int, default=8)
        p.add_argument("--max-episodes", type=int)
        p.add_argument("--force", action="store_true")
        p.set_defaults(fn=lambda a, bl=bl: cmd_eval(a, bl))

    p = sub.add_parser("report", help="markdown before/after table from saved runs")
    p.add_argument("project")
    p.add_argument("runs", nargs="+", help="run dirs; the first is the reference column")
    p.add_argument("--labels", nargs="*")
    p.add_argument("--split")
    p.add_argument("--scoring")
    p.add_argument("--advisory", default="auto")
    p.add_argument("--title")
    p.add_argument("--md", help="also write the table to this file")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("train", help="train: hosted (prime), self-hosted (trl), or select a checkpoint")
    p.add_argument("project")
    p.add_argument("--backend", choices=["prime", "trl", "select"], required=True)
    p.add_argument("--model", help="base model, e.g. Qwen/Qwen3.5-9B")
    p.add_argument("--owner", default="<your-hub-user>", help="prime: environment hub owner")
    p.add_argument("--name")
    p.add_argument("--out", default="runs/train")
    p.add_argument("--env-version", default="0.1.0")
    p.add_argument("--max-steps", type=int, help="default 21 (prime), 150 (trl)")
    p.add_argument("--batch-size", type=int, help="prime: rollouts per step (default 64)")
    p.add_argument("--rollouts", type=int, help="rollouts per episode / GRPO group size (default 8)")
    p.add_argument("--learning-rate", type=float, help="default 1e-4 (prime), 1e-5 (trl)")
    p.add_argument("--lora-alpha", type=int, help="default 16")
    p.add_argument("--max-tokens", type=int, help="completion tokens per turn (default 512)")
    p.add_argument(
        "--launch", action="store_true", help="prime: actually push and launch (bills your account)"
    )
    p.add_argument("--output-dir", help="trl: where checkpoints go")
    p.add_argument("--dry-run", action="store_true", help="trl: build prompts and check the reward only")
    p.add_argument("--checkpoints", help="select: dir with checkpoint-* adapters")
    p.add_argument(
        "--candidates",
        nargs="*",
        help="select: name=RUN_DIR[,RUN_DIR...] saved runs on the selection subset (several = passes)",
    )
    p.add_argument("--subset", help="select: selection subset (default: supportrl.yaml selection.subset)")
    p.add_argument(
        "--ask-guard", help="select: RUN_DIR[,...] of a reference model; reject candidates that ask less"
    )
    p.add_argument("--scoring", help="a named scoring variant (e.g. v5)")
    p.set_defaults(fn=cmd_train)

    p = sub.add_parser("simulate", help="LLM customer -> new unlabelled candidate episodes")
    p.add_argument("project")
    p.add_argument("--personas", required=True, help="YAML list of personas (simulator/README.md)")
    p.add_argument("--n", type=int, default=1, help="episodes per persona")
    p.add_argument("--out", required=True)
    _endpoint_args(p, what="the agent")
    _endpoint_args(p, "customer_", what="the customer")
    p.set_defaults(fn=cmd_simulate)

    p = sub.add_parser("play", help="chat with a model under the real prompt (you, or an LLM, as customer)")
    p.add_argument("project")
    _endpoint_args(p, what="the agent")
    _endpoint_args(p, "customer_", required=False, what="an LLM customer (omit to type yourself)")
    p.add_argument("--context", help="session context JSON (fields of your context_template)")
    p.add_argument("--persona")
    p.add_argument("--goal")
    p.add_argument("--turns", type=int, default=3)
    p.set_defaults(fn=cmd_play)

    p = sub.add_parser("env", help="verifiers environment tools")
    esub = p.add_subparsers(dest="env_cmd", required=True)
    b = esub.add_parser("build", help="build a self-contained environment package")
    b.add_argument("project")
    b.add_argument("--out", required=True)
    b.add_argument("--name")
    b.add_argument("--version", default="0.1.0")
    b.add_argument(
        "--include-locked", action="store_true", help="also bundle locked splits (default: left out)"
    )
    b.set_defaults(fn=cmd_env)
    return ap


def main(argv=None) -> int:
    parser = build_parser()
    a, unknown = parser.parse_known_args(argv)
    if unknown and not (a.cmd == "train" and a.backend == "trl"):
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    a.extra = [x for x in unknown if x != "--"]  # trl: passed through to the TRL script
    try:
        return a.fn(a)
    except (FileNotFoundError, FileExistsError, ValueError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

"""python -m app.ml train      train, evaluate and save the triage model
python -m app.ml report     print the saved model's recorded results
python -m app.ml eval --seeds 5 --seed-start 300    check the saved model on fresh worlds"""
import argparse
import json
import sys

from app.ml.model import DEFAULT_MODEL, load_model


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.ml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("train")
    sub.add_parser("report")
    ev = sub.add_parser("eval")
    ev.add_argument("--seeds", type=int, default=5)
    ev.add_argument("--seed-start", type=int, default=300)
    args = ap.parse_args(argv)

    if args.cmd == "train":
        from app.ml.train import train_and_report

        meta = train_and_report()
        print(json.dumps(meta["metrics"]["episode_level_test_with_triage"], indent=2))
        return 0

    model = load_model()
    if model is None:
        print(f"No usable model at {DEFAULT_MODEL}. Run: python -m app.ml train", file=sys.stderr)
        return 1
    if args.cmd == "report":
        print(json.dumps(model.metadata, indent=2))
        return 0

    from app.ml.data import collect_many
    from app.ml.train import Fitted, episode_metrics

    seeds = list(range(args.seed_start, args.seed_start + args.seeds))
    used = set(model.metadata["train_seeds"]) | set(model.metadata["validation_seeds"])
    if used & set(seeds):
        print(f"WARNING: seeds {sorted(used & set(seeds))} were used in training or validation; results are optimistic.")
    data = collect_many(seeds)

    class _Wrapper:  # reuse episode_metrics with the loaded model
        threshold = model.threshold

        @staticmethod
        def probs(rows):
            return model.probabilities([r.features for r in rows])

    print("rules only :", json.dumps(episode_metrics(None, data)))
    print("with triage:", json.dumps(episode_metrics(_Wrapper, data)))  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

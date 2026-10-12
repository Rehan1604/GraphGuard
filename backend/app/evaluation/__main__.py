"""Reproduce the evaluation from the command line:  python -m app.evaluation --seed 42"""
import argparse
import json

from app.evaluation.runner import cached_report, format_report, summarize_seeds


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GraphGuard synthetic evaluation.")
    parser.add_argument("--dataset", choices=["benchmark", "simulator"], default="benchmark")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--events", type=int, default=240, help="stream length for the simulator dataset")
    parser.add_argument("--seeds", type=int, help="instead of one run, repeat on seeds 1..N and show how much the numbers vary")
    parser.add_argument("--json", help="also write the full report to this file")
    args = parser.parse_args()
    if args.seeds:
        summary = summarize_seeds(list(range(1, args.seeds + 1)))
        print(f"Repeated on {len(summary.seeds)} random datasets (seeds 1..{args.seeds}):")
        for name, m in summary.metrics.items():
            print(f"  {name:20s} mean {m['mean']:.3f}   min {m['min']:.3f}   max {m['max']:.3f}")
        return
    report = cached_report(args.dataset, args.seed, args.events)
    print(format_report(report))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report.model_dump(mode="json"), fh, indent=2)
        print(f"\nFull report written to {args.json}")


if __name__ == "__main__":
    main()
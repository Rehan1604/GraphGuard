"""Reproduce the evaluation from the command line:  python -m app.evaluation --seed 42"""
import argparse
import json

from app.evaluation.runner import cached_report, format_report, summarize_seeds


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GraphGuard synthetic evaluation.")
    parser.add_argument("--dataset", choices=["benchmark", "simulator"], default="benchmark")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--events", type=int, default=240, help="stream length for the simulator dataset")
    parser.add_argument("--seeds", type=int, help="instead of one run, repeat on N seeds and show how much the numbers vary")
    parser.add_argument("--seed-start", type=int, default=1, help="first seed for --seeds (default 1; seeds 101-120 were kept as a held-out check)")
    parser.add_argument("--json", help="also write the full report to this file")
    args = parser.parse_args()
    if args.seeds:
        seeds = list(range(args.seed_start, args.seed_start + args.seeds))
        summary = summarize_seeds(seeds)
        print(f"Repeated on {len(summary.seeds)} random datasets (seeds {seeds[0]}..{seeds[-1]}):")
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
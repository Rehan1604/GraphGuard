"""Train and honestly evaluate the alert-triage model.

Data split, by RANDOM SEED (each seed is a whole separate synthetic world), so no alert from a test world
was ever seen in training:
  train 1-30  ->  fit the models
  validate 31-40  ->  choose the model, calibrate probabilities, choose the cut-off
  test 201-230  ->  reported once, never used for any choice

Also reported: how the model does on a TYPE of benign look-alike it was never shown (leave-one-out),
because that is the question a sceptical reviewer should ask."""
from __future__ import annotations

import platform
from dataclasses import dataclass

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.evaluation.metrics import score_detector
from app.ml.data import LabelledFinding, SeedData, collect_many
from app.ml.features import FEATURE_SETS
from app.ml.model import TriageModel, save_model

TRAIN_SEEDS = list(range(1, 31))
VAL_SEEDS = list(range(31, 41))
TEST_SEEDS = list(range(201, 231))
LOOKALIKES = ("payroll", "split_bill", "marketplace_payout")
KEEP_TRUE_FRACTION = 0.95  # the cut-off keeps at least this share of genuine alerts on the validation worlds


def make_estimator(kind: str):
    if kind == "logistic":
        return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=3000))
    if kind == "gradient_boosting":
        return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.08, max_iter=150, random_state=0)
    raise ValueError(kind)


def matrix(rows: list[LabelledFinding], names: tuple[str, ...]):
    X = np.array([[r.features[n] for n in names] for r in rows], dtype=float)
    y = np.array([r.label for r in rows], dtype=int)
    return X, y


def choose_threshold(prob: np.ndarray, y: np.ndarray, keep: float = KEEP_TRUE_FRACTION) -> float:
    pos = np.sort(prob[y == 1])
    return float(pos[int(np.floor((1 - keep) * len(pos)))]) if len(pos) else 0.5


@dataclass
class Fitted:
    kind: str
    feature_set: str
    names: tuple[str, ...]
    estimator: object
    calibrator: IsotonicRegression
    threshold: float
    medians: dict[str, float]

    def probs(self, rows: list[LabelledFinding]) -> np.ndarray:
        if not rows:
            return np.array([])
        X, _ = matrix(rows, self.names)
        return self.calibrator.predict(self.estimator.predict_proba(X)[:, 1])

    def bundle(self) -> dict:
        return {"pipeline": self.estimator, "calibrator": self.calibrator, "threshold": self.threshold,
                "feature_names": list(self.names), "medians": self.medians}


def fit(train: list[LabelledFinding], val: list[LabelledFinding], kind: str, feature_set: str) -> Fitted:
    names = FEATURE_SETS[feature_set]
    X, y = matrix(train, names)
    est = make_estimator(kind).fit(X, y)
    Xv, yv = matrix(val, names)
    raw = est.predict_proba(Xv)[:, 1]
    cal = IsotonicRegression(out_of_bounds="clip").fit(raw, yv)
    thr = choose_threshold(cal.predict(raw), yv)
    medians = {n: float(np.median(X[:, i])) for i, n in enumerate(names)}
    return Fitted(kind, feature_set, names, est, cal, thr, medians)


def finding_metrics(fitted: Fitted, rows: list[LabelledFinding]) -> dict:
    """Alert-level numbers pooled over many worlds."""
    y = np.array([r.label for r in rows])
    p = fitted.probs(rows)
    kept = p >= fitted.threshold
    tp, fp = int(((y == 1) & kept).sum()), int(((y == 0) & kept).sum())
    return {
        "alerts": len(rows),
        "genuine_alerts": int(y.sum()),
        "rules_only_precision": round(float(y.mean()), 4),
        "roc_auc": round(float(roc_auc_score(y, p)), 4) if 0 < y.sum() < len(y) else None,
        "average_precision": round(float(average_precision_score(y, p)), 4) if y.sum() else None,
        "kept": int(kept.sum()),
        "kept_precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "genuine_kept": f"{tp}/{int(y.sum())}",
        "genuine_alerts_kept_fraction": round(tp / int(y.sum()), 4) if y.sum() else None,
        "false_alarms_removed": f"{int(((y == 0) & ~kept).sum())}/{int((y == 0).sum())}",
    }


def episode_metrics(fitted: Fitted | None, data: dict[int, SeedData]) -> dict:
    """What an analyst would see per world, scored exactly like the main evaluation. fitted=None means rules only."""
    precisions, recalls, tp_total, n_total, found, planted = [], [], 0, 0, 0, 0
    for seed, sd in data.items():
        if fitted is None:
            kept = sd.rows
        else:
            p = fitted.probs(sd.rows)
            kept = [r for r, pr in zip(sd.rows, p) if pr >= fitted.threshold]
        result = score_detector("x", [r.detection for r in kept], sd.dataset)
        if result.precision.value is not None:
            precisions.append(result.precision.value)
        recalls.append(result.recall.value)
        tp_total += result.precision.numerator
        n_total += result.precision.denominator
        found += result.recall.numerator
        planted += result.recall.denominator
    return {
        "worlds": len(data),
        "alerts_shown": n_total,
        "pooled_precision": round(tp_total / n_total, 4) if n_total else None,
        "precision_range_over_worlds": [round(min(precisions), 4), round(max(precisions), 4)] if precisions else None,
        "patterns_found": f"{found}/{planted}",
        "pooled_recall": round(found / planted, 4) if planted else None,
    }


def leave_one_lookalike_out(train, val, test, kind, feature_set) -> dict:
    out = {}
    for held in LOOKALIKES:
        f = fit([r for r in train if r.category != held], [r for r in val if r.category != held], kind, feature_set)
        unseen = [r for r in test if r.category == held]
        genuine = [r for r in test if r.label == 1]
        if not unseen:
            continue
        suppressed = float((f.probs(unseen) < f.threshold).mean())
        kept_true = float((f.probs(genuine) >= f.threshold).mean())
        out[held] = {"test_alerts": len(unseen), "suppressed_never_seen_type": round(suppressed, 4),
                     "genuine_alerts_still_kept": round(kept_true, 4)}
    return out


def train_and_report(save: bool = True, verbose: bool = True) -> dict:
    def say(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    say("collecting alerts from synthetic worlds ...")
    data = collect_many(TRAIN_SEEDS + VAL_SEEDS + TEST_SEEDS + [42])
    tr = [r for s in TRAIN_SEEDS for r in data[s].rows]
    va = [r for s in VAL_SEEDS for r in data[s].rows]
    te = [r for s in TEST_SEEDS for r in data[s].rows]
    say(f"alerts: train {len(tr)}, validation {len(va)}, test {len(te)}")

    table, candidates = [], {}
    for kind in ("logistic", "gradient_boosting"):
        for fs in ("shape", "shape_and_scale"):
            f = fit(tr, va, kind, fs)
            m_val = finding_metrics(f, va)
            candidates[(kind, fs)] = f
            table.append({"model": kind, "features": fs, "validation_average_precision": m_val["average_precision"],
                          "validation_roc_auc": m_val["roc_auc"]})
            say(f"  {kind:18s} {fs:16s} validation AP {m_val['average_precision']}  AUC {m_val['roc_auc']}")
    # DESIGN DECISION (made on principle, not by looking at test numbers): the shipped model uses SHAPE features only.
    # In this benchmark the benign look-alikes differ from planted patterns in how large the amounts are, because of how
    # the generator was written. Amount-size features would mostly learn the generator, so they are trained and reported
    # as an ablation but never shipped. Within shape-only models, pick the best validation average precision.
    shape_rows = [r for r in table if r["features"] == "shape"]
    choice = max(shape_rows, key=lambda r: r["validation_average_precision"])
    chosen = candidates[(choice["model"], choice["features"])]
    ablation = candidates[("gradient_boosting" if choice["model"] == "gradient_boosting" else "logistic", "shape_and_scale")]
    say(f"chosen: {choice['model']} with {choice['features']} features")

    test_data = {s: data[s] for s in TEST_SEEDS}
    metrics = {
        "alert_level_test": finding_metrics(chosen, te),
        "alert_level_validation": finding_metrics(chosen, va),
        "episode_level_test_rules_only": episode_metrics(None, test_data),
        "episode_level_test_with_triage": episode_metrics(chosen, test_data),
        "seed_42": {"rules_only": episode_metrics(None, {42: data[42]}), "with_triage": episode_metrics(chosen, {42: data[42]})},
        "all_candidates_on_test": [
            {"model": k, "features": fs, **{x: v for x, v in finding_metrics(f, te).items() if x in ("roc_auc", "average_precision", "kept_precision", "genuine_alerts_kept_fraction")}}
            for (k, fs), f in candidates.items()
        ],
        "leave_one_lookalike_out": leave_one_lookalike_out(tr, va, te, chosen.kind, chosen.feature_set),
        "ablation_with_amount_size_features": {
            "alert_level_test": finding_metrics(ablation, te),
            "leave_one_lookalike_out": leave_one_lookalike_out(tr, va, te, ablation.kind, ablation.feature_set),
            "note": "Reported to show how much of the apparent skill depends on the generator's amount sizes. NOT shipped.",
        },
    }
    metadata = {
        "version": f"triage-{chosen.kind}-{chosen.feature_set}-v1",
        "model": chosen.kind, "feature_set": chosen.feature_set, "features": list(chosen.names),
        "threshold": round(chosen.threshold, 4), "threshold_rule": f"keeps {KEEP_TRUE_FRACTION:.0%} of genuine alerts on the validation worlds",
        "train_seeds": TRAIN_SEEDS, "validation_seeds": VAL_SEEDS, "test_seeds": TEST_SEEDS,
        "label_definition": "1 = the alert matches a planted pattern in the benchmark answer key; 0 = benign look-alike, near-miss, or coincidence",
        "library_versions": {"scikit-learn": sklearn.__version__, "numpy": np.__version__, "python": platform.python_version()},
        "model_comparison_validation": table,
        "metrics": metrics,
        "caveats": [
            "Trained and tested on SYNTHETIC worlds produced by the same generator. Held-out seeds are new random worlds, not new kinds of world.",
            "The probability is calibrated on the benchmark. It is not a probability of wrongdoing and needs re-calibration on real data.",
            "The three benign look-alike types (payroll, split bill, marketplace payout) are fixed designs. The leave-one-out table shows what happens when one type is withheld.",
        ],
    }
    if save:
        save_model(chosen.bundle(), metadata)
        say("model saved")
    return metadata

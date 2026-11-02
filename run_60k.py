#!/usr/bin/env python3
"""AstroGuard-QFV: expand a FROZEN 18K cohort to a nested balanced 60K cohort.

Drop this file into the existing AstroGuard-QFV repository (beside run_18k.py).
The 18K manifest, its hash, observations, and RESULTS_18K are never modified.

The 60K cohort contains the exact 18K object IDs, plus 14K new eligible
objects from EACH broad ALeRCE pseudolabel class. It receives a NEW split.
No classification accuracy or formal-verification result is asserted here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path

import pandas as pd

from suite.common import sha256, stable_key, write_json

CLASSES = ("Periodic", "Stochastic", "Transient")
CLASSICAL = ("rf", "cnn", "bigru", "transformer", "classical24a", "classical24b")
MATCHED = ("quantum24", "classical24a", "classical24b")
SEEDS = (42, 142, 242, 342, 442)
REQUIRED = ("object_id", "broad_class", "original_class", "label_source",
            "photometry_file", "sampling_frame")


def manifest_paths(folder: Path, per_class: int):
    name = f"objects_{per_class * 3}_nested"
    return folder / f"{name}.csv", folder / f"{name}_freeze.json"


def verify_base(folder: Path, base_per_class: int) -> pd.DataFrame:
    file = folder / f"objects_{3 * base_per_class}.csv"
    if not file.is_file():
        raise FileNotFoundError(f"Existing frozen 18K manifest missing: {file}")
    info = folder / f"objects_{3 * base_per_class}_freeze.json"
    if info.is_file():
        frozen = json.loads(info.read_text(encoding="utf-8"))
        if frozen.get("sha256") != sha256(file):
            raise ValueError("The original 18K manifest does not match its freeze SHA256. STOP.")
    base = pd.read_csv(file, dtype={"object_id": str}, keep_default_na=False)
    missing = set(REQUIRED) - set(base.columns)
    if missing:
        raise ValueError(f"Existing manifest lacks required fields: {sorted(missing)}")
    if base["object_id"].duplicated().any():
        raise ValueError("Existing 18K manifest has duplicated object IDs")
    if len(base) != 3 * base_per_class:
        raise ValueError(f"Expected {3 * base_per_class} original objects; found {len(base)}")
    ct = base.broad_class.value_counts().to_dict()
    if any(ct.get(c, 0) != base_per_class for c in CLASSES):
        raise ValueError(f"Original cohort is not class balanced: {ct}")
    return base


def pool_from_checkpoint(folder: Path) -> pd.DataFrame:
    dbpath = folder / "collection_progress.sqlite3"
    if not dbpath.is_file():
        raise FileNotFoundError(
            f"ALeRCE checkpoint not found: {dbpath}. "
            "Use the existing collector to resume downloads first."
        )
    with sqlite3.connect(dbpath) as conn:
        query = """
            SELECT a.oid AS object_id,
                   a.broad AS broad_class,
                   a.subclass AS original_class,
                   'ALeRCE broker_model pseudolabel' AS label_source,
                   a.photometry_file AS photometry_file,
                   a.timestamp AS retrieved_at,
                   a.query_rank AS query_rank,
                   a.probability AS broker_probability,
                   a.n_detections AS raw_valid_detections
              FROM accepted AS a
             WHERE NOT EXISTS (
                SELECT 1 FROM candidates c
                 WHERE c.oid = a.oid AND c.broad <> a.broad
             )
        """
        try:
            pool = pd.read_sql_query(query, conn)
        except sqlite3.DatabaseError as ex:
            raise RuntimeError(
                "Checkpoint does not match the current AstroGuard collector schema"
            ) from ex
    if len(pool):
        pool["object_id"] = pool["object_id"].astype(str)
    if pool.object_id.duplicated().any():
        raise ValueError("Checkpoint returned multiple records for one object")
    return pool


def freeze_nested(folder: Path, *, per_class: int = 20000,
                  base_per_class: int = 6000, seed: int = 42) -> dict:
    """Select extra real eligible objects; keep all original 18K identities.

    Writes no manifest until the requested class quotas have all been met.
    Re-running is read-only once the completed manifest has been frozen.
    """
    folder = Path(folder).resolve()
    if per_class < base_per_class or base_per_class < 1:
        raise ValueError("Target per class must be >= original per class")
    base = verify_base(folder, base_per_class)
    file, info = manifest_paths(folder, per_class)
    if file.exists():
        if not info.exists():
            raise ValueError(f"Found an unfingerprinted 60K manifest: {file}")
        prior = json.loads(info.read_text(encoding="utf-8"))
        if sha256(file) != prior.get("sha256"):
            raise ValueError("60K frozen manifest SHA changed; refusing to overwrite")
        current = pd.read_csv(file, dtype={"object_id": str})
        if len(current) != per_class * 3 or not set(base.object_id).issubset(set(current.object_id)):
            raise ValueError("Previously frozen 60K cohort does not contain the original 18K")
        return {"frozen": True, "reused_existing": True,
                "path": str(file), "sha256": sha256(file), "n": len(current)}

    pool = pool_from_checkpoint(folder)
    labels = dict(zip(pool.object_id, pool.broad_class))
    mismatch = [str(row.object_id) for row in base.itertuples()
                if labels.get(str(row.object_id)) != row.broad_class]
    if mismatch:
        raise ValueError(
            f"Original manifest has {len(mismatch)} IDs missing from the unambiguous "
            f"checkpoint or with different labels, e.g. {mismatch[:3]}. "
            "Do not merge different collection identities without a separate audit."
        )

    base_ids = set(base.object_id)
    extras = pool[~pool.object_id.isin(base_ids)].copy()
    extras["sampling_frame"] = (
        "ALeRCE class-filtered ID-paginated frame; deterministic hash of eligible IDs"
    )
    extras["independent_label_verified"] = False
    extras["external_label_reference"] = ""
    extras["external_label"] = ""
    extras["source_verified"] = True  # data source provenance, NOT label truth
    extras["sort_key"] = extras.object_id.map(lambda v: stable_key(str(v), seed))

    selections = []
    deficits = {}
    for cls in CLASSES:
        sub = extras.loc[extras.broad_class == cls]
        available = len(sub)
        need = per_class - base_per_class
        if available < need:
            deficits[cls] = {"needed_new": need, "available_new": available,
                             "missing": need - available}
        selections.append(sub.sort_values(["sort_key", "object_id"]).head(need))
    if deficits:
        raise RuntimeError(
            "Not enough distinct eligible new objects to freeze 60K. "
            f"Class deficits: {json.dumps(deficits)}. "
            "Run `python run_60k.py collect --max-new 1000` repeatedly, "
            "and expand the broker candidate page cap if the queue runs empty."
        )

    additions = pd.concat(selections, ignore_index=True).drop(columns="sort_key")
    combined = pd.concat([base, additions], ignore_index=True, sort=False)
    if len(combined) != 3 * per_class or combined.object_id.duplicated().any():
        raise AssertionError("New nested cohort count/uniqueness invariant failed")
    counts = combined.broad_class.value_counts().to_dict()
    if any(counts.get(cls, 0) != per_class for cls in CLASSES):
        raise AssertionError("New nested cohort balance invariant failed")
    if not set(base.object_id).issubset(set(combined.object_id)):
        raise AssertionError("Nested cohort lost an original 18K object")

    # The existing preprocessor resolves relative paths from the manifest's parent.
    missing_photometry = []
    for row in combined.itertuples(index=False):
        p = Path(str(row.photometry_file))
        resolved = p if p.is_absolute() else folder / p
        if not resolved.is_file():
            missing_photometry.append(str(row.object_id))
            if len(missing_photometry) >= 10:
                break
    if missing_photometry:
        raise FileNotFoundError(
            f"Manifest points to missing light-curve CSVs, first IDs: {missing_photometry}. "
            "Restore/download the raw photometry; no 60K manifest was frozen."
        )
    combined["nested_cohort"] = True
    combined["included_in_original_18k"] = combined.object_id.isin(base_ids)
    combined["independent_label_verified"] = False
    temp = file.with_suffix(".csv.tmp")
    combined.to_csv(temp, index=False)
    temp.replace(file)
    report = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "file": file.name, "sha256": sha256(file),
        "seed": seed, "count": len(combined), "per_broad_class": per_class,
        "counts": counts, "original_cohort_manifest": f"objects_{3*base_per_class}.csv",
        "original_cohort_sha256": sha256(folder / f"objects_{3 * base_per_class}.csv"),
        "original_object_ids_retained": len(base_ids),
        "new_object_ids": len(additions),
        "selection": "Original frozen objects plus stable-hash new eligible objects per class",
        "label_warning": "Broker predictions are pseudolabels, not confirmed astronomical ground truth",
        "sampling_warning": "Balanced class-filtered cohort is not a natural-prevalence ZTF sample",
        "split_warning": "60K preparation creates a NEW object-disjoint split, it does not preserve 18K train/val/test assignments"
    }
    write_json(info, report)
    return {"frozen": True, "reused_existing": False, "path": str(file),
            "sha256": report["sha256"], "n": len(combined),
            "old": len(base), "new": len(additions), "by_class": counts}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("stage", choices=("status", "collect", "freeze", "prepare", "train", "analyze", "verify"))
    p.add_argument("--input", default="input")
    p.add_argument("--output", default="RESULTS_60K")
    p.add_argument("--per-class", type=int, default=20000)
    p.add_argument("--base-per-class", type=int, default=6000)
    p.add_argument("--max-new", type=int, default=1000)
    p.add_argument("--request-delay", type=float, default=.2)
    p.add_argument("--retry-errors", action="store_true")
    p.add_argument("--profile", choices=("classical", "matched", "smoke"), default="classical")
    p.add_argument("--tag", help="Separate result folder for changed epochs/budgets")
    p.add_argument("--models", nargs="+", help="Optional model names to train")
    p.add_argument("--seeds", nargs="+", type=int, default=list(SEEDS))
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--matched-train", type=int, default=3000)
    p.add_argument("--bootstrap", type=int, default=3000)
    p.add_argument("--device", choices=("cpu", "cuda", "auto"), default="auto")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--jar", help="Path to official TLC tla2tools.jar")
    args = p.parse_args(argv)
    folder, output = Path(args.input).resolve(), Path(args.output).resolve()
    cohort, freeze = manifest_paths(folder, args.per_class)
    if args.per_class < args.base_per_class:
        p.error("--per-class must be >= --base-per-class")
    if args.stage == "status":
        print("Original 18K:", folder / f"objects_{3*args.base_per_class}.csv")
        if (folder / f"objects_{3*args.base_per_class}.csv").exists():
            base = verify_base(folder, args.base_per_class)
            print("Original objects:", len(base), "by class:", base.broad_class.value_counts().to_dict())
        print("New 60K:", cohort, "FROZEN" if cohort.is_file() else "NOT YET FROZEN")
        db = folder / "collection_progress.sqlite3"
        if db.is_file():
            accepted = pool_from_checkpoint(folder)
            print("Unambiguous accepted by class:", accepted.broad_class.value_counts().to_dict())
        return
    if args.stage == "collect":
        from run_18k_collect import collect_18k
        result = collect_18k(input_dir=str(folder), out_dir=str(output / "collection"),
                             per_class=args.per_class, max_new=args.max_new,
                             delay=args.request_delay, retry_errors=args.retry_errors,
                             seed=args.seed)
        print("Collection:", json.dumps(result, indent=2, default=str))
        print("NOTE: the collector's objects_60000.csv is a staging snapshot. "
              "Use `freeze` to generate objects_60000_nested.csv preserving the original 18K IDs.")
        return
    if args.stage == "freeze":
        print(json.dumps(freeze_nested(folder, per_class=args.per_class,
                                       base_per_class=args.base_per_class,
                                       seed=args.seed), indent=2))
        return
    if args.stage != "verify":
        if not cohort.is_file() or not freeze.is_file():
            raise FileNotFoundError("First run: python run_60k.py freeze")
        frozen = json.loads(freeze.read_text(encoding="utf-8"))
        if sha256(cohort) != frozen.get("sha256"):
            raise RuntimeError("60K manifest changed since freezing; STOP")
        df = pd.read_csv(cohort, dtype={"object_id": str})
        if len(df) != args.per_class*3 or df.object_id.duplicated().any():
            raise RuntimeError("Frozen 60K manifest is incomplete or duplicated")

    prepared = output / "prepared"
    if args.stage == "prepare":
        from suite.preprocess_18k import prepare
        result = prepare(cohort, prepared, seed=args.seed)
        print(json.dumps(result, indent=2))
        if result["n_valid"] != args.per_class * 3:
            raise RuntimeError(
                f"Only {result['n_valid']} of {3*args.per_class} curves passed preprocessing. "
                "Do not describe this as an executed 60K experiment."
            )
        return
    if args.stage not in ("verify",) and not (prepared / "dataset_report.json").is_file():
        raise FileNotFoundError("First run: python run_60k.py prepare")

    # The original suite config describes an older, larger experiment and a
    # 70/15/15 split. Override IN MEMORY so the 60K evidence metadata uses
    # the actual 65/15/20 splitter, without changing the existing repo config.
    import suite.common as common
    original_config = common.config
    def config_60k():
        config = original_config()
        config["split"] = {"train": .65, "val": .15, "test": .20}
        config["dataset_target"] = {
            "total_eligible_objects": args.per_class * 3,
            "target_per_broad_class": args.per_class,
            "sampling_frame": "ALeRCE class-filtered nested pseudolabel cohort",
            "achieved_size_must_be_reported": True}
        config["full"]["expected_target_train_if_cohort_attained"] = int(args.per_class * 3 * .65)
        config["full"]["expected_target_validation_if_cohort_attained"] = int(args.per_class * 3 * .15)
        config["full"]["expected_target_test_if_cohort_attained"] = int(args.per_class * 3 * .20)
        return config
    common.config = config_60k
    import run_large
    run_large.config = config_60k
    experiment = run_large.main
    models = (args.models if args.models else
              list(MATCHED if args.profile == "matched" else
                   ("rf", "classical24a", "classical24b") if args.profile == "smoke" else CLASSICAL))
    if args.profile == "matched":
        limit = args.matched_train
    elif args.profile == "smoke":
        limit = 90
    else:
        limit = None  # all ~39,000 training objects for classical profile
    tag = args.tag or args.profile
    path = output / tag if args.stage != "verify" else output / "formal_verification"
    cmd = ["--stage", args.stage, "--input", str(cohort), "--prepared", str(prepared),
           "--output", str(path), "--preset", "full", "--seed", str(args.seed),
           "--device", args.device, "--bootstrap", str(args.bootstrap), "--fail-fast"]
    if args.stage in ("train", "analyze"):
        cmd += ["--models", *models, "--seeds", *map(str, args.seeds)]
    if args.stage == "train":
        cmd += ["--epochs", str(2 if args.profile == "smoke" else args.epochs),
                "--batch", str(args.batch), "--objective", "supervised",
                "--prefixes", "2", "5", "10", "20", "40", "80", "128",
                "--include-predictions-in-zip"]
        if limit is not None: cmd += ["--max-train", str(limit)]
    if args.jar and args.stage == "verify":
        cmd += ["--jar", str(Path(args.jar).resolve())]
    if args.stage == "verify" and not args.jar:
        raise ValueError("Actual TLC execution requires --jar PATH_TO_OFFICIAL_tla2tools.jar")
    if args.stage == "train" and args.profile == "matched" and args.device != "cpu":
        print("WARNING: Quantum24 PennyLane default.qubit is a CPU simulator; "
              "a CUDA device may not be supported for this profile.")
    write_json(output / f"RUN_60K_{tag}_CONFIG.json", {
        "cohort": str(cohort) if cohort.exists() else None, "sha256": sha256(cohort) if cohort.exists() else None,
        "stage": args.stage, "profile": args.profile, "models": models, "seeds": args.seeds,
        "train_object_budget": limit, "training_object_count_full": None if limit else "actual prepared train split",
        "epochs": args.epochs, "objective": "supervised",
        "limitation": "Broker pseudolabels; offline study, not true-label or deployment validation"})
    result = experiment(cmd)
    # The shared original packaging helper still spells '18K'. Rename only
    # that ZIP name, not experiment contents; avoid a misleading 60K filename.
    for src in path.glob("AstroGuard_QFV_18K_*_Results.zip"):
        src.rename(src.with_name(src.name.replace("_18K_", "_60K_")))
    if isinstance(result, dict):
        print("Stage:", args.stage, "Completed. Evidence:", path)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Read-only diagnostics for the nested 60K AstroGuard-QFV study.

Drop beside run_60k.py. Never downloads data, never edits a manifest/checkpoint.

  frame-status  how the ALeRCE candidate frame limits each class (run BEFORE collecting)
  audit         dataset-properties tables for the frozen manifest (for the paper)
  bands         test accuracy / macro-F1 split by ALeRCE probability band and discovery year

Why: reviewers asked how objects were chosen and whether the sample is representative.
The collector pages ALeRCE by object ID (ascending) and hashes within that finite frame,
so the cohort is biased toward early-numbered ZTF objects. These stages MEASURE that bias
so it can be reported instead of asserted.

  python run_60k_extras.py frame-status --input input --per-class 20000
  python run_60k_extras.py audit  --input input --manifest input/objects_60000_nested.csv
  python run_60k_extras.py bands  --manifest input/objects_60000_nested.csv \
        --predictions RESULTS_60K/classical/trained --output RESULTS_60K/bands
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

CLASSES = ("Periodic", "Stochastic", "Transient")
YEAR_RE = re.compile(r"^ZTF(\d{2})")


def oid_year(oid: str):
    m = YEAR_RE.match(str(oid))
    return 2000 + int(m.group(1)) if m else np.nan


def _read(db: sqlite3.Connection, sql: str) -> pd.DataFrame:
    return pd.read_sql_query(sql, db)


# ----------------------------------------------------------------------------- frame-status
def frame_status(folder: Path, per_class: int, out: Path | None = None) -> dict:
    dbfile = folder / "collection_progress.sqlite3"
    if not dbfile.is_file():
        raise FileNotFoundError(dbfile)
    db = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True)
    cand = _read(db, "SELECT broad, subclass, COUNT(DISTINCT oid) AS candidates FROM candidates GROUP BY broad, subclass")
    att = _read(db, "SELECT subclass, status, COUNT(*) n FROM attempts GROUP BY subclass, status")
    acc = _read(db, "SELECT subclass, COUNT(*) accepted FROM accepted GROUP BY subclass")
    pages = _read(db, "SELECT subclass, last_page, exhausted FROM pages")
    pend = _read(db, """SELECT c.subclass, COUNT(DISTINCT c.oid) untried FROM candidates c
                        WHERE c.oid NOT IN (SELECT oid FROM attempts) GROUP BY c.subclass""")
    years = _read(db, "SELECT oid, broad FROM accepted")
    db.close()
    wide = att.pivot_table(index="subclass", columns="status", values="n", fill_value=0).reset_index()
    for c in ("ACCEPTED", "INELIGIBLE", "REQUEST_ERROR"):
        if c not in wide:
            wide[c] = 0
    t = (cand.merge(pages, on="subclass", how="left").merge(wide, on="subclass", how="left")
         .merge(acc, on="subclass", how="left").merge(pend, on="subclass", how="left").fillna(0))
    t["eligibility_rate"] = np.where((t.ACCEPTED + t.INELIGIBLE) > 0,
                                     t.ACCEPTED / (t.ACCEPTED + t.INELIGIBLE).clip(lower=1), np.nan)
    t["projected_extra_eligible"] = (t.untried * t.eligibility_rate.fillna(0)).round().astype(int)
    t["projected_total_eligible"] = t.accepted.astype(int) + t.projected_extra_eligible
    by_broad = t.groupby("broad")[["candidates", "accepted", "untried", "projected_total_eligible"]].sum()
    by_broad["quota"] = per_class
    by_broad["shortfall"] = (per_class - by_broad.projected_total_eligible).clip(lower=0)
    years["year"] = years.oid.map(oid_year)
    ydist = years.groupby(["broad", "year"]).size().unstack(fill_value=0)
    print("\n== Frame by subclass (page cap + oid-ascending order => finite, early-ID frame) ==")
    print(t.to_string(index=False))
    print("\n== Projected capacity per broad class ==")
    print(by_broad.to_string())
    print("\n== ZTF object-ID year prefix of ACCEPTED objects (discovery-year proxy) ==")
    print(ydist.to_string())
    short = by_broad[by_broad.shortfall > 0]
    if len(short):
        print("\nWARNING: projected eligible objects fall short of the quota for:",
              ", ".join(short.index), "\n  -> raise the page cap / re-query, or reduce --per-class and report the"
              " class counts you actually obtained. Do NOT silently under-fill a 'balanced' cohort.")
    exhausted = t[(t.exhausted == 1) | (t.last_page == 0)]
    if len(exhausted):
        print("\nNote: subclasses whose candidate list is fully exhausted (or never queried):",
              ", ".join(exhausted.subclass))
    if out:
        out.mkdir(parents=True, exist_ok=True)
        t.to_csv(out / "frame_status_by_subclass.csv", index=False)
        by_broad.to_csv(out / "frame_status_by_class.csv")
        ydist.to_csv(out / "accepted_oid_year.csv")
    return {"by_subclass": t, "by_class": by_broad, "year": ydist}


# ----------------------------------------------------------------------------- audit
def _span_days(path: Path):
    try:
        d = pd.read_csv(path, usecols=["mjd"])
        return float(d.mjd.max() - d.mjd.min())
    except Exception:
        return np.nan


def audit(folder: Path, manifest: Path, out: Path) -> pd.DataFrame:
    df = pd.read_csv(manifest, dtype={"object_id": str}, keep_default_na=False)
    df["oid_year"] = df.object_id.map(oid_year)
    df["broker_probability"] = pd.to_numeric(df.get("broker_probability", np.nan), errors="coerce")
    df["n_det"] = pd.to_numeric(df.get("raw_valid_detections", np.nan), errors="coerce")
    spans = []
    for f in df.photometry_file:
        p = Path(str(f))
        spans.append(_span_days(p if p.is_absolute() else folder / p))
    df["span_days"] = spans
    out.mkdir(parents=True, exist_ok=True)
    df.drop(columns=["photometry_file"], errors="ignore").to_csv(out / "frame_audit_objects.csv", index=False)

    def q(s):
        return f"{s.median():.0f} ({s.quantile(.25):.0f}--{s.quantile(.75):.0f})"
    rows = []
    for (b, sc), g in df.groupby(["broad_class", "original_class"]):
        rows.append({"class": b, "subclass": sc, "N": len(g), "n_det median(IQR)": q(g.n_det),
                     "span_days median(IQR)": q(g.span_days.dropna()) if g.span_days.notna().any() else "n/a",
                     "ALeRCE prob median": f"{g.broker_probability.median():.2f}" if g.broker_probability.notna().any() else "n/a",
                     "oid years": f"{int(g.oid_year.min())}--{int(g.oid_year.max())}" if g.oid_year.notna().any() else "n/a"})
    t = pd.DataFrame(rows)
    t.to_csv(out / "dataset_properties.csv", index=False)
    yr = df.groupby(["broad_class", "oid_year"]).size().unstack(fill_value=0)
    yr.to_csv(out / "oid_year_by_class.csv")
    if "included_in_original_18k" in df:
        df.groupby(["broad_class", "included_in_original_18k"]).size().to_csv(out / "nested_composition.csv")
    print(t.to_string(index=False))
    print("\nObject-ID year prefix by class:\n", yr.to_string())
    print("\nLaTeX rows (class & subclass & N & detections & span & prob):")
    for r in rows:
        print(f"{r['class']} & {r['subclass']} & {r['N']:,} & {r['n_det median(IQR)']} & "
              f"{r['span_days median(IQR)']} & {r['ALeRCE prob median']} \\\\")
    top = yr.sum(axis=0).sort_values(ascending=False)
    if len(top) and top.iloc[0] / top.sum() > .5:
        print(f"\nWARNING: {top.index[0]:.0f}-numbered objects are {100*top.iloc[0]/top.sum():.0f}% of the cohort;"
              " state this frame limitation in the paper.")
    return t


# ----------------------------------------------------------------------------- bands
def bands(manifest: Path, pred_root: Path, out: Path, edges=(0, .5, .7, .9, 1.0001), prefix=128) -> pd.DataFrame:
    from sklearn.metrics import f1_score
    man = pd.read_csv(manifest, dtype={"object_id": str}, keep_default_na=False)
    man["prob"] = pd.to_numeric(man.get("broker_probability", np.nan), errors="coerce")
    man["year"] = man.object_id.map(oid_year)
    man["band"] = pd.cut(man.prob, bins=list(edges), right=False)
    info = man.set_index("object_id")[["band", "year"]]
    files = sorted(pred_root.rglob("predictions.csv"))
    if not files:
        raise FileNotFoundError(f"No predictions.csv under {pred_root}")
    rows = []
    for f in files:
        p = pd.read_csv(f, dtype={"object_id": str})
        p = p[(p.split == "test") & (p.prefix == prefix)].join(info, on="object_id")
        for col in ("band", "year"):
            for key, g in p.groupby(col, observed=True):
                if len(g) < 30:
                    continue
                rows.append({"model": g.model.iloc[0], "seed": int(g.seed.iloc[0]), "stratum": col, "value": str(key),
                             "n": len(g), "accuracy": float((g.prediction == g.broad_class).mean()),
                             "macro_f1": float(f1_score(g.broad_class, g.prediction, labels=list(CLASSES),
                                                        average="macro", zero_division=0))})
    r = pd.DataFrame(rows)
    out.mkdir(parents=True, exist_ok=True)
    r.to_csv(out / "bands_per_seed.csv", index=False)
    s = (r.groupby(["model", "stratum", "value"]).agg(n=("n", "mean"), acc=("accuracy", "mean"), acc_sd=("accuracy", "std"),
                                                         f1=("macro_f1", "mean"), f1_sd=("macro_f1", "std")).reset_index())
    s.to_csv(out / "bands_summary.csv", index=False)
    print(s.to_string(index=False))
    print("\nIf macro-F1 rises steeply with ALeRCE probability, the headline score mostly measures agreement on"
          " the broker's easy objects; say so.")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=("frame-status", "audit", "bands"))
    ap.add_argument("--input", default="input")
    ap.add_argument("--manifest", default="input/objects_60000_nested.csv")
    ap.add_argument("--predictions", default="RESULTS_60K/classical/trained")
    ap.add_argument("--output", default="RESULTS_60K/audit")
    ap.add_argument("--per-class", type=int, default=20000)
    a = ap.parse_args(argv)
    folder, out = Path(a.input).resolve(), Path(a.output).resolve()
    if a.stage == "frame-status":
        frame_status(folder, a.per_class, out)
    elif a.stage == "audit":
        audit(folder, Path(a.manifest).resolve(), out)
    else:
        bands(Path(a.manifest).resolve(), Path(a.predictions).resolve(), out)


if __name__ == "__main__":
    main()

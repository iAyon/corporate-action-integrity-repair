"""
Orchestration pipeline for detection and proposed fix generation.
Executes detectors across Parquet datasets and generates standard JSON outputs.
"""

import json
import glob
import time
from pathlib import Path
from typing import List, Optional
import polars as pl

from src.config import PARQUET_DIR, PROPOSED_FIXES_DIR
from src.detectors.split_detector import SplitDetector
from src.detectors.dividend_detector import DividendDetector
from src.detectors.company_detector import CompanyDetector
from src.models.schemas import ProposedFix


def run_full_detection(limit_files: Optional[int] = None, output_filename: str = "proposed_fixes.json") -> List[ProposedFix]:
    """
    Executes SplitDetector, DividendDetector, and CompanyDetector across Parquet files.
    """
    files = sorted(glob.glob(str(PARQUET_DIR / "*.parquet")))
    if not files:
        raise FileNotFoundError(f"No Parquet files found in {PARQUET_DIR}. Run conversion first.")

    if limit_files:
        files = files[:limit_files]

    print(f"Running detection across {len(files)} Parquet file(s)...")
    split_det = SplitDetector()
    div_det = DividendDetector()
    comp_det = CompanyDetector()

    all_fixes: List[ProposedFix] = []
    t0 = time.time()

    for idx, fpath in enumerate(files, 1):
        f_start = time.time()
        df = pl.read_parquet(fpath)

        # Run Detectors
        split_alerts = split_det.run(df)
        div_alerts = div_det.run(df)
        comp_alerts = comp_det.run(df)

        split_fixes = split_det.to_proposed_fixes(split_alerts)
        div_fixes = div_det.to_proposed_fixes(div_alerts)
        comp_fixes = comp_det.to_proposed_fixes(comp_alerts)

        file_fixes = split_fixes + div_fixes + comp_fixes
        all_fixes.extend(file_fixes)

        print(
            f"[{idx}/{len(files)}] {Path(fpath).name}: {len(df):,} rows -> "
            f"{len(split_fixes)} split fixes, {len(div_fixes)} div fixes, {len(comp_fixes)} company fixes "
            f"({time.time() - f_start:.1f}s)"
        )

    out_path = PROPOSED_FIXES_DIR / output_filename
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([fix.model_dump() for fix in all_fixes], f, indent=2)

    total_time = time.time() - t0
    print(f"\nCompleted! Generated {len(all_fixes):,} proposed fixes in {total_time:.1f}s.")
    print(f"Saved results to {out_path}")
    return all_fixes


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run detection pipeline across Parquet files")
    parser.add_argument("--limit-files", type=int, default=3, help="Limit number of parquet files (default: 3)")
    parser.add_argument("--output", type=str, default="proposed_fixes.json", help="Output JSON filename")
    args = parser.parse_args()

    run_full_detection(limit_files=args.limit_files, output_filename=args.output)

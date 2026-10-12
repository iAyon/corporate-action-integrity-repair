"""
High-performance ETL module to convert raw compressed CSV zip files
into optimized, compressed Apache Parquet files using Polars streaming.
"""

import os
import glob
import time
import zipfile
from pathlib import Path
from typing import Optional, List
import polars as pl
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from src.config import RAW_ZIP_DIR, PARQUET_DIR

console = Console()

POLARS_SCHEMA_OVERRIDES = {
    "CIK": pl.String,
    "DATE": pl.String,
    "SPLIT_RATIO": pl.Float64,
    "EX_DIVIDEND": pl.Float64,
    "OPEN": pl.Float64,
    "HIGH": pl.Float64,
    "LOW": pl.Float64,
    "CLOSE": pl.Float64,
    "VOLUME": pl.Float64,
    "ADJ_OPEN": pl.Float64,
    "ADJ_HIGH": pl.Float64,
    "ADJ_LOW": pl.Float64,
    "ADJ_CLOSE": pl.Float64,
    "ADJ_VOLUME": pl.Float64,
    "ADJ_FACTOR": pl.Float64,
    "CHANGE": pl.Float64,
    "PERCENT_CHANGE": pl.Float64,
}


def find_zip_files(raw_dir: Path = RAW_ZIP_DIR) -> List[Path]:
    """Find and return all matching zip files in sorted order."""
    pattern = str(raw_dir / "stock_prices_uscomp_all_file-*.zip")
    files = sorted([Path(p) for p in glob.glob(pattern)])
    return files


def convert_single_zip_to_parquet(zip_path: Path, output_dir: Path = PARQUET_DIR, overwrite: bool = False) -> Optional[Path]:
    """
    Extracts the internal CSV from the zip file and saves it as a compressed Parquet file.
    Does not write huge uncompressed CSVs to disk, streaming directly into Polars.
    """
    stem = zip_path.stem  # e.g., stock_prices_uscomp_all_file-01
    out_parquet = output_dir / f"{stem}.parquet"

    if out_parquet.exists() and not overwrite:
        console.print(f"[yellow]Skipping {out_parquet.name} (already exists). Use overwrite=True to replace.[/yellow]")
        return out_parquet

    start_time = time.time()
    with zipfile.ZipFile(zip_path) as z:
        csv_names = [name for name in z.namelist() if name.endswith(".csv")]
        if not csv_names:
            console.print(f"[red]Error: No CSV file found in {zip_path.name}[/red]")
            return None
        
        csv_filename = csv_names[0]
        with z.open(csv_filename) as f:
            df = pl.read_csv(
                f,
                schema_overrides=POLARS_SCHEMA_OVERRIDES,
                ignore_errors=True,
                truncate_ragged_lines=True
            )
            
            # Sort by SECURITY_ID and DATE for optimal temporal time-series queries
            df = df.sort(["SECURITY_ID", "DATE"])
            df.write_parquet(out_parquet, compression="zstd")
            
    elapsed = time.time() - start_time
    file_size_mb = out_parquet.stat().st_size / (1024 * 1024)
    print(
        f"[OK] Converted {zip_path.name} -> {out_parquet.name} "
        f"({len(df):,} rows, {file_size_mb:.1f} MB in {elapsed:.1f}s)"
    )
    return out_parquet


def convert_all(limit: Optional[int] = None, overwrite: bool = False):
    """Converts raw zip archives to Parquet files."""
    zip_files = find_zip_files()
    if not zip_files:
        console.print(f"[red]No raw zip files found in {RAW_ZIP_DIR}[/red]")
        return

    if limit:
        zip_files = zip_files[:limit]

    print(f"Found {len(zip_files)} zip file(s) to process into Parquet...")
    t0 = time.time()
    
    for idx, zf in enumerate(zip_files, 1):
        print(f"[{idx}/{len(zip_files)}] Processing {zf.name}...")
        convert_single_zip_to_parquet(zf, overwrite=overwrite)

    total_time = time.time() - t0
    print(f"Done! Processed {len(zip_files)} files in {total_time:.1f}s.")


def get_lazy_dataset() -> pl.LazyFrame:
    """
    Returns a unified Polars LazyFrame across all converted Parquet files.
    Allows zero-copy, highly parallel out-of-core scanning.
    """
    parquet_files = list(PARQUET_DIR.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No Parquet files found in {PARQUET_DIR}. Run conversion first.")
    
    return pl.scan_parquet(str(PARQUET_DIR / "*.parquet"))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Convert raw CSV zips to high-performance Parquet format")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of zip files to process")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Parquet files")
    args = parser.parse_args()

    convert_all(limit=args.limit, overwrite=args.overwrite)

"""Diagnostic script that times processing with the canvodpy pipeline."""

import csv
import gc
import time
from datetime import datetime
from pathlib import Path

from canvod.config import load_config
from canvod.store import GnssResearchSite
from canvodpy.orchestrator import PipelineOrchestrator


class TimingLogger:
    """CSV logger for timing data with append support."""

    def __init__(self, filename=None, expected_receivers=None):
        # Default to .logs directory in project root
        if filename is None:
            filename = load_config().processing.logging.get_log_dir() / "timing_log.csv"
        self.filename = filename
        self.file_exists = Path(filename).exists()

        # Define all possible receivers upfront
        if expected_receivers is None:
            expected_receivers = [
                "canopy_01",
                "canopy_02",
                "reference_01",
                "reference_02",
            ]
        self.expected_receivers = sorted(expected_receivers)

        # Fixed fieldnames for consistent CSV structure
        self.fieldnames = (
            ["day", "start_time", "end_time"]
            + [f"{name}_seconds" for name in self.expected_receivers]
            + ["total_seconds"]
        )

    def log(self, day, start_time, end_time, receiver_times, total_time):
        """Log a day's processing times."""
        row = {
            "day": day,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "total_seconds": round(total_time, 2),
        }

        # Add all expected receivers (0.0 if not present this day)
        for receiver_name in self.expected_receivers:
            col_name = f"{receiver_name}_seconds"
            row[col_name] = round(receiver_times.get(receiver_name, 0.0), 2)

        # Write with consistent fieldnames
        mode = "a" if self.file_exists else "w"
        write_header = not self.file_exists

        try:
            with open(self.filename, mode, newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames)

                if write_header:
                    writer.writeheader()

                writer.writerow(row)

            self.file_exists = True
            print(f"📊 Logged timing for {day}")
            print(f"   File: {Path(self.filename).absolute()}")

        except Exception as e:
            print(f"✗ Failed to log timing: {e}")

    def save(self):
        """Compatibility method - does nothing since we write immediately."""


def diagnose_processing(
    start_from: str | None = None,
    end_at: str | None = None,
) -> None:
    """Run diagnostic processing with canvodpy pipeline.

    Parameters
    ----------
    start_from : str, optional
        YYYYDOY string to start from (e.g., "2025278"). If None, starts from
        beginning.
    end_at : str, optional
        YYYYDOY string to end at (e.g., "2025280"). If None, processes all
        remaining.

    Examples
    --------
    >>> # Process everything
    >>> diagnose_processing()

    >>> # Start from a specific date
    >>> diagnose_processing(start_from="2024183")  # July 1, 2024

    >>> # Process a specific range
    >>> diagnose_processing(start_from="2025278", end_at="2025280")

    """
    print("=" * 80)
    print("TIMING DIAGNOSTIC WITH GENERALIZED PIPELINE")
    print("=" * 80)
    print(f"Start time: {datetime.now()}")
    cfg = load_config()
    keep_vars = cfg.processing.params.keep_gnss_observables
    gnss_store_strategy = cfg.processing.storage.gnss_store_strategy
    print(f"gnss_store_strategy: {gnss_store_strategy}")
    print(f"keep_gnss_observables: {keep_vars}")
    if start_from:
        print(f"Starting from: {start_from}")
    if end_at:
        print(f"Ending at: {end_at}")
    print()

    # Initialize site and orchestrator
    site = GnssResearchSite(site_name="ExampleSite")
    proc = cfg.processing.processing
    # Get all configured receivers
    all_receivers = sorted(site.active_receivers.keys())
    timing_log = TimingLogger(expected_receivers=all_receivers)

    counter = 0
    garbage_collect = 0
    days_since_rechunk = 0

    # Main processing loop
    # Context manager ensures orchestrator resources are released on exit
    # All params from config — no hardcoded defaults
    resources = proc.resolve_resources()
    with PipelineOrchestrator(
        site=site,
        dry_run=False,
        n_max_workers=resources["n_workers"],
        days_per_batch=proc.days_per_batch,
        config=cfg,
    ) as orchestrator:
        for date_key, datasets, receiver_times in orchestrator.process_by_date(
            keep_vars=keep_vars, start_from=start_from, end_at=end_at
        ):
            day_start_time = datetime.now()  # Capture start time

            print(f"\n{'=' * 80}")
            print(f"Processing {date_key}")
            print(f"{'=' * 80}\n")

            try:
                # Track timing per receiver
                for receiver_name, ds in datasets.items():
                    print(f"\n{'─' * 80}")
                    print(f"{receiver_name.upper()} PROCESSING")
                    print(f"{'─' * 80}")
                    print(f"  Dataset shape: {dict(ds.sizes)}")
                    print(f"  Processing time: {receiver_times[receiver_name]:.2f}s")

                day_end_time = datetime.now()  # Capture end time
                # Calculate actual total from receiver times
                total_time = sum(receiver_times.values())

                # Summary
                print(f"\n{'=' * 80}")
                print("SUMMARY")
                print(f"{'=' * 80}")
                for receiver_name, ds in datasets.items():
                    print(
                        f"{receiver_name}: {dict(ds.sizes)} "
                        f"({receiver_times[receiver_name]:.2f}s)"
                    )
                print(f"Total time: {total_time:.2f}s")
                print(f"\n✓ Successfully processed {date_key}")

                # LOG TO CSV with actual receiver times
                timing_log.log(
                    day=date_key,
                    start_time=day_start_time,
                    end_time=day_end_time,
                    receiver_times=receiver_times,
                    total_time=total_time,
                )

                days_since_rechunk += 1

            except Exception as e:
                print(f"\n✗ Failed {date_key}: {e}")
                import traceback

                traceback.print_exc()

            finally:
                counter += 1
                garbage_collect += 1

                # Rechunking logic commented out (as in original)
                # if days_since_rechunk >= 2:
                #     print(f"\n{'='*80}")
                #     print("🔄 RECHUNKING STORE (every 2 days)")
                #     print(f"{'='*80}\n")
                #     # Rechunking logic would go here
                #     days_since_rechunk = 0

            # Garbage collection every 5 days
            if garbage_collect % 5 == 0:
                print("\n💤 Pausing for 60s before garbage collection...")
                time.sleep(60)
                print("\n🗑️  Running garbage collection...")
                gc.collect()
                print("✓ Garbage collection done")

        # Optional: Stop after N days for diagnostics
        # if counter == 30:
        #     print(f"\n🛑 Reached 30 days of processing, stopping for diagnostics.")
        #     break

    print(f"\n{'=' * 80}")
    print(f"End time: {datetime.now()}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    # Process everything
    diagnose_processing()  # tart_from="20250806")

    # Start from a specific date
    # diagnose_processing(start_from="2024183")  # July 1, 2024

    # Process a specific range
    # diagnose_processing(start_from="2025278", end_at="2025280")

    # Process specific test range (Oct 26, 2025)
    # diagnose_processing(start_from="2025299", end_at="2025300")

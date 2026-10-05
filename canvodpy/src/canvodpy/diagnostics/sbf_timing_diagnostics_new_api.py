"""Diagnostic script for canvodpy using NEW API.

timing_diagnostics_new_api.py

This script processes RINEX data using the new canvodpy.api (Site + Pipeline).
Compare results with timing_diagnostics_script.py (old orchestrator) to verify
equivalence.

New API: Site → Pipeline → process_range()
Old API: GnssResearchSite → PipelineOrchestrator → process_by_date()
"""

import csv
import gc
import time
from datetime import datetime
from pathlib import Path

from canvod.config import load_config
from canvodpy.api import Site


class TimingLogger:
    """CSV logger for timing data with append support."""

    def __init__(self, filename=None, expected_receivers=None):
        # Default to .logs directory in project root
        if filename is None:
            filename = (
                load_config().processing.logging.get_log_dir()
                / "timing_log_new_api.csv"
            )
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


def diagnose_processing_new_api(
    start_from: str | None = None,
    end_at: str | None = None,
) -> None:
    """Run diagnostic processing with NEW canvodpy.api.

    Uses Site + Pipeline pattern (new API) instead of legacy orchestrator.
    Compare results with timing_diagnostics_script.py to verify equivalence.

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
    >>> diagnose_processing_new_api()

    >>> # Start from a specific date
    >>> diagnose_processing_new_api(start_from="2024183")  # July 1, 2024

    >>> # Process a specific range
    >>> diagnose_processing_new_api(start_from="2025278", end_at="2025280")

    """
    print("=" * 80)
    print("TIMING DIAGNOSTIC WITH NEW API (Site + Pipeline)")
    print("=" * 80)
    print(f"Start time: {datetime.now()}")
    cfg = load_config()
    keep_vars = cfg.processing.params.keep_gnss_observables
    print(f"keep_gnss_observables: {keep_vars}")
    if start_from:
        print(f"Starting from: {start_from}")
    if end_at:
        print(f"Ending at: {end_at}")
    print()

    # Initialize site and pipeline using NEW API
    site = Site("ExampleSite")
    # reader_format is now per-receiver under sites: (no global reader= param)
    pipeline = site.pipeline(keep_vars=keep_vars, dry_run=False)

    # Get all configured receivers
    all_receivers = sorted(site.active_receivers.keys())
    timing_log = TimingLogger(expected_receivers=all_receivers)

    counter = 0
    garbage_collect = 0
    days_since_rechunk = 0

    # Main processing loop using NEW API
    # Note: Pipeline.process_range() doesn't return timing info,
    # so we need to time manually
    for date_key, datasets in pipeline.process_range(
        start=start_from or "2000001",  # Default to very early date
        end=end_at or "2099365",  # Default to far future date
    ):
        day_start_time = datetime.now()

        print(f"\n{'=' * 80}")
        print(f"Processing {date_key}")
        print(f"{'=' * 80}\n")

        try:
            # Track timing per receiver manually
            receiver_times = {}
            receiver_start = datetime.now()

            for receiver_name, ds in datasets.items():
                print(f"\n{'─' * 80}")
                print(f"{receiver_name.upper()} PROCESSING")
                print(f"{'─' * 80}")
                print(f"  Dataset shape: {dict(ds.sizes)}")

                # Manual timing (less accurate than orchestrator's internal timing)
                receiver_end = datetime.now()
                receiver_times[receiver_name] = (
                    receiver_end - receiver_start
                ).total_seconds()
                receiver_start = receiver_end

            day_end_time = datetime.now()
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

            # LOG TO CSV
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

        # Garbage collection every 5 days
        if garbage_collect % 5 == 0:
            print("\n💤 Pausing for 60s before garbage collection...")
            time.sleep(60)
            print("\n🗑️  Running garbage collection...")
            gc.collect()
            print("✓ Garbage collection done")

    print(f"\n{'=' * 80}")
    print(f"End time: {datetime.now()}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    # Process everything
    diagnose_processing_new_api()

    # Start from a specific date
    # diagnose_processing_new_api(start_from="2025224",
    #                             end_at="2025224")  # July 1, 2024

    # Process a specific range
    # diagnose_processing_new_api(start_from="2025278", end_at="2025280")

    # Process specific test range (Oct 26, 2025)
    # diagnose_processing_new_api(start_from="2025299", end_at="2025300")

"""Portable benchmark helpers used by the opt-in performance suite."""

from benchmarks.run_benchmarks import _peak_rss_bytes


def test_peak_memory_is_available_on_the_running_platform() -> None:
    assert _peak_rss_bytes() > 0

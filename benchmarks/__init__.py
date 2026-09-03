"""Personal-scale performance benchmarks for the Research Harness (ROADMAP Task 17.3).

Nothing here is part of the shipped package: the modules build a synthetic workspace with
:mod:`benchmarks.generate_corpus` and time the paths a researcher actually waits on with
:mod:`benchmarks.run_benchmarks`. They use only public APIs, and they never modify a
workspace they did not create.
"""

from __future__ import annotations

__all__ = ["generate_corpus", "run_benchmarks"]

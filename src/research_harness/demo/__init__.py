"""`research demo`: the whole evidence loop on a bundled synthetic paper, offline.

The demo exists so the first run of the cockpit has something to review without an API
key: it stages proposals with the scripted provider and verifies them the same way. The
scripted replies are derived from the parsed document itself, so every candidate quotes a
span that really exists and every verdict is one a careful reader would give.
"""

from research_harness.demo.loop import DEMO_PDF, DemoReport, run_demo

__all__ = ["DEMO_PDF", "DemoReport", "run_demo"]

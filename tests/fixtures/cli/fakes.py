"""Fake CLI executables for offline tests (CLI providers spec §20).

`FakeCli.install` writes a small Python program under `<root>/bin/<name>` and a
`script.json` it reads on every invocation, so a test can decide what `--version`, an
auth probe, or a run prints, how long it takes, and whether it hangs. Every invocation
appends `{"kind", "argv", "cwd", "env", "stdin"}` to `calls.jsonl`, which is how a test
proves the prompt travelled on stdin, the API key was stripped, and the cwd was a temp dir.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROGRAM = r"""#!/usr/bin/env python3
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = json.load(open(os.path.join(ROOT, "script.json"), encoding="utf-8"))

def record(kind, stdin=None):
    with open(os.path.join(ROOT, "calls.jsonl"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": kind, "argv": sys.argv[1:], "cwd": os.getcwd(),
                                 "env": dict(os.environ), "stdin": stdin}) + "\n")

def emit(lines):
    for line in lines:
        if isinstance(line, dict) and "sleep" in line:
            time.sleep(line["sleep"]); continue
        sys.stdout.write(line if isinstance(line, str) else json.dumps(line))
        sys.stdout.write("\n"); sys.stdout.flush()

args = sys.argv[1:]
if args == ["--version"]:
    record("version"); sys.stdout.write(SCRIPT.get("version_stdout", "fake 1.2.3") + "\n")
    sys.stderr.write(SCRIPT.get("version_stderr", "")); sys.exit(SCRIPT.get("version_exit", 0))
for probe in SCRIPT.get("probes", []):
    if args == probe["args"]:
        record("probe"); time.sleep(probe.get("sleep", 0))
        sys.stdout.write(probe.get("stdout", "")); sys.stderr.write(probe.get("stderr", ""))
        sys.exit(probe.get("exit", 0))
run = SCRIPT.get("run", {})
emit(run.get("before_input", []))
stdin = None
if run.get("read_stdin", True):
    stdin = sys.stdin.readline() if run.get("read_one_line") else sys.stdin.read()
record("run", stdin)
emit(run.get("lines", []))
if run.get("hang"):
    time.sleep(3600)
sys.stderr.write(run.get("stderr", ""))
sys.exit(run.get("exit", 0))
"""


@dataclass
class FakeCli:
    root: Path
    name: str

    @property
    def bin_dir(self) -> Path:
        return self.root / "bin"

    @property
    def executable(self) -> Path:
        return self.bin_dir / self.name

    @classmethod
    def install(
        cls,
        root: Path,
        name: str,
        *,
        version_stdout: str = "fake 1.2.3",
        version_exit: int = 0,
        version_stderr: str = "",
        probes: list[dict[str, Any]] | None = None,
        run: dict[str, Any] | None = None,
    ) -> FakeCli:
        fake = cls(root=root, name=name)
        fake.bin_dir.mkdir(parents=True, exist_ok=True)
        fake.executable.write_text(
            PROGRAM.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1), encoding="utf-8"
        )
        fake.executable.chmod(
            fake.executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        fake.write_script(
            {
                "version_stdout": version_stdout,
                "version_exit": version_exit,
                "version_stderr": version_stderr,
                "probes": probes or [],
                "run": run or {"lines": [], "exit": 0},
            }
        )
        return fake

    def write_script(self, script: Mapping[str, Any]) -> None:
        (self.root / "script.json").write_text(json.dumps(script), encoding="utf-8")

    def script(self) -> dict[str, Any]:
        return dict(json.loads((self.root / "script.json").read_text(encoding="utf-8")))

    def set_run(self, **fields: Any) -> None:
        script = self.script()
        script["run"] = {**script.get("run", {}), **fields}
        self.write_script(script)

    def env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        source = dict(os.environ if base is None else base)
        source["PATH"] = os.pathsep.join([str(self.bin_dir), source.get("PATH", "")])
        source.setdefault("HOME", str(self.root / "home"))
        return source

    def calls(self) -> list[dict[str, Any]]:
        path = self.root / "calls.jsonl"
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def runs(self) -> list[dict[str, Any]]:
        return [call for call in self.calls() if call["kind"] == "run"]

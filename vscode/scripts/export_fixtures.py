"""Export the VS Code unit-test fixtures from the Python side.

The extension re-implements two things the harness owns: LaTeX sentence segmentation (so a
hover can answer without a round trip) and the shape of a `manuscript.audit` report (so
diagnostics can be mapped). Both are only safe if the copy is checked against the original,
so this script builds a small workspace through the real capability layer and writes what it
produced into `vscode/src/test/fixtures/`:

* `manuscript.json` - the fixture LaTeX source plus every sentence `manuscript/latex.py`
  found in it, with the fingerprints `manuscript/anchors.py` would anchor on;
* `audit-report.json` - the `manuscript.audit` response for that workspace, verbatim.

Run it from the repository root whenever the manuscript modules change::

    uv run python vscode/scripts/export_fixtures.py

Then `cd vscode && pnpm test`: `latex.test.ts` asserts the TypeScript port reproduces the
fingerprints in `manuscript.json`, and `diagnostics.test.ts` maps `audit-report.json` onto
editor ranges. A drift on either side fails a test rather than a researcher's tooltip.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:  # running without an editable install
    sys.path.insert(0, str(REPO_ROOT / "src"))

from research_harness.capabilities.context import open_context  # noqa: E402
from research_harness.capabilities.dto import CreateClaimRequest, InitProjectRequest  # noqa: E402
from research_harness.capabilities.handlers import create_claim, init_project  # noqa: E402
from research_harness.domain.base import Provenance  # noqa: E402
from research_harness.domain.claim import (  # noqa: E402
    Claim,
    ClaimAssessment,
    ClaimScopeSpec,
    ClaimSemantics,
)
from research_harness.domain.enums import ClaimScope, ClaimStatus, ClaimType  # noqa: E402
from research_harness.domain.ids import ClaimId  # noqa: E402
from research_harness.domain.transitions import HUMAN_ACTOR  # noqa: E402
from research_harness.manuscript.attach import ManuscriptService  # noqa: E402
from research_harness.manuscript.latex import LatexProject  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "src" / "test" / "fixtures"

#: Four substantive sentences, each carrying one thing the audit has to notice, plus an
#: abbreviation, a decimal, a comment, and a display equation for the segmentation port.
MAIN_TEX = """% A fixture manuscript. No number here measures anything real.
\\documentclass{article}
\\usepackage{natbib}

\\title{Encrypted Traffic Under Sustained Load}
\\author{R. Hale}

\\begin{document}
\\maketitle

\\section{Introduction}
\\label{sec:intro}

Every encrypted traffic classifier fails under sustained load, and no prior work
reports the size of the gap \\citep{traffic2024}.

Byte-level tokenization reaches an F1 of 94.32 on CICIDS2017 under the held-out
protocol \\citep{traffic2024}.  % the decimal must not split this sentence

Prior surveys, e.g. the review of \\citet{missing2023}, report no comparable figure
for the same setting.

Our sweep shows that detection quality degrades as the offered load grows.

\\begin{equation}
  F_1 = 2 \\cdot \\frac{P \\cdot R}{P + R}
\\end{equation}

\\bibliographystyle{plainnat}
\\bibliography{references}

\\end{document}
"""

REFERENCES_BIB = """% `traffic2024` resolves; `missing2023` deliberately does not.

@inproceedings{traffic2024,
  author    = {Researcher, A. and Collaborator, B.},
  title     = {Deep Representations for Encrypted Network Traffic},
  booktitle = {Proceedings of the Example Conference on Networking}
}
"""

OVER_STRONG_LINE = 14
MEASURED_LINE = 17
CONTESTED_LINE = 20

SUPPORTED_CLAIM = ClaimId("C0001")
CONTESTED_CLAIM = ClaimId("C0002")


def make_claim(
    claim_id: ClaimId,
    statement: str,
    *,
    level: ClaimScope,
    status: ClaimStatus,
) -> Claim:
    """A claim whose assessment is exactly what `claim.create` would write."""
    return Claim(
        id=claim_id,
        statement=statement,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(subject=statement, predicate="asserts", object=statement),
        scope=ClaimScopeSpec(level=level, corpus="encrypted traffic classifiers"),
        assessment=ClaimAssessment(
            requested_strength=level,
            allowed_strength=level,
            status=status,
            maximum_defensible_wording="most systems in the reviewed corpus",
        ),
        provenance=Provenance.human(HUMAN_ACTOR),
    )


def build_workspace(root: Path) -> ManuscriptService:
    """A workspace with two Claims, a manuscript, and three anchors, built through capabilities."""
    result = init_project(InitProjectRequest(root=root, name="vscode-fixture"))
    ctx = open_context(result.root, HUMAN_ACTOR)
    create_claim(
        ctx,
        CreateClaimRequest(
            claim=make_claim(
                SUPPORTED_CLAIM,
                "Byte-level tokenization reports an F1 of 94.32 in the reviewed corpus",
                level=ClaimScope.CORPUS_PATTERN,
                status=ClaimStatus.SUPPORTED,
            )
        ),
    )
    create_claim(
        ctx,
        CreateClaimRequest(
            claim=make_claim(
                CONTESTED_CLAIM,
                "Prior surveys report no comparable figure for this setting",
                level=ClaimScope.INDIVIDUAL,
                status=ClaimStatus.CONTESTED,
            )
        ),
    )

    manuscript_dir = ctx.repo.layout.manuscript_dir
    manuscript_dir.mkdir(parents=True, exist_ok=True)
    (manuscript_dir / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (manuscript_dir / "references.bib").write_text(REFERENCES_BIB, encoding="utf-8")

    service = ManuscriptService(ctx)
    service.attach(("main.tex", OVER_STRONG_LINE), SUPPORTED_CLAIM)
    service.attach(("main.tex", MEASURED_LINE), SUPPORTED_CLAIM)
    service.attach(("main.tex", CONTESTED_LINE), CONTESTED_CLAIM)
    return service


def manuscript_fixture(service: ManuscriptService) -> dict[str, Any]:
    """The LaTeX source and every sentence the harness finds in it."""
    project = LatexProject.load(service.main_path)
    return {
        "note": (
            "Written by vscode/scripts/export_fixtures.py from "
            "research_harness.manuscript.latex. Do not edit by hand."
        ),
        "main_tex": "main.tex",
        "source": MAIN_TEX,
        "bibliography": REFERENCES_BIB,
        "sentences": [
            {
                "file": sentence.file,
                "line_start": sentence.line_start,
                "line_end": sentence.line_end,
                "char_start": sentence.char_start,
                "char_end": sentence.char_end,
                "normalized_text": sentence.normalized_text,
                "fingerprint": sentence.fingerprint,
                "citation_keys": list(sentence.citation_keys),
            }
            for sentence in project.sentences
        ],
    }


def main() -> int:
    """Write both fixtures and say what went into them."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vscode-fixture-") as scratch:
        service = build_workspace(Path(scratch) / "project")
        manuscript = manuscript_fixture(service)
        report = service.audit(parsed=False)

    _write(FIXTURES / "manuscript.json", manuscript)
    _write(FIXTURES / "audit-report.json", report.model_dump(mode="json"))
    kinds = sorted({finding.kind.value for finding in report.findings})
    print(f"{len(manuscript['sentences'])} sentences -> {FIXTURES / 'manuscript.json'}")
    print(f"{len(report.findings)} findings ({', '.join(kinds)}) -> audit-report.json")
    return 0


def _write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

"""The ROADMAP §5 end-to-end loop, built once and reused by every Product §42 invariant.

    init -> ingest -> parse -> extract candidate -> verify -> review accept
         -> create claim -> audit claim -> attach manuscript sentence -> audit citation

Everything below goes through the supported surfaces: `capabilities/` handlers, the
services that drive them (`EvidenceReviewService`, `ClaimService`, `ManuscriptService`),
and a scripted provider. Nothing here writes a canonical file directly, so a workstation
built by this module is a workspace a researcher could have produced by hand.

The manuscript is three sentences and each one exists for a Product §42.J case:

===== ===================================================== ==========================
line  sentence                                              expected finding
===== ===================================================== ==========================
15    "TrafficLM reaches an F1 of 94.32 ... \\citep{ok}"     none: the key supports it
18    "The corrected split ... \\citep{unsupported}"          citation mismatch
21    "Detection quality degrades ... \\citep{ghost}"         missing bibliography key
===== ===================================================== ==========================
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import (
    IngestLocalPdfRequest,
    InitProjectRequest,
    ParseWorkRequest,
    RegisterWorkRequest,
)
from research_harness.capabilities.handlers import init_project, register_work
from research_harness.claims.service import ClaimService
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
    Coverage,
)
from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import (
    ArtifactKind,
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimType,
    ProvenanceSource,
    ReviewAction,
    VersionKind,
)
from research_harness.domain.ids import ArtifactId, ClaimId, EvidenceId, WorkId
from research_harness.domain.work import CandidateMetadata, IdentifierField, WorkCandidate
from research_harness.evidence.extraction import ModelClient
from research_harness.evidence.interrogation import DEFAULT_SCHEMA
from research_harness.evidence.service import EvidenceReviewService
from research_harness.evidence.staging import StagingStore
from research_harness.ingest.service import IngestService
from research_harness.manuscript.attach import ManuscriptService
from research_harness.manuscript.audit import ManuscriptAuditReport
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.interrogate import run_interrogation
from research_harness.workflows.verify import run_verification
from research_harness.workspace.runs import RunStore
from tests.integration.evidence.conftest import (
    DATASET_SENTENCE,
    dataset_candidate,
    extraction_dict,
    metric_candidate,
    parse_fixture,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_research_paper.pdf"

HUMAN = "human:alice"
MODEL_ACTOR = "vendor-a/model-x"

WORK = WorkId("W0001")
OTHER_WORK = WorkId("W0002")
ARTIFACT = ArtifactId("A0001-1")
METRIC_EVIDENCE = EvidenceId("E0001")
DATASET_EVIDENCE = EvidenceId("E0002")
SUPPORTED_CLAIM = ClaimId("C0001")
UNSUPPORTED_CLAIM = ClaimId("C0002")

#: Interrogation fields the loop asks, in schema order. `metric_result` is first in the
#: accepted order because the numeric one is what §42.D and §42.J both lean on.
FIELDS: tuple[str, ...] = ("dataset", "metric_result")

MEASURED_VALUE = "94.32"
MEASURED_PAGE = 4

#: Verdicts the scripted verifier returns, keyed by interrogation field.
VERDICTS: dict[str, str] = {"dataset": "supported", "metric_result": "supported"}
QUOTES: dict[str, str] = {"dataset": DATASET_SENTENCE, "metric_result": MEASURED_VALUE}

SUPPORTING_KEY = "traffic2024"
UNSUPPORTED_KEY = "split2020"
GHOST_KEY = "phantom2099"

#: 1-based line each fixture sentence *starts* on; an anchor records the start, and the
#: audit names it as `main.tex:<line>`.
SUPPORTED_LINE = 14
MISMATCH_LINE = 17
GHOST_LINE = 20

MAIN_TEX = f"""% Product 42 fixture manuscript. Every number here is the synthetic paper's.
\\documentclass{{article}}
\\usepackage{{natbib}}

\\title{{Encrypted Traffic Classification Under Sustained Load}}
\\author{{A. Researcher}}

\\begin{{document}}
\\maketitle

\\section{{Results}}
\\label{{sec:results}}

TrafficLM reaches an F1 of {MEASURED_VALUE} on CICIDS2017 under the held-out protocol
\\citep{{{SUPPORTING_KEY}}}.

The corrected split we adopt for evaluation follows the protocol of the cited release
\\citep{{{UNSUPPORTED_KEY}}}.

Detection quality degrades as the offered load grows on the reviewed corpus
\\citep{{{GHOST_KEY}}}.

\\bibliographystyle{{plainnat}}
\\bibliography{{references}}

\\end{{document}}
"""

OTHER_TITLE = "A Corrected Split for Structured Traffic Corpora"

REFERENCES_BIB = f"""% The first entry matches W0001 by its normalized title, and W0001 carries
% the evidence C0001 leans on. The second matches W0002, which carries no evidence at all,
% so it resolves and still supports nothing C0002 records - the Product 42.J case. The key
% cited on the third sentence is deliberately absent from this file and never resolves.

@inproceedings{{{SUPPORTING_KEY},
  author    = {{Researcher, A. and Collaborator, B. and Advisor, C.}},
  title     = {{Deep Representations for Encrypted Network Traffic}},
  booktitle = {{Proceedings of the Example Conference on Networking}}
}}

@article{{{UNSUPPORTED_KEY},
  author    = {{Ostrom, K. and Lindqvist, M.}},
  title     = {{{OTHER_TITLE}}},
  journal   = {{Journal of Example Studies}},
  year      = {{2020}}
}}
"""


# --------------------------------------------------------------------------- the result


@dataclass(frozen=True)
class Workstation:
    """One workspace that has been through the whole loop, and the ids it produced."""

    root: Path
    work: WorkId
    artifact: ArtifactId
    evidence: tuple[EvidenceId, ...]
    claims: tuple[ClaimId, ...]
    candidates: dict[str, str]
    """Interrogation field -> the staging id its candidate was accepted from."""

    def context(self, actor: str = HUMAN) -> CapabilityContext:
        """A capability context over this workspace, bound to ``actor``."""
        return open_context(self.root, actor)

    @property
    def manuscript_dir(self) -> Path:
        return self.root / "manuscript"


# ------------------------------------------------------------------- scripted providers


def schema_order(fields: Sequence[str]) -> tuple[str, ...]:
    """``fields`` in the order the interrogation workflow will ask them.

    One `extract.<field>` stage runs per selected field in schema order, so a scripted
    queue only lines up with the stages when it is built in that order.
    """
    return tuple(item.name for item in DEFAULT_SCHEMA.select(list(fields)))


def extractor_provider(
    document: ParsedDocument, fields: Sequence[str] = FIELDS
) -> ScriptedProvider:
    """One extraction reply per field, quoting spans the real parse actually produced."""
    by_field = {
        "dataset": dataset_candidate(document),
        "metric_result": metric_candidate(document),
    }
    return ScriptedProvider([extraction_dict([by_field[name]]) for name in schema_order(fields)])


def verification_reply(field: str) -> dict[str, Any]:
    """A schema-valid `VerificationOutput` for one field, quoting the real source span."""
    return {
        "verdict": VERDICTS[field],
        "rationale": "read the anchored span and the blocks around it",
        "quoted_support": QUOTES[field],
        "discrepancies": [],
    }


def verifier_provider(fields: Sequence[str]) -> ScriptedProvider:
    """One verification reply per staged candidate, in the order verification asks."""
    return ScriptedProvider([verification_reply(name) for name in fields])


# ------------------------------------------------------------------------ the loop steps


def init_and_ingest(root: Path, *, name: str = "gate-p17") -> CapabilityContext:
    """`init` -> `ingest` -> `parse` through the capability layer."""
    created = init_project(InitProjectRequest(root=root, name=name))
    ctx = open_context(created.root, HUMAN)
    service = IngestService(ctx)
    service.ingest(IngestLocalPdfRequest(path=FIXTURE))
    service.parse(ParseWorkRequest(work=WORK))
    return ctx


def register_cited_work(ctx: CapabilityContext) -> WorkId:
    """A second corpus Work that the manuscript cites and no Claim leans on.

    It exists so Product §42.J has its real case to make: a citation key that resolves to
    a work in *this* corpus and still supports nothing the attached Claim records.
    """
    path = ctx.root / ".research" / "cache" / "corrected-split.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n% the corrected-split release, cited but never read\n")
    external = ProvenanceSource.EXTERNAL_METADATA
    register_work(
        ctx,
        RegisterWorkRequest(
            candidate=WorkCandidate(
                provenance=Provenance.system(actor="ingest"),
                metadata=CandidateMetadata(
                    title=IdentifierField(value=OTHER_TITLE, source=external, confidence=0.9),
                    authors=(IdentifierField(value="K. Ostrom", source=external),),
                    year=IdentifierField(value="2020", source=external),
                ),
                candidate_file_hash=(f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"),
                original_filename=path.name,
            ),
            artifact_path=path,
            version_kind=VersionKind.PREPRINT,
            mime_type="application/pdf",
            artifact_kind=ArtifactKind.PDF,
        ),
    )
    return OTHER_WORK


def interrogate_and_verify(
    ctx: CapabilityContext,
    *,
    extractor: ModelClient | None = None,
    verifier: ModelClient | None = None,
    fields: Sequence[str] = FIELDS,
) -> dict[str, str]:
    """Stage candidates and verify them; returns ``field -> candidate id``.

    Neither stage touches canonical state: extraction and verification both write only
    under `.research/staging` (ADR-003).
    """
    staging = StagingStore(ctx.repo.layout.research_dir)
    engine = WorkflowEngine(RunStore(ctx.repo.layout.research_dir))
    document = parse_fixture()
    run_interrogation(
        engine,
        staging,
        ctx.repo,
        WORK,
        extractor if extractor is not None else extractor_provider(document, fields),
        fields=list(schema_order(fields)),
    )
    ordered = _staged_fields(staging, fields)
    run_verification(
        engine,
        staging,
        ctx.repo,
        WORK,
        verifier if verifier is not None else verifier_provider(ordered),
    )
    return {
        candidate.field: candidate.candidate_id
        for candidate in staging.list(work=WORK)
        if candidate.field in set(fields)
    }


def _staged_fields(staging: StagingStore, fields: Sequence[str]) -> list[str]:
    """Fields of the candidates verification will visit, in the order it visits them."""
    from research_harness.evidence.staging import CandidateStatus

    return [
        candidate.field
        for candidate in staging.list(work=WORK, status=CandidateStatus.PROPOSED)
        if candidate.field in set(fields)
    ]


def accept_candidates(ctx: CapabilityContext, candidates: dict[str, str]) -> tuple[EvidenceId, ...]:
    """Accept every staged candidate as the researcher; returns the ids allocated."""
    service = EvidenceReviewService(ctx, StagingStore(ctx.repo.layout.research_dir))
    accepted: list[EvidenceId] = []
    for field in FIELDS:
        candidate_id = candidates.get(field)
        if candidate_id is None:
            continue
        result = service.accept(candidate_id, action=ReviewAction.ACCEPT)
        accepted.append(EvidenceId(result.objects[0]))
    return tuple(accepted)


def create_and_audit_claims(
    ctx: CapabilityContext, evidence: Sequence[EvidenceId]
) -> tuple[ClaimId, ...]:
    """One well-supported claim over the accepted evidence, and one with no support."""
    service = ClaimService(ctx)
    supported, _ = service.create(
        f"TrafficLM reaches an F1 of {MEASURED_VALUE} on CICIDS2017 in the reviewed corpus",
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(
            subject="TrafficLM", predicate="reaches", object="an F1 of 94.32 on CICIDS2017"
        ),
        scope=ClaimScopeSpec(level=ClaimScope.INDIVIDUAL, corpus="encrypted traffic classifiers"),
        requested_strength=ClaimScope.INDIVIDUAL,
        relations=tuple(
            ClaimEvidenceRelation(evidence=item, relation=ClaimEvidenceRelationType.SUPPORTS)
            for item in evidence
        ),
        coverage=Coverage(relevant_works=1, examined_works=1),
    )
    unsupported, _ = service.create(
        "The corrected split changes the reported operating point",
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(
            subject="corrected_split", predicate="changes", object="the operating point"
        ),
        scope=ClaimScopeSpec(level=ClaimScope.INDIVIDUAL, corpus="encrypted traffic classifiers"),
        requested_strength=ClaimScope.INDIVIDUAL,
    )
    service.audit(supported.id)
    service.audit(unsupported.id)
    return (supported.id, unsupported.id)


def write_manuscript(ctx: CapabilityContext) -> None:
    """Put the fixture LaTeX project into the workspace's own `manuscript/` directory."""
    manuscript = ctx.repo.layout.manuscript_dir
    manuscript.mkdir(parents=True, exist_ok=True)
    (manuscript / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (manuscript / "references.bib").write_text(REFERENCES_BIB, encoding="utf-8")


def attach_sentences(ctx: CapabilityContext, claims: Sequence[ClaimId]) -> None:
    """Bind each fixture sentence to the Claim it is meant to rest on."""
    service = ManuscriptService(ctx)
    supported, unsupported = claims[0], claims[1]
    service.attach(("main.tex", SUPPORTED_LINE), supported)
    service.attach(("main.tex", MISMATCH_LINE), unsupported)
    service.attach(("main.tex", GHOST_LINE), supported)


def audit_manuscript(ctx: CapabilityContext) -> ManuscriptAuditReport:
    """`manuscript audit` over the workspace's own manuscript, source parse included."""
    return ManuscriptService(ctx).audit()


def build_workstation(root: Path) -> Workstation:
    """Run the whole ROADMAP §5 loop against ``root`` and report what it produced."""
    ctx = init_and_ingest(root)
    register_cited_work(ctx)
    candidates = interrogate_and_verify(ctx)
    evidence = accept_candidates(ctx, candidates)
    claims = create_and_audit_claims(ctx, evidence)
    write_manuscript(ctx)
    attach_sentences(ctx, claims)
    audit_manuscript(ctx)
    return Workstation(
        root=ctx.root,
        work=WORK,
        artifact=ARTIFACT,
        evidence=evidence,
        claims=claims,
        candidates=candidates,
    )


# ------------------------------------------------------------------------------ digests


#: Fields two runs of the same loop cannot share, and that carry no scientific content:
#: clocks, the actor that happened to act, and which backend answered.
VOLATILE_KEYS: frozenset[str] = frozenset(
    {
        "accepted_by",
        "actor",
        "audited_at",
        "created_at",
        "extractor",
        "note",
        "occurred_at",
        "reviewed_at",
        "updated_at",
        "verifier",
    }
)


def scientific_form(value: Any) -> Any:
    """``value`` with every provenance, actor, and clock field removed, recursively.

    What survives is what a reader would argue with: the anchor, the content, the origin,
    the verdict, the scope, and the relations. Everything dropped is *who* and *when*.
    """
    if isinstance(value, dict):
        return {
            key: scientific_form(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_KEYS and key != "provenance"
        }
    if isinstance(value, list):
        return [scientific_form(item) for item in value]
    return value


def digest(value: Any) -> str:
    """A stable digest of the scientific content of ``value``."""
    material = json.dumps(scientific_form(value), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def jsonl(path: Path) -> list[dict[str, Any]]:
    """Every record of a canonical JSON Lines file, or an empty list when there is none."""
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def canonical_files(root: Path) -> Iterator[Path]:
    """Every file that carries scientific authority: everything outside `.research/`."""
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".research" not in path.relative_to(root).parts:
            yield path


def canonical_bytes_digest(root: Path) -> str:
    """Digest of every canonical file's bytes, so a rewrite anywhere shows up."""
    material = hashlib.sha256()
    for path in canonical_files(root):
        material.update(path.relative_to(root).as_posix().encode("utf-8"))
        material.update(b"\0")
        material.update(path.read_bytes())
        material.update(b"\0")
    return material.hexdigest()

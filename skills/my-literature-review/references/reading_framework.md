# Evidence-linked reading framework

Use this reference when extracting comparable information from included Works.

## Source discipline

Record the Artifact and anchor for every full-text observation. Keep these origins distinct:

- `source_observed`: directly visible in the Artifact;
- `author_stated`: an author claim or interpretation;
- `researcher_inferred`: a reviewable interpretation;
- `model_proposed`: a candidate awaiting verification and human review.

Abstract-only reading must stay labeled and cannot populate details that require methods, results, appendices, or supplementary material.

## Information matrix

Collect only fields relevant to the accepted question, commonly:

- problem, scope, setting, and population/dataset;
- method, representation, inputs, and assumptions;
- training/evaluation design, partitions, baselines, and metrics;
- reported results with conditions and uncertainty;
- ablations, robustness, compute, latency, and deployment constraints;
- author-stated limitations and anchored counter-evidence;
- artifact/code/data availability.

Each cell stores value, provenance, source anchor, evidence origin, and status (`observed`, `not_reported`, `not_examined`, `unavailable`, `conflicting`, or `not_applicable`).

## Classification

Use multi-label taxonomy when a paper spans methods, problems, datasets, or roles. A primary label is optional and must be justified by the accepted taxonomy. Do not force one group merely to simplify a table.

## Synthesis

Separate:

- what the source reports;
- what the reviewer infers;
- how sources agree or conflict;
- what remains unknown.

Missing information remains missing. It does not become a limitation, gap, or novelty claim without the required evidence and coverage audit.

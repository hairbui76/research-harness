/**
 * What the extension puts on the wire, and what it does with the answer.
 *
 * The capability names and request bodies asserted here are the same ones
 * `tests/contract/protocol/test_vscode_contract.py` calls against a real daemon, so the two
 * tests together say: the extension sends this, and the harness accepts exactly this.
 */

import { describe, expect, it } from "vitest";

import { HarnessClient } from "../client/HarnessClient";
import { HarnessError } from "../client/errors";
import {
  addNote,
  attachClaim,
  auditClaim,
  auditManuscript,
  createClaim,
  findSupport,
  listClaims,
  manuscriptAnchors,
  resolveSource,
  revalidateAnchors,
  traceSentence,
} from "../client/requests";
import { CAPABILITIES, type NewClaim } from "../client/types";

interface RecordedCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

function fakeDaemon(reply: (call: RecordedCall) => { status?: number; payload: unknown }) {
  const calls: RecordedCall[] = [];
  const fetchImpl = (async (
    input: Parameters<typeof fetch>[0],
    init?: Parameters<typeof fetch>[1],
  ) => {
    const call: RecordedCall = {
      url: String(input),
      method: init?.method ?? "GET",
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(call);
    const { status = 200, payload } = reply(call);
    return new Response(JSON.stringify(payload), {
      status,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  return { calls, fetchImpl };
}

function ok(capability: string, result: unknown) {
  return { payload: { capability, ok: true, result } };
}

function client(
  reply: (call: RecordedCall) => { status?: number; payload: unknown },
  token = "t0ken",
) {
  const daemon = fakeDaemon(reply);
  return {
    calls: daemon.calls,
    client: new HarnessClient({
      baseUrl: "http://127.0.0.1:8765/",
      readToken: async () => token,
      fetchImpl: daemon.fetchImpl,
    }),
  };
}

describe("request shaping, per capability", () => {
  it("manuscript.audit names the project and the main file", async () => {
    const harness = client((call) => ok(CAPABILITIES.manuscriptAudit, { findings: [], ...call }));
    await auditManuscript(harness.client, { project_root: "/w/manuscript", main_tex: "paper.tex" });
    expect(harness.calls[0]?.url).toBe("http://127.0.0.1:8765/capabilities/manuscript.audit");
    expect(harness.calls[0]?.method).toBe("POST");
    expect(harness.calls[0]?.body).toEqual({
      project_root: "/w/manuscript",
      main_tex: "paper.tex",
    });
  });

  it("manuscript.audit defaults main_tex, because the DTO does", async () => {
    const harness = client(() => ok(CAPABILITIES.manuscriptAudit, { findings: [] }));
    await auditManuscript(harness.client);
    expect(harness.calls[0]?.body).toEqual({ main_tex: "main.tex" });
  });

  it("manuscript.audit carries the selection's file and line range", async () => {
    const harness = client(() => ok(CAPABILITIES.manuscriptAudit, { findings: [] }));
    await auditManuscript(harness.client, {
      main_tex: "main.tex",
      file: "main.tex",
      line_start: 14,
      line_end: 20,
    });
    expect(harness.calls[0]?.body).toEqual({
      main_tex: "main.tex",
      file: "main.tex",
      line_start: 14,
      line_end: 20,
    });
  });

  it("manuscript.anchors asks for the project and nothing else", async () => {
    const harness = client(() =>
      ok(CAPABILITIES.manuscriptAnchors, { count: 0, anchors: [], verdicts: [] }),
    );
    await manuscriptAnchors(harness.client, { project_root: "/w/manuscript" });
    expect(harness.calls[0]?.url).toContain("/capabilities/manuscript.anchors");
    expect(harness.calls[0]?.body).toEqual({
      main_tex: "main.tex",
      project_root: "/w/manuscript",
    });
  });

  it("manuscript.revalidate records by default, and says so on the wire", async () => {
    const harness = client(() =>
      ok(CAPABILITIES.manuscriptRevalidate, { dry_run: false, checked: 0, applied: [] }),
    );
    await revalidateAnchors(harness.client, { main_tex: "main.tex" });
    expect(harness.calls[0]?.url).toContain("/capabilities/manuscript.revalidate");
    expect(harness.calls[0]?.body).toEqual({ main_tex: "main.tex", dry_run: false });
  });

  it("manuscript.trace names the sentence by file and line", async () => {
    const harness = client(() =>
      ok(CAPABILITIES.manuscriptTrace, { file: "main.tex", line: 17, sentence: "x" }),
    );
    await traceSentence(harness.client, { file: "main.tex", line: 17 });
    expect(harness.calls[0]?.body).toEqual({ main_tex: "main.tex", file: "main.tex", line: 17 });
  });

  it("claim.list sends the filters it was given and no others", async () => {
    const harness = client(() => ok(CAPABILITIES.claimList, { count: 0, claims: [] }));
    await listClaims(harness.client);
    expect(harness.calls[0]?.url).toContain("/capabilities/claim.list");
    expect(harness.calls[0]?.body).toEqual({});

    const filtered = client(() => ok(CAPABILITIES.claimList, { count: 0, claims: [] }));
    await listClaims(filtered.client, { status: "supported" });
    expect(filtered.calls[0]?.body).toEqual({ status: "supported" });
  });

  it("manuscript.attach_claim sends a whole anchor with its fingerprint", async () => {
    const harness = client(() => ok(CAPABILITIES.manuscriptAttachClaim, { objects: [] }));
    await attachClaim(harness.client, {
      provenance: { source: "human", actor: "human", workflow: "vscode" },
      file: "main.tex",
      line_start: 14,
      line_end: 15,
      char_start: 244,
      char_end: 373,
      sentence: "Every encrypted traffic classifier fails under sustained load.",
      sentence_fingerprint: "sha256:abc",
      claim: "C0001",
      citation_keys: ["traffic2024"],
      status: "valid",
      stale: "fresh",
    });
    const body = harness.calls[0]?.body as { anchor: Record<string, unknown> };
    expect(harness.calls[0]?.url).toContain("/capabilities/manuscript.attach_claim");
    expect(Object.keys(body)).toEqual(["anchor"]);
    expect(body.anchor["sentence_fingerprint"]).toBe("sha256:abc");
    expect(body.anchor["claim"]).toBe("C0001");
    expect(body.anchor["provenance"]).toEqual({
      source: "human",
      actor: "human",
      workflow: "vscode",
    });
  });

  it("claim.find_support sends claim_id", async () => {
    const harness = client(() => ok(CAPABILITIES.claimFindSupport, { claim: "C0001" }));
    await findSupport(harness.client, "C0001");
    expect(harness.calls[0]?.body).toEqual({ claim_id: "C0001" });
  });

  it("claim.create sends no id, and lets the daemon name the Claim", async () => {
    const harness = client(() => ok(CAPABILITIES.claimCreate, { objects: ["C0003"] }));
    const claim: NewClaim = {
      statement: "Load degrades detection quality",
      type: "descriptive",
      semantics: { subject: "load", predicate: "degrades", object: "detection quality" },
      scope: { level: "corpus_pattern" },
      assessment: {
        requested_strength: "corpus_pattern",
        allowed_strength: "individual",
        status: "unverified",
      },
      provenance: { source: "human", actor: "human", workflow: "vscode" },
    };
    const created = await createClaim(harness.client, claim);
    expect(harness.calls[0]?.body).toEqual({ claim });
    expect(claim).not.toHaveProperty("id");
    expect(created.objects[0]).toBe("C0003");
  });

  it("claim.audit sends the status and the strength the evidence allows", async () => {
    const harness = client(() => ok(CAPABILITIES.claimAudit, { objects: ["C0001"] }));
    await auditClaim(harness.client, {
      claim_id: "C0001",
      status: "qualified",
      allowed_strength: "corpus_pattern",
      maximum_defensible_wording: "most systems in the reviewed corpus",
    });
    expect(harness.calls[0]?.body).toEqual({
      claim_id: "C0001",
      status: "qualified",
      allowed_strength: "corpus_pattern",
      maximum_defensible_wording: "most systems in the reviewed corpus",
    });
  });

  it("note.add sends the text and names the capture host separately", async () => {
    const harness = client(() => ok(CAPABILITIES.noteAdd, { objects: [] }));
    await addNote(harness.client, { text: "check the split", source: "vscode main.tex:17" });
    expect(harness.calls[0]?.body).toEqual({
      text: "check the split",
      source: "vscode main.tex:17",
    });
  });

  it("retrieval.resolve_source sends the reference", async () => {
    const harness = client(() => ok(CAPABILITIES.resolveSource, { ref: "E0001" }));
    await resolveSource(harness.client, "E0001");
    expect(harness.calls[0]?.body).toEqual({ ref: "E0001" });
  });
});

describe("authority", () => {
  it("presents the local token as a bearer, which is what makes the caller the researcher", async () => {
    const harness = client(() => ok(CAPABILITIES.manuscriptAudit, { findings: [] }));
    await auditManuscript(harness.client);
    expect(harness.calls[0]?.headers["Authorization"]).toBe("Bearer t0ken");
  });

  it("sends no Authorization header when the workspace has no token", async () => {
    const daemon = fakeDaemon(() => ok(CAPABILITIES.manuscriptAudit, { findings: [] }));
    const bare = new HarnessClient({
      baseUrl: "http://127.0.0.1:8765",
      readToken: async () => undefined,
      fetchImpl: daemon.fetchImpl,
    });
    await auditManuscript(bare);
    expect(daemon.calls[0]?.headers["Authorization"]).toBeUndefined();
  });
});

describe("error mapping", () => {
  it("turns permission_denied into an instruction about the token", async () => {
    const harness = client(() => ({
      status: 403,
      payload: {
        capability: CAPABILITIES.manuscriptAttachClaim,
        ok: false,
        error: {
          code: "permission_denied",
          message: "manuscript.attach_claim: agent_host may not mutate",
          capability: CAPABILITIES.manuscriptAttachClaim,
        },
      },
    }));
    const failure = await harness.client
      .invoke(CAPABILITIES.manuscriptAttachClaim, {})
      .catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(HarnessError);
    const error = failure as HarnessError;
    expect(error.isPermissionDenied).toBe(true);
    expect(error.message).toContain("daemon-token");
    expect(error.message).toContain("research token");
  });

  it("names the rebuild for a projection error", async () => {
    const harness = client(() => ({
      status: 409,
      payload: {
        capability: CAPABILITIES.resolveSource,
        ok: false,
        error: { code: "projection_error", message: "no projection", capability: null },
      },
    }));
    const error = (await harness.client
      .invoke(CAPABILITIES.resolveSource, { ref: "E0001" })
      .catch((caught: unknown) => caught)) as HarnessError;
    expect(error.code).toBe("projection_error");
    expect(error.message).toContain("research rebuild");
  });

  it("says the daemon is not running when the socket refuses", async () => {
    const failing = new HarnessClient({
      baseUrl: "http://127.0.0.1:8765",
      readToken: async () => undefined,
      fetchImpl: (async () => {
        throw new Error("ECONNREFUSED");
      }) as typeof fetch,
    });
    const error = (await failing.health().catch((caught: unknown) => caught)) as HarnessError;
    expect(error.code).toBe("daemon_unreachable");
    expect(error.message).toContain("research serve");
  });

  it("reports a missing object as object_not_found rather than a crash", async () => {
    const harness = client(() => ({ status: 404, payload: { detail: "no claim C0404" } }));
    expect(await harness.client.objectExists("C0404")).toBe(false);
  });
});

describe("catalog", () => {
  const catalog = {
    capabilities: [
      {
        name: "manuscript.audit",
        summary: "",
        permission: "read",
        scientific_semantics: "",
        request_schema: {},
        response_schema: {},
        human_only: false,
        long_running: false,
      },
    ],
    planned: [{ name: "corpus.search", reason: "needs configured providers" }],
  };

  it("is fetched once and reused", async () => {
    const harness = client(() => ({ payload: catalog }));
    await harness.client.capabilities();
    await harness.client.capabilities();
    expect(harness.calls).toHaveLength(1);
  });

  it("distinguishes an implemented capability from a planned one", async () => {
    const harness = client(() => ({ payload: catalog }));
    expect(await harness.client.has("manuscript.audit")).toBe(true);
    expect(await harness.client.has("corpus.search")).toBe(false);
    expect(await harness.client.plannedReason("corpus.search")).toBe(
      "needs configured providers",
    );
  });
});

describe("listing claims", () => {
  const claims = [
    {
      id: "C0001",
      statement: "Byte-level tokenization improves recall",
      type: "descriptive",
      status: "supported",
      requested_strength: "corpus_pattern",
      allowed_strength: "corpus_pattern",
      stale: "fresh",
    },
  ];

  it("reads them through the capability, not through a Web-cockpit route", async () => {
    const harness = client(() => ok(CAPABILITIES.claimList, { count: 1, claims }));
    expect(await listClaims(harness.client)).toEqual(claims);
    expect(harness.calls[0]?.url).toBe("http://127.0.0.1:8765/capabilities/claim.list");
    expect(harness.calls.map((call) => call.url)).not.toContain("http://127.0.0.1:8765/index");
  });

  it("raises a real refusal rather than reading it as an empty workspace", async () => {
    const harness = client(() => ({
      status: 503,
      payload: { detail: "no workspace here" },
    }));
    await expect(listClaims(harness.client)).rejects.toBeInstanceOf(HarnessError);
  });
});

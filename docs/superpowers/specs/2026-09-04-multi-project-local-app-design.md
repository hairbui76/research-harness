# Multi-project Local Web App — Design Specification

**Status:** Design approved in conversation; awaiting review of this written specification.

**Scope:** Product and architecture design only. This document does not authorize implementation.

## 1. Goal

Research Harness should start once, independently of the current working directory, and let
the researcher create, open, remember, and switch among local research projects from the Web
interface. The intended entry point is:

```console
research app
```

The experience should resemble a local project launcher: the researcher explicitly grants
access to a folder, and the application thereafter identifies it by an opaque project ID.
Opening a second project must not require stopping the first project's workflows or launching
another manually selected port.

The existing one-workspace commands remain valid. In particular,
`research serve -w <folder>`, the CLI workspace option, MCP, and editor integrations continue
to use the current single-workspace behavior.

## 2. Decisions

The approved design makes these choices:

1. One local server manages multiple projects concurrently.
2. The first release remains a browser application served on loopback, not a packaged desktop
   shell.
3. Both creating a new workspace and opening an existing workspace are supported.
4. Windows and Linux receive native folder-picker adapters, with a typed-path fallback on
   Linux when no supported picker is installed.
5. A global project registry remembers explicitly granted folders across restarts.
6. Project-scoped requests carry an opaque `project_id`; ordinary Web requests never select a
   workspace by supplying a filesystem path.
7. AI callers may read and stage through existing capabilities, but acceptance and canonical
   mutation remain subject to the existing authority and review rules.

## 3. Non-goals

- Turning Research Harness into a general-purpose coding agent with unrestricted shell or
  filesystem mutation.
- Letting a model silently accept Evidence, Claims, Decisions, or other canonical state.
- Scanning the computer for projects that the researcher has not explicitly opened.
- Copying project contents into an application-owned data directory.
- Syncing the global project registry between computers.
- Serving the application on a non-loopback address.
- Removing or changing the contract of `research serve -w <folder>`.
- Packaging a Tauri, Electron, or native desktop application in this release.

## 4. User experience

### 4.1 Starting the application

`research app` starts a loopback-only server on the app port and opens an authenticated local
URL in the default browser. The command is independent of the current directory and does not
infer a workspace from it.

If another compatible app instance is already listening, the command opens that instance
instead of starting a competing process. A genuinely unrelated process occupying the port
produces a clear error and supports an explicit `--port` override.

### 4.2 Project Home

Project Home shows every registered project ordered by most recently opened. Each row includes:

- display name;
- folder path;
- last-opened time;
- availability and compatibility status;
- active-workflow indicator when applicable.

The primary actions are **New Project** and **Open Folder**. With no registered projects,
Project Home is the initial screen. With previous projects, the app opens the most recently
used available project; Project Home remains reachable from the project rail.

### 4.3 New Project

The researcher enters a project name and chooses a parent folder. The application creates a
new child folder using a filesystem-safe form of the name, initializes it through the same
application service used by `research init`, registers it, and opens it.

Creation refuses to overwrite an existing file or workspace. If the proposed child directory
already exists, the researcher must choose another name or use **Open Folder**. Initialization
must be atomic enough that a failure cannot leave a registered but invalid project.

### 4.4 Open Folder

The researcher chooses an existing directory. The application validates its canonical path,
readability, and `research.yaml` before registration.

- A valid workspace is registered and opened.
- A readable directory without `research.yaml` is not modified automatically. The interface
  offers **Initialize as research project** and describes the files that will be created.
- An invalid or unsupported workspace shows the validation error without adding a usable
  project entry.
- A path already registered opens the existing project instead of creating a duplicate.

### 4.5 Project rail and routing

The existing project rail becomes the project switcher. It shows the active project, recent
projects, background activity in other projects, and an add-project action. The per-project
menu includes:

- Open;
- Open in Explorer or the Linux file manager;
- Rename display name;
- Locate folder;
- Forget project.

Workspace URLs use `/projects/{project_id}/...`. Reloading a page therefore restores the same
project, and switching projects does not cancel work in the previous project. The active
project name remains visible in the workspace header to reduce cross-project mistakes.

## 5. Architecture

```text
research app
    |
    v
Multi-project FastAPI application
    |
    +-- App authentication and same-origin checks
    +-- Project Registry
    +-- Project Manager
    +-- Native Folder Picker adapters
    +-- Project Runtime Pool
            |
            +-- project A -> WorkspaceRuntime(root A, lock A, capabilities)
            +-- project B -> WorkspaceRuntime(root B, lock B, capabilities)
            +-- project C -> created lazily when opened
```

### 5.1 Project Registry

The registry is application state, not scientific project state. Its default locations are:

- Windows: `%LOCALAPPDATA%\ResearchHarness\projects.json`
- Linux: `$XDG_DATA_HOME/research-harness/projects.json`, falling back to
  `~/.local/share/research-harness/projects.json`

The implementation should use the platform data-directory convention through one focused
path service rather than spreading OS checks through the codebase.

Each registry entry contains:

```text
project_id          opaque, stable random identifier
display_name        application label; initially the workspace name
canonical_root      absolute normalized path
created_at          registry insertion time
last_opened_at      last successful open
status_hint         optional cached diagnostic, never authoritative
```

The registry contains no research content, model credentials, workspace token, or copied
configuration. Writes use a temporary sibling file, flush, and atomic replacement. A corrupt
registry is preserved for diagnosis and reported clearly; it must not be silently replaced
with an empty registry.

### 5.2 Project Manager

The Project Manager is the only application component allowed to turn a newly selected local
path into a registered project. It owns create, open, locate, rename-display-name, forget, and
list operations.

It resolves paths before comparing them, rejects non-directories, validates the workspace
schema with the existing repository boundary, and deduplicates by canonical path. Where the
platform exposes a stable filesystem identity, it may be used as an additional duplicate
signal, but correctness cannot depend on it.

Forgetting a project deletes only its registry entry. It never deletes, moves, or edits the
project directory. A project with an active run cannot be forgotten; the user must wait for
the run or cancel it first.

### 5.3 WorkspaceRuntime

`WorkspaceRuntime` holds the per-project operational dependencies currently captured by
`create_app(root)`, including:

- canonical workspace root;
- capability registry;
- principal resolution appropriate to the host app;
- mutation gate;
- access to durable run state;
- health and last-access metadata.

The runtime is created lazily after registry validation. A runtime pool caches active runtimes
by `project_id`. Idle runtimes with no active workflow may be evicted; reopening them must be
observationally equivalent because canonical and durable run state remains on disk.

Locks remain per workspace. A write in project A must not block an unrelated write in project
B. Existing repository locks still protect against a CLI, editor, MCP host, or single-project
daemon mutating the same workspace concurrently.

### 5.4 Shared route construction

The server routes must have one implementation used in both modes:

- `create_app(root)` supplies a fixed workspace resolver for the existing one-workspace
  daemon;
- `create_multi_project_app(...)` supplies a resolver that derives the runtime from the
  validated `project_id` path segment.

Scientific behavior remains in capabilities and repositories. The multi-project application
must not duplicate capability handlers, domain rules, DTOs, or response mapping.

## 6. HTTP surface

The control-plane API is:

```text
GET    /api/projects
POST   /api/projects/create
POST   /api/projects/open
POST   /api/projects/{project_id}/locate
PATCH  /api/projects/{project_id}
DELETE /api/projects/{project_id}
POST   /api/dialogs/folder
```

Project-scoped workspace routes live below:

```text
GET    /api/projects/{project_id}/health
GET    /api/projects/{project_id}/capabilities
POST   /api/projects/{project_id}/capabilities/{name}
GET    /api/projects/{project_id}/runs/{run_id}
POST   /api/projects/{project_id}/runs/{run_id}/cancel
GET    /api/projects/{project_id}/objects/{object_id}
GET    /api/projects/{project_id}/overview
GET    /api/projects/{project_id}/index
...the existing workspace-scoped byte, session, graph, and manuscript routes
```

Existing request and response bodies remain unchanged after the project prefix. A run lookup
is always scoped to the selected runtime; a run from another project is reported as not found.

Folder paths are accepted only by authenticated control-plane operations associated with a
human selection or typed-path fallback. No capability request may override its resolved root.

## 7. Folder-picker adapters

Folder selection is initiated by the authenticated Web UI but executed by the local daemon.
The picker returns its result to the Project Manager, not directly to a project-scoped API.

Adapters implement one small interface: select an existing directory, or report cancellation
or unavailability without changing state.

- Windows uses a native folder selection dialog.
- Linux tries `zenity`, then `kdialog`.
- If neither Linux picker exists, the UI offers an authenticated manual-path field.

Picker commands must use argument arrays rather than shell command strings. Cancellation is a
normal result, not an application error. The Web request remains bounded; if a platform dialog
cannot safely be driven within the server process, the adapter may use a short-lived helper
process.

## 8. Authentication and authority

### 8.1 App token

The multi-project app uses one random application token stored beside other application data
with owner-only permissions where supported. Startup opens a local URL carrying a one-time
bootstrap value; the Web client retains authentication only for the current local browser
session and removes the secret from the visible URL.

The server binds only to `127.0.0.1`. Every control-plane mutation requires valid app
authentication and an allowed same-origin request. In particular, unauthenticated callers
cannot:

- enumerate local project paths;
- open a folder picker;
- register or locate a folder;
- rename or forget a project.

The single-workspace `.research/daemon-token` behavior remains unchanged for
`research serve`.

### 8.2 Research authority

Registering a folder grants Research Harness access to that workspace; it does not expand a
model's scientific authority. Existing principals and capability permissions remain the
source of truth:

- authenticated researcher actions may invoke their existing human-authorized operations;
- an AI or agent-host caller may read and stage only as currently permitted;
- accepted scientific state still requires the applicable human review transition.

This release does not add generic arbitrary-file read/write endpoints. Access to workspace
content continues through Research Harness repositories, manuscript services, attachment
services, and named capabilities. A future general-purpose file agent would require a
separate authority and review design.

## 9. Filesystem safety

- Registry roots are absolute and canonicalized before use.
- Duplicate roots map to one project entry even when entered through different path syntax.
- Every project-relative file operation must prove that its resolved target remains beneath
  the registered canonical root.
- `..`, absolute child paths, alternate-drive paths, and symlinks escaping the root are
  rejected.
- The runtime revalidates that the registered root still identifies a usable workspace when
  it is opened after eviction or application restart.
- A relocated project becomes unavailable until the researcher uses **Locate folder**.
- Locate verifies the selected workspace before atomically replacing the registered root.
- No error response sent to an unauthenticated caller includes a local filesystem path.

## 10. Failure behavior

Failures are isolated to the affected project whenever possible.

- Missing or unmounted folder: mark project unavailable and offer Locate.
- Missing `research.yaml`: report that the folder is no longer a workspace; do not initialize
  it automatically.
- Newer unsupported schema: expose a read-only compatibility state when existing repository
  rules can safely read it; otherwise block opening with upgrade guidance.
- Invalid or corrupt schema: keep the registry entry, block workspace operations, and show the
  validation error.
- Busy workspace: surface the existing lock/busy result; never bypass the lock.
- Registry write failure: do not claim that the project was added, renamed, located, or
  forgotten.
- Picker unavailable: offer the supported fallback without altering registry state.
- Failure in one runtime: keep Project Home and every other project usable.

Switching projects while a workflow runs leaves that workflow active. The project rail shows
its state, and returning to the project reconnects to durable run status through the existing
run APIs.

## 11. Frontend changes

The Web application gains:

1. a Project Home route;
2. a project registry client and query state;
3. create, open, initialize, locate, rename, and forget dialogs;
4. project-aware routing and API base selection;
5. an expanded project rail with availability and background-run indicators;
6. clear project identity in every workspace header;
7. empty, loading, unavailable, incompatible, busy, and registry-error states.

Workspace views should continue to consume their existing DTOs. Project selection belongs at
the API-client and application-layout boundaries rather than being threaded through every
presentational component.

Last-session memory remains keyed by workspace/project identity. Changing the registered path
through Locate must not discard the project's remembered conversation state.

## 12. CLI compatibility

The new command is:

```text
research app [--port <port>] [--no-open]
```

It does not accept `--workspace` because the application manages projects internally.
`--no-open` supports development and environments where launching a browser is undesirable.

The following remain unchanged:

```text
research serve -w <workspace>
research mcp -w <workspace>
research <command> -w <workspace>
RESEARCH_WORKSPACE=<workspace> research <command>
```

No existing workspace format migration is required merely to register a project with the
multi-project app.

## 13. Testing strategy

Implementation follows test-first development.

### 13.1 Unit tests

- Application data paths on Windows and Linux/XDG.
- Registry round-trip, atomic replacement, stable ordering, corruption handling, and no
  accidental secret fields.
- Canonical-path deduplication, missing roots, invalid roots, and relocated roots.
- Traversal, alternate-root, and escaping-symlink rejection.
- Project Manager create, open, initialize, locate, rename, forget, and active-run refusal.
- Windows and Linux picker adapters, including cancellation and unavailable fallbacks.
- Runtime pooling, independent mutation gates, idle eviction, and lazy recreation.

### 13.2 API and security tests

- Control-plane routes reject missing or invalid app authentication.
- Same-origin enforcement covers every control-plane mutation.
- Unauthenticated responses never disclose registered paths.
- A project-scoped request cannot select or read another project by body, query, object ID, or
  run ID.
- Existing capability envelopes and error codes remain unchanged beneath the project prefix.
- Single-workspace HTTP route contracts continue to pass.

### 13.3 Integration and concurrency tests

- Create and open produce valid repositories through the existing initialization/open paths.
- Concurrent mutations in separate projects proceed independently.
- Concurrent mutation of one project through app and CLI remains serialized by the workspace
  lock.
- A long-running operation survives navigation to another project and is recoverable after an
  app restart.
- Forget refuses active runs and removes no project files after success.
- Registry restart restores recent-project ordering and project identity.

### 13.4 Web end-to-end tests

- First-run empty Project Home.
- New Project, Open Folder, and Initialize-as-project flows.
- Duplicate folder opens the existing project.
- Switch, deep-link, refresh, and last-project restoration.
- Rename display name without changing `research.yaml`.
- Forget confirmation states explicitly that files remain on disk.
- Missing folder and successful Locate flow.
- Background workflow indicators across project switches.
- Keyboard navigation, focus restoration after dialogs, and screen-reader labels.

### 13.5 Platform smoke tests

- Windows native picker, browser launch, path normalization, and Explorer action.
- Linux `zenity`, `kdialog`, typed-path fallback, XDG path selection, and file-manager action.

CI must not require an interactive native dialog. Picker behavior is covered by adapter tests;
interactive checks are opt-in smoke tests.

## 14. Acceptance criteria

1. `research app` starts successfully outside every research workspace and opens the local Web
   application.
2. A researcher can create a workspace, open an existing workspace, and initialize a selected
   ordinary folder from the Web interface.
3. Registered projects persist across restarts without copying their contents.
4. Switching projects does not restart the server or cancel work in another project.
5. Project A cannot read an object, file, run, or capability context belonging to project B.
6. Mutations in different projects use independent runtime gates; mutations of the same
   project remain protected by the existing workspace lock.
7. Control-plane operations and local paths are unavailable without valid app authentication.
8. Forgetting a project removes only the registry entry and never deletes project files.
9. Windows and Linux provide a folder selection path, including the documented Linux fallback.
10. An unavailable or invalid project does not prevent other projects or Project Home from
    working.
11. `research serve -w`, MCP, CLI commands, workspace tokens, existing HTTP responses, and
    existing workspace files remain backward compatible.
12. AI access remains bounded by the existing read/stage/review authority model; the feature
    introduces no generic arbitrary-file or shell authority.

## 15. Suggested implementation boundaries

The later implementation plan should preserve small, independently testable units:

```text
src/research_harness/app/
├── paths.py          # platform application-data locations
├── models.py         # project registry records and public views
├── registry.py       # atomic persistence and canonical-path lookup
├── manager.py        # project lifecycle operations
├── runtime.py        # WorkspaceRuntime and runtime pool
├── auth.py           # app token and browser bootstrap
└── pickers/
    ├── base.py
    ├── windows.py
    └── linux.py
```

Server route factories should remain under the server package, and Web changes remain under
the existing app, API, and view boundaries. These names are guidance for the implementation
plan, not an obligation to create large framework abstractions before a vertical slice proves
them useful.

## 16. Implementation request

After review, implementation can be requested with:

> Implement `docs/superpowers/specs/2026-09-04-multi-project-local-app-design.md` using
> test-driven development while preserving single-workspace CLI, MCP, and HTTP behavior.

That later request authorizes implementation; this design document by itself does not.

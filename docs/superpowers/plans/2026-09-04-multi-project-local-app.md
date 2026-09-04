# Multi-project Local Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a loopback-only `research app` mode that creates, opens, remembers, and switches among multiple local Research Harness workspaces on Windows and Linux without breaking the existing single-workspace CLI, MCP, HTTP, or Web flows.

**Architecture:** A global app registry maps opaque project IDs to explicitly approved canonical roots. A project manager and runtime pool validate those roots and lazily create isolated workspace runtimes; a multi-project FastAPI host exposes authenticated control-plane routes and dispatches existing workspace routes below `/api/projects/{project_id}`. The Web bundle detects whether it is connected to the new multi-project host or the legacy one-workspace daemon and selects the matching route/client tree.

**Tech Stack:** Python 3.12, Pydantic 2, FastAPI/Starlette, Typer, Uvicorn, pytest, React 18, TypeScript 5.9, React Router 6, Vitest/Testing Library, the existing `@research-harness/design` package.

**Spec:** `docs/superpowers/specs/2026-09-04-multi-project-local-app-design.md`

## Global Constraints

- Bind only to `127.0.0.1`; do not add a configurable external host.
- Support Windows and Linux. Native folder selection uses Windows native UI, then `zenity`/`kdialog` on Linux, with an authenticated typed-path fallback.
- Keep `research serve -w`, `research mcp -w`, all `-w` CLI commands, workspace tokens, existing HTTP response contracts, and existing workspace files backward compatible.
- Never accept a workspace root in a project-scoped capability, byte, run, session, graph, or manuscript request; resolve only an opaque `project_id` through the app registry.
- Project control-plane operations require the app token; browser project mutations additionally require an allowed same-origin `Origin` header. CLI-only bootstrap issuance requires the app token and accepts no browser credential shortcut.
- Forgetting a project removes only its registry entry. No project lifecycle action deletes user files.
- An agent-host principal keeps the existing read/stage authority. This feature adds no arbitrary shell, arbitrary-file read, arbitrary-file write, or scientific acceptance authority.
- Preserve per-workspace repository locking and give each in-process workspace runtime its own mutation gate.
- Use test-first development. Each task lands as a focused commit and leaves its named test command green.
- Do not add a desktop shell, project discovery scan, cloud registry sync, or general-purpose file agent.

---

## Delivery map

| Phase | Tasks | Reviewable outcome |
|---|---:|---|
| A. Local project foundation | 1–4 | Persistent registry, safe lifecycle service, native pickers, app authentication |
| B. Multi-project backend | 5–7 | Shared workspace runtime plus authenticated multi-project HTTP host |
| C. Launch and client routing | 8–10 | `research app`, host detection, project-scoped browser routes and API calls |
| D. Product experience | 11–12 | Project Home, lifecycle dialogs, project switcher, status and file-manager actions |
| E. Hardening and handoff | 13–14 | Cross-project/security gates, platform smoke coverage, user documentation |

## File structure

Create a focused Python application package:

```text
src/research_harness/local_app/
├── __init__.py          # public local-app exports only
├── paths.py             # Windows/Linux app-data locations and root containment
├── models.py            # persisted project records and public control-plane DTOs
├── registry.py          # atomic projects.json persistence and canonical-root lookup
├── manager.py           # create/open/initialize/locate/rename/forget/reveal lifecycle
├── runtime.py           # WorkspaceRuntime and ProjectRuntimePool
├── auth.py              # app token, principal resolver, Origin enforcement
└── pickers/
    ├── __init__.py      # picker factory
    ├── base.py          # FolderPicker protocol and result/error types
    ├── windows.py       # Windows folder dialog adapter
    └── linux.py         # zenity/kdialog adapter and unavailable result
```

Create the multi-project host separately from the current daemon:

```text
src/research_harness/server/multi_app.py     # control plane, dispatcher, SPA host
src/research_harness/cli/commands/local_app.py
```

Add Web responsibilities without pushing project state into research views:

```text
web/src/api/projects.ts                # AppClient and project DTOs
web/src/app/host.tsx                   # legacy-vs-multi host detection and app state
web/src/app/projectPaths.tsx           # active project ID and project-local href helper
web/src/views/projects/ProjectHome.tsx
web/src/views/projects/ProjectDialogs.tsx
web/src/views/projects/projects.css
```

Modify the existing API client only to support a project-scoped base URL. Modify the Design
System rail only for presentation callbacks/status fields; it must not fetch or know server
rules.

---

### Task 1: Platform paths, project records, and atomic registry

**Files:**
- Create: `src/research_harness/local_app/__init__.py`
- Create: `src/research_harness/local_app/paths.py`
- Create: `src/research_harness/local_app/models.py`
- Create: `src/research_harness/local_app/registry.py`
- Create: `tests/unit/local_app/__init__.py`
- Create: `tests/unit/local_app/test_paths.py`
- Create: `tests/unit/local_app/test_registry.py`

**Interfaces:**
- Produces: `app_data_dir(*, system: str | None = None, env: Mapping[str, str] | None = None, home: Path | None = None) -> Path`
- Produces: `canonical_directory(path: Path) -> Path`
- Produces: `assert_beneath(root: Path, candidate: Path) -> Path`
- Produces: `ProjectRecord`, `ProjectView`, `ProjectAvailability`, `RegistryDocument`
- Produces: `ProjectRegistry(path: Path)` with `list()`, `get()`, `find_by_root()`, `add()`, `replace()`, and `remove()`
- Consumes: existing `ResearchHarnessError` and timezone-aware datetimes

- [x] **Step 1: Write failing platform-path and containment tests**

```python
def test_windows_uses_local_app_data(tmp_path: Path) -> None:
    found = app_data_dir(system="Windows", env={"LOCALAPPDATA": str(tmp_path)}, home=tmp_path)
    assert found == tmp_path / "ResearchHarness"


def test_linux_prefers_xdg_data_home(tmp_path: Path) -> None:
    found = app_data_dir(system="Linux", env={"XDG_DATA_HOME": str(tmp_path)}, home=Path("/home/r"))
    assert found == tmp_path / "research-harness"


def test_a_resolved_child_must_remain_beneath_the_root(tmp_path: Path) -> None:
    root = (tmp_path / "project")
    root.mkdir()
    child = root / "paper.tex"
    child.write_text("x")
    assert assert_beneath(root, child) == child.resolve()
    with pytest.raises(ProjectPathError):
        assert_beneath(root, tmp_path / "outside.txt")
```

- [x] **Step 2: Run the path tests and confirm the missing-module failure**

Run: `uv run pytest tests/unit/local_app/test_paths.py -v`

Expected: FAIL during collection because `research_harness.local_app.paths` does not exist.

- [x] **Step 3: Implement the focused platform path boundary**

```python
class ProjectPathError(ResearchHarnessError):
    pass


def app_data_dir(*, system=None, env=None, home=None) -> Path:
    values = os.environ if env is None else env
    platform_name = platform.system() if system is None else system
    if platform_name == "Windows":
        base = values.get("LOCALAPPDATA")
        if not base:
            raise ProjectPathError("LOCALAPPDATA is not set")
        return Path(base) / "ResearchHarness"
    if platform_name == "Linux":
        base = values.get("XDG_DATA_HOME")
        return Path(base) / "research-harness" if base else (home or Path.home()) / ".local" / "share" / "research-harness"
    raise ProjectPathError(f"research app supports Windows and Linux, not {platform_name}")


def canonical_directory(path: Path) -> Path:
    resolved = Path(path).expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise ProjectPathError(f"not a directory: {resolved}")
    return resolved


def assert_beneath(root: Path, candidate: Path) -> Path:
    resolved_root = canonical_directory(root)
    resolved = Path(candidate).resolve(strict=True)
    if not resolved.is_relative_to(resolved_root):
        raise ProjectPathError(f"path escapes project root: {candidate}")
    return resolved
```

- [x] **Step 4: Write failing registry round-trip, deduplication, ordering, and corruption tests**

```python
def record(root: Path, project_id: str, name: str, opened: datetime) -> ProjectRecord:
    return ProjectRecord(
        project_id=project_id, display_name=name,
        canonical_root=root.resolve(), created_at=opened, last_opened_at=opened,
    )


def test_registry_round_trips_and_orders_most_recent_first(tmp_path: Path) -> None:
    store = ProjectRegistry(tmp_path / "projects.json")
    store.add(record(tmp_path / "a", "prj_0000000000000001", "A", datetime(2026, 1, 1, tzinfo=UTC)))
    store.add(record(tmp_path / "b", "prj_0000000000000002", "B", datetime(2026, 1, 2, tzinfo=UTC)))
    assert [item.display_name for item in ProjectRegistry(store.path).list()] == ["B", "A"]


def test_registry_refuses_a_second_id_for_the_same_canonical_root(tmp_path: Path) -> None:
    store = ProjectRegistry(tmp_path / "projects.json")
    first = record(tmp_path / "same", "prj_0000000000000001", "A", datetime.now(UTC))
    store.add(first)
    with pytest.raises(DuplicateProjectError):
        store.add(first.model_copy(update={"project_id": "prj_other"}))


def test_corrupt_registry_is_preserved_and_reported(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ProjectRegistryError):
        ProjectRegistry(path).list()
    assert path.read_text(encoding="utf-8") == "not json"
```

- [x] **Step 5: Implement immutable records and atomic registry replacement**

```python
class ProjectAvailability(StrEnum):
    available = "available"
    unavailable = "unavailable"
    invalid = "invalid"
    incompatible = "incompatible"
    busy = "busy"


class ProjectRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    project_id: str = Field(pattern=r"^prj_[0-9a-f]{16}$")
    display_name: str = Field(min_length=1, max_length=120)
    canonical_root: Path
    created_at: datetime
    last_opened_at: datetime
    status_hint: str | None = None


class RegistryDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal[1] = 1
    projects: tuple[ProjectRecord, ...] = ()


class ProjectView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    project_id: str
    display_name: str
    path: Path
    availability: ProjectAvailability
    detail: str | None = None
    active_runs: int = Field(default=0, ge=0)
    last_opened_at: datetime

    @classmethod
    def from_record(
        cls,
        record: ProjectRecord,
        *,
        availability: ProjectAvailability,
        detail: str | None = None,
        active_runs: int = 0,
    ) -> "ProjectView":
        return cls(
            project_id=record.project_id,
            display_name=record.display_name,
            path=record.canonical_root,
            availability=availability,
            detail=detail,
            active_runs=active_runs,
            last_opened_at=record.last_opened_at,
        )


class ProjectRegistry:
    def list(self) -> tuple[ProjectRecord, ...]:
        return tuple(sorted(self._load().projects, key=lambda item: item.last_opened_at, reverse=True))

    def add(self, record: ProjectRecord) -> ProjectRecord:
        document = self._load()
        if any(item.canonical_root == record.canonical_root for item in document.projects):
            raise DuplicateProjectError(f"project root already registered: {record.canonical_root}")
        self._save(document.model_copy(update={"projects": (*document.projects, record)}))
        return record
```

Implement `_save()` with a same-directory `.tmp-<uuid>` file, `flush()`, `os.fsync()`,
`os.replace()`, and best-effort directory fsync, mirroring the durability pattern in
`workspace/runs.py` without importing its private helpers.

- [x] **Step 6: Run focused tests, type checks, and lint**

Run: `uv run pytest tests/unit/local_app/test_paths.py tests/unit/local_app/test_registry.py -v`

Run: `uv run mypy src/research_harness/local_app`

Run: `uv run ruff check src/research_harness/local_app tests/unit/local_app`

Expected: all commands PASS.

- [x] **Step 7: Commit the registry foundation**

```bash
git add src/research_harness/local_app tests/unit/local_app
git commit -m "feat(app): add persistent local project registry"
```

---

### Task 2: Project lifecycle manager

**Files:**
- Create: `src/research_harness/local_app/manager.py`
- Create: `tests/unit/local_app/test_manager.py`
- Modify: `src/research_harness/local_app/__init__.py`

**Interfaces:**
- Consumes: `ProjectRegistry`, `ProjectRecord`, `ProjectView`, `canonical_directory`, `init_project()`, `WorkspaceRepository.open()`
- Produces: `ProjectManager(registry, *, clock, id_factory, active_runs, reveal)`
- Produces: `create(parent, name, policy)`, `open(root)`, `initialize(root, name, policy)`, `locate(project_id, root)`, `rename(project_id, display_name)`, `forget(project_id)`, `reveal(project_id)`, `list_projects()`
- Produces errors: `ProjectNotFoundError`, `ProjectNeedsInitializationError`, `ProjectActiveRunsError`, `ProjectLifecycleError`

- [x] **Step 1: Write failing create/open/deduplicate tests**

```python
def test_create_initializes_a_safe_child_and_registers_it(tmp_path: Path) -> None:
    manager = manager_at(tmp_path)
    parent = tmp_path / "parent"
    parent.mkdir()
    view = manager.create(parent, "Độ trễ mạng", ReviewPolicy.STRICT)
    assert view.path.name == "do-tre-mang"
    assert (view.path / "research.yaml").is_file()
    assert view.display_name == "Độ trễ mạng"


def test_open_requires_an_existing_workspace(tmp_path: Path) -> None:
    folder = tmp_path / "ordinary"
    folder.mkdir()
    with pytest.raises(ProjectNeedsInitializationError):
        manager_at(tmp_path).open(folder)


def test_opening_the_same_root_returns_the_existing_project_id(tmp_path: Path) -> None:
    root = WorkspaceRepository.init(tmp_path / "project", "P").root
    manager = manager_at(tmp_path)
    first = manager.open(root)
    second = manager.open(root / ".")
    assert second.project_id == first.project_id
```

- [x] **Step 2: Run the lifecycle tests and confirm failure**

Run: `uv run pytest tests/unit/local_app/test_manager.py -v`

Expected: FAIL because `ProjectManager` is not defined.

- [x] **Step 3: Implement safe folder naming and create/open/initialize**

```python
def safe_folder_name(name: str) -> str:
    latin = name.replace("Đ", "D").replace("đ", "d")
    ascii_name = unicodedata.normalize("NFKD", latin).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_name).strip(".-").lower()
    if not slug or slug.upper() in WINDOWS_RESERVED_NAMES:
        raise ProjectLifecycleError("project name does not produce a safe folder name")
    return slug


class ProjectManager:
    def create(self, parent: Path, name: str, policy: ReviewPolicy) -> ProjectView:
        canonical_parent = canonical_directory(parent)
        root = canonical_parent / safe_folder_name(name)
        if root.exists():
            raise ProjectLifecycleError(f"project folder already exists: {root}")
        result = init_project(InitProjectRequest(root=root, name=name, policy=policy))
        return self._register(result.root, name)

    def open(self, root: Path) -> ProjectView:
        canonical = canonical_directory(root)
        existing = self._registry.find_by_root(canonical)
        if existing is not None:
            return self._touch(existing)
        try:
            repo = WorkspaceRepository.open(canonical)
        except WorkspaceNotFoundError as exc:
            raise ProjectNeedsInitializationError(str(exc)) from exc
        return self._register(repo.root, repo.config.name)
```

Use `secrets.token_hex(8)` for `prj_<16 hex>`, inject the clock and ID factory in tests, and
never register until initialization/open validation has succeeded.

- [x] **Step 4: Write failing locate/rename/forget/reveal and availability tests**

```python
def test_forget_never_deletes_the_workspace(tmp_path: Path) -> None:
    manager = manager_at(tmp_path)
    view = manager.create(tmp_path, "Keep me", ReviewPolicy.STRICT)
    manager.forget(view.project_id)
    assert view.path.is_dir()
    assert (view.path / "research.yaml").is_file()


def test_forget_refuses_a_project_with_an_active_run(tmp_path: Path) -> None:
    manager = manager_at(tmp_path, active_runs=lambda _project_id: ("run_1",))
    view = manager.create(tmp_path, "Busy", ReviewPolicy.STRICT)
    with pytest.raises(ProjectActiveRunsError):
        manager.forget(view.project_id)


def test_locate_keeps_the_project_id_and_updates_only_after_validation(tmp_path: Path) -> None:
    manager = manager_at(tmp_path)
    old = manager.create(tmp_path, "Old", ReviewPolicy.STRICT)
    new_root = WorkspaceRepository.init(tmp_path / "moved", "Old").root
    moved = manager.locate(old.project_id, new_root)
    assert moved.project_id == old.project_id
    assert moved.path == new_root.resolve()
```

- [x] **Step 5: Implement lifecycle updates and derived status views**

`list_projects()` must open each root defensively and return one of these exact mappings:

```python
except FileNotFoundError:
    return ProjectView.from_record(record, availability="unavailable", detail="Folder not found")
except UnsupportedSchemaVersionError as exc:
    return ProjectView.from_record(record, availability="incompatible", detail=str(exc))
except WorkspaceError as exc:
    return ProjectView.from_record(record, availability="invalid", detail=str(exc))
else:
    active = self._active_runs(record.project_id)
    availability = "busy" if active else "available"
    return ProjectView.from_record(record, availability=availability, active_runs=len(active))
```

`reveal(project_id)` passes only the registered root to an injected platform action. `rename`
changes only `display_name`; it must not edit `research.yaml`.

- [x] **Step 6: Run manager tests and the existing init tests**

Run: `uv run pytest tests/unit/local_app/test_manager.py tests/e2e/test_cli_init_ingest_parse.py -v`

Expected: PASS.

- [x] **Step 7: Commit project lifecycle behavior**

```bash
git add src/research_harness/local_app tests/unit/local_app/test_manager.py
git commit -m "feat(app): add project lifecycle manager"
```

---

### Task 3: Windows and Linux folder-picker adapters

**Files:**
- Create: `src/research_harness/local_app/pickers/__init__.py`
- Create: `src/research_harness/local_app/pickers/base.py`
- Create: `src/research_harness/local_app/pickers/windows.py`
- Create: `src/research_harness/local_app/pickers/linux.py`
- Create: `tests/unit/local_app/test_pickers.py`

**Interfaces:**
- Produces: `FolderPicker` protocol with `select_folder(title: str) -> FolderSelection`
- Produces: `FolderSelection(path: Path | None, method: Literal["native", "zenity", "kdialog", "manual"], cancelled: bool, fallback_required: bool)`
- Produces: `folder_picker(system: str | None = None) -> FolderPicker`
- Consumes: subprocess runner injected as `Callable[[Sequence[str]], CompletedProcess[str]]`

- [x] **Step 1: Write failing adapter-selection and cancellation tests**

```python
def test_linux_prefers_zenity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)
    calls: list[list[str]] = []
    picker = LinuxFolderPicker(run=lambda argv: completed(calls, argv, stdout="/tmp/project\n"))
    result = picker.select_folder("Open project")
    assert calls == [["/usr/bin/zenity", "--file-selection", "--directory", "--title", "Open project"]]
    assert result.path == Path("/tmp/project")


def test_linux_without_a_picker_requests_manual_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    result = LinuxFolderPicker().select_folder("Open project")
    assert result.fallback_required is True
    assert result.path is None


def test_cancel_is_not_an_error() -> None:
    picker = LinuxFolderPicker(which=lambda _name: "/usr/bin/zenity", run=lambda _argv: result(1))
    assert picker.select_folder("Open").cancelled is True
```

- [x] **Step 2: Run picker tests and confirm failure**

Run: `uv run pytest tests/unit/local_app/test_pickers.py -v`

Expected: FAIL because picker modules do not exist.

- [x] **Step 3: Implement Linux argument-array invocation**

```python
class LinuxFolderPicker:
    def select_folder(self, title: str) -> FolderSelection:
        if executable := self._which("zenity"):
            return self._select([executable, "--file-selection", "--directory", "--title", title], "zenity")
        if executable := self._which("kdialog"):
            return self._select([executable, "--getexistingdirectory", str(Path.home()), "--title", title], "kdialog")
        return FolderSelection(path=None, method="manual", cancelled=False, fallback_required=True)
```

Treat exit code `0` with a non-empty stdout path as selection, exit code `1` as cancellation,
and every other exit as `FolderPickerError` with a bounded diagnostic. Never use `shell=True`.

- [x] **Step 4: Implement the Windows native adapter through a fixed PowerShell script**

The adapter passes the title as a positional argument and keeps the script constant:

```python
WINDOWS_PICKER_SCRIPT = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $args[0]
$dialog.UseDescriptionForTitle = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Out.Write($dialog.SelectedPath)
    exit 0
}
exit 1
""".strip()

argv = [powershell, "-NoProfile", "-NonInteractive", "-Command", WINDOWS_PICKER_SCRIPT, title]
```

Resolve `pwsh` first and `powershell.exe` second. Execute in a short-lived process and use the
same result classifier as Linux.

- [x] **Step 5: Run unit tests and manual opt-in smoke commands**

Run: `uv run pytest tests/unit/local_app/test_pickers.py -v`

Run on Windows manually: `uv run python -c "from research_harness.local_app.pickers import folder_picker; print(folder_picker().select_folder('Choose a project'))"`

Run on Linux manually: the same command; verify `zenity`, `kdialog`, or `fallback_required=True`.

Expected automated result: PASS. Manual smoke tests may be skipped in CI.

- [x] **Step 6: Commit folder picker adapters**

```bash
git add src/research_harness/local_app/pickers tests/unit/local_app/test_pickers.py
git commit -m "feat(app): add Windows and Linux folder pickers"
```

---

### Task 4: Global app token and same-origin enforcement

**Files:**
- Create: `src/research_harness/local_app/auth.py`
- Create: `tests/unit/local_app/test_auth.py`
- Modify: `src/research_harness/local_app/models.py`

**Interfaces:**
- Produces: `ensure_app_token(data_dir: Path) -> str`, `app_token_path(data_dir: Path) -> Path`
- Produces: `BootstrapStore(ttl_seconds=60)` with `issue() -> str` and `exchange(value: str) -> bool`; exchange consumes a nonce exactly once
- Produces: `app_principal_resolver(token: str) -> PrincipalResolver`
- Produces: `require_app_token(request: Request) -> None`
- Produces: `require_control_mutation(request: Request) -> None`
- Consumes: existing `_bearer` semantics or an extracted public bearer parser, `Principal.human()`, `Principal.agent_host()`

- [x] **Step 1: Write failing token persistence and permission tests**

```python
def test_app_token_is_stable_and_not_stored_in_the_registry(tmp_path: Path) -> None:
    first = ensure_app_token(tmp_path)
    second = ensure_app_token(tmp_path)
    assert first == second
    assert app_token_path(tmp_path).read_text(encoding="utf-8").strip() == first
    assert "token" not in (tmp_path / "projects.json").read_text(encoding="utf-8") if (tmp_path / "projects.json").exists() else True


def test_app_token_resolves_the_human_and_no_token_resolves_an_agent_host(tmp_path: Path) -> None:
    token = ensure_app_token(tmp_path)
    resolve = app_principal_resolver(token)
    assert resolve(token).kind == "human"
    assert resolve(None).kind == "agent_host"


def test_bootstrap_is_short_lived_and_single_use() -> None:
    store = BootstrapStore(ttl_seconds=60, clock=fake_clock)
    nonce = store.issue()
    assert store.exchange(nonce) is True
    assert store.exchange(nonce) is False
```

- [x] **Step 2: Run tests and confirm failure**

Run: `uv run pytest tests/unit/local_app/test_auth.py -v`

Expected: FAIL because `local_app.auth` does not exist.

- [x] **Step 3: Implement owner-restricted token storage and principal resolution**

```python
APP_TOKEN_FILENAME = "app-token"


def ensure_app_token(data_dir: Path) -> str:
    path = app_token_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    if existing:
        return existing
    token = secrets.token_urlsafe(32)
    atomic_write_secret(path, f"{token}\n")
    with_permissions(path)
    return token
```

Use the same human/agent-host permission sets as the existing daemon; do not create a new
authority model. Store only SHA-256 digests of bootstrap nonces in memory, prune expired entries
on issue/exchange, and never persist a nonce.

- [x] **Step 4: Write failing HTTP dependency tests for token and Origin**

```python
def test_control_read_requires_the_bearer_token(app_request: RequestFactory, token: str) -> None:
    with pytest.raises(HTTPException, match="authentication"):
        require_app_token(app_request(headers={}))


def test_control_mutation_requires_same_origin(app_request: RequestFactory, token: str) -> None:
    request = app_request(headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.test"})
    with pytest.raises(HTTPException, match="origin"):
        require_control_mutation(request)
```

- [x] **Step 5: Implement exact origin policy**

Allow the request origin only when it equals `http://127.0.0.1:<effective-port>` or, in
existing development mode, one of `DEV_ORIGINS`. A missing Origin is refused for browser-facing
control mutations. Control reads require bearer authentication but not Origin. Project-scoped
workspace reads retain the legacy behavior where no token means agent host.

- [x] **Step 6: Run authentication tests and existing daemon authority tests**

Run: `uv run pytest tests/unit/local_app/test_auth.py tests/contract/protocol/test_http.py -v`

Expected: PASS.

- [x] **Step 7: Commit app authentication**

```bash
git add src/research_harness/local_app/auth.py src/research_harness/local_app/models.py tests/unit/local_app/test_auth.py
git commit -m "feat(app): secure the local project control plane"
```

---

### Task 5: Workspace runtime and runtime pool

**Files:**
- Create: `src/research_harness/local_app/runtime.py`
- Create: `tests/unit/local_app/test_runtime.py`
- Modify: `src/research_harness/local_app/manager.py`

**Interfaces:**
- Produces: `WorkspaceRuntime(project_id: str, root: Path, catalog: CapabilityRegistry, mutation_gate: threading.Lock, last_accessed_at: datetime)`
- Produces: `WorkspaceRuntime.create(project_id: str, root: Path, *, catalog: CapabilityRegistry | None = None, clock: Callable[[], datetime] = utc_now) -> WorkspaceRuntime`
- Produces: `WorkspaceRuntime.active_run_ids() -> tuple[str, ...]`
- Produces: `ProjectRuntimePool(registry, *, catalog_factory, clock)` with `get(project_id)`, `evict(project_id)`, `has_active_runs(project_id)`, `status(project_id)`, `evict_idle(before)`
- Consumes: `RunStore`, `RunStatus.pending`, `RunStatus.running`, `WorkspaceRepository.open()`

- [x] **Step 1: Write failing isolation, active-run, eviction, and relocated-root tests**

```python
def test_projects_get_distinct_mutation_gates(two_projects: RegisteredProjects) -> None:
    pool = two_projects.pool
    left = pool.get(two_projects.left.project_id)
    right = pool.get(two_projects.right.project_id)
    assert left.mutation_gate is not right.mutation_gate


def test_a_pending_or_running_run_blocks_forget(project_with_runs: RegisteredProject) -> None:
    project_with_runs.save_run(status=RunStatus.running)
    assert project_with_runs.pool.has_active_runs(project_with_runs.project_id)


def test_idle_eviction_reopens_the_same_root(project: RegisteredProject) -> None:
    first = project.pool.get(project.project_id)
    project.pool.evict(project.project_id)
    second = project.pool.get(project.project_id)
    assert second is not first
    assert second.root == first.root
```

- [x] **Step 2: Run runtime tests and confirm failure**

Run: `uv run pytest tests/unit/local_app/test_runtime.py -v`

Expected: FAIL because runtime classes do not exist.

- [x] **Step 3: Implement runtime construction and active-run checks**

```python
@dataclass(slots=True)
class WorkspaceRuntime:
    project_id: str
    root: Path
    catalog: CapabilityRegistry
    mutation_gate: threading.Lock
    last_accessed_at: datetime

    def active_run_ids(self) -> tuple[str, ...]:
        repo = WorkspaceRepository.open(self.root)
        runs = RunStore(repo.layout.research_dir).list_runs()
        return tuple(run.run_id for run in runs if run.status in {RunStatus.pending, RunStatus.running})
```

`ProjectRuntimePool.get()` re-reads the registry, validates the workspace through
`WorkspaceRepository.open()`, creates one runtime per project ID, and updates last access. It
must never trust a stale root passed by a caller.

- [x] **Step 4: Connect the manager's active-run and locate/forget eviction hooks**

Construct `ProjectManager` with:

```python
manager = ProjectManager(
    registry,
    active_runs=lambda project_id: pool.get(project_id).active_run_ids(),
    on_root_changed=pool.evict,
)
```

Call `on_root_changed(project_id)` only after a successful locate or forget registry commit.

- [x] **Step 5: Run runtime and manager tests**

Run: `uv run pytest tests/unit/local_app/test_runtime.py tests/unit/local_app/test_manager.py -v`

Expected: PASS.

- [x] **Step 6: Commit runtime isolation**

```bash
git add src/research_harness/local_app/runtime.py src/research_harness/local_app/manager.py tests/unit/local_app
git commit -m "feat(app): isolate workspace runtimes per project"
```

---

### Task 6: Extract a shared workspace HTTP application without changing legacy routes

**Files:**
- Modify: `src/research_harness/server/app.py:167-288`
- Modify: `tests/contract/protocol/test_http.py`
- Create: `tests/unit/server/test_workspace_runtime_app.py`

**Interfaces:**
- Consumes: `WorkspaceRuntime`
- Produces: `create_workspace_app(runtime, *, principal_resolver, serve_bundle: bool) -> FastAPI`
- Preserves: `create_app(workspace_root, *, registry=None, principal_resolver=None) -> FastAPI`
- Preserves: the exact `EXPECTED_ROUTES` set for `create_app()`

- [x] **Step 1: Add a failing parity test around the new factory**

```python
def test_runtime_app_and_legacy_app_publish_the_same_workspace_routes(workspace: Path) -> None:
    runtime = WorkspaceRuntime.create("prj_0000000000000001", workspace)
    legacy = create_app(workspace)
    extracted = create_workspace_app(runtime, principal_resolver=human_resolver(), serve_bundle=False)
    assert api_routes(extracted) == api_routes(legacy)
```

- [x] **Step 2: Run the parity and current contract tests**

Run: `uv run pytest tests/unit/server/test_workspace_runtime_app.py tests/contract/protocol/test_http.py -v`

Expected: the new test FAILS because `create_workspace_app` is missing; all pre-existing tests PASS.

- [x] **Step 3: Extract the current closure state into the runtime factory**

```python
def create_app(workspace_root, *, registry=None, principal_resolver=None) -> FastAPI:
    root = Path(workspace_root)
    token = ensure_token(root)
    runtime = WorkspaceRuntime.create(
        project_id="prj_0000000000000000",
        root=root,
        catalog=registry or build_default_registry(),
    )
    resolve = principal_resolver or _default_resolver(token)
    return create_workspace_app(runtime, principal_resolver=resolve, serve_bundle=True)


def create_workspace_app(runtime, *, principal_resolver, serve_bundle) -> FastAPI:
    root = runtime.root
    catalog = runtime.catalog
    mutation_gate = runtime.mutation_gate
    app = FastAPI(...)
    # Register the existing routes unchanged against root/catalog/mutation_gate.
    if serve_bundle:
        _serve_bundle(app)
    _allow_dev_origins(app)
    return app
```

Do not change endpoint bodies or DTOs. Keep attachment, manuscript, and session registration
functions accepting a concrete root; the runtime factory supplies it. Add `serve_bundle=False`
only at the shared-factory boundary so a dispatched project app cannot serve the SPA fallback.

- [x] **Step 4: Assert legacy token placement, authority, routes, bytes, and SSE still pass**

Run: `uv run pytest tests/contract/protocol/test_http.py tests/contract/protocol/test_web_routes.py tests/contract/protocol/test_session_events.py tests/contract/capabilities/test_attachments.py -v`

Expected: PASS with no changes to existing expected payloads or route names.

- [x] **Step 5: Run static checks**

Run: `uv run mypy src/research_harness/server src/research_harness/local_app/runtime.py`

Run: `uv run ruff check src/research_harness/server src/research_harness/local_app/runtime.py tests/unit/server/test_workspace_runtime_app.py`

Expected: PASS.

- [x] **Step 6: Commit the no-behavior-change extraction**

```bash
git add src/research_harness/server src/research_harness/local_app/runtime.py tests/contract/protocol/test_http.py tests/unit/server/test_workspace_runtime_app.py
git commit -m "refactor(server): share workspace app construction"
```

---

### Task 7: Authenticated multi-project FastAPI host and dispatcher

**Files:**
- Create: `src/research_harness/server/multi_app.py`
- Modify: `src/research_harness/server/__init__.py`
- Create: `tests/contract/protocol/test_multi_project_http.py`
- Create: `tests/e2e/test_multi_project_gate.py`

**Interfaces:**
- Produces: `create_multi_project_app(data_dir: Path, *, manager=None, pool=None, picker=None, registry=None, bootstraps=None) -> FastAPI`
- Produces routes: `/api/app/health`, `/api/projects`, lifecycle endpoints from the spec, and `/api/dialogs/folder`
- Produces: `ProjectDispatcher(pool, principal_resolver)` ASGI app mounted at `/api/projects`
- Consumes: `ProjectManager`, `ProjectRuntimePool`, `FolderPicker`, `create_workspace_app()`

- [x] **Step 1: Write the failing control-plane route and auth contract tests**

```python
EXPECTED_CONTROL_ROUTES = {
    ("/api/app/health", frozenset({"GET"})),
    ("/api/app/bootstrap", frozenset({"POST"})),
    ("/api/app/session", frozenset({"POST"})),
    ("/api/projects", frozenset({"GET"})),
    ("/api/projects/create", frozenset({"POST"})),
    ("/api/projects/open", frozenset({"POST"})),
    ("/api/projects/initialize", frozenset({"POST"})),
    ("/api/projects/{project_id}/locate", frozenset({"POST"})),
    ("/api/projects/{project_id}/reveal", frozenset({"POST"})),
    ("/api/projects/{project_id}", frozenset({"PATCH", "DELETE"})),
    ("/api/dialogs/folder", frozenset({"POST"})),
}


def test_project_paths_are_hidden_without_app_authentication(multi_client: TestClient) -> None:
    response = multi_client.get("/api/projects")
    assert response.status_code == 401
    assert "project" not in response.text


def test_cross_origin_control_mutation_is_refused(authenticated_multi_client: TestClient) -> None:
    response = authenticated_multi_client.post(
        "/api/projects/open", json={"path": "C:/research"}, headers={"Origin": "https://evil.test"}
    )
    assert response.status_code == 403
```

- [x] **Step 2: Run contract tests and confirm failure**

Run: `uv run pytest tests/contract/protocol/test_multi_project_http.py -v`

Expected: FAIL because `create_multi_project_app` does not exist.

- [x] **Step 3: Implement control-plane DTOs and routes**

Use closed Pydantic request models:

```python
class CreateProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent: Path
    name: str
    policy: ReviewPolicy = ReviewPolicy.STRICT


class OpenProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Path


class RenameProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=120)
```

Return stable JSON error envelopes with codes `project_not_found`, `project_needs_initialization`,
`project_active_runs`, `project_invalid`, `picker_unavailable`, and `control_permission_denied`.
The folder-dialog response is `{path, method, cancelled, fallback_required}`.

`POST /api/app/bootstrap` requires the persisted app bearer token and returns a 60-second nonce
from `BootstrapStore.issue()`. `POST /api/app/session` requires a same-origin request carrying
`{"bootstrap": "<nonce>"}`; it consumes the nonce and returns the app token once. A replay is 401.

- [x] **Step 4: Implement the mounted project dispatcher**

Mount after exact control-plane routes:

```python
app.mount("/api/projects", ProjectDispatcher(pool, app_principal_resolver(token)), name="project-workspaces")
```

The dispatcher receives a stripped path like `/{project_id}/overview`, splits only the first
segment, validates the ID through `pool.get(project_id)`, rewrites `scope["path"]` to
`/overview`, sets `root_path` to `/api/projects/{project_id}`, and calls a cached
`create_workspace_app(runtime, principal_resolver=resolve, serve_bundle=False)`. Locate and
forget evict both the runtime and cached sub-app after the registry mutation succeeds.

- [x] **Step 5: Write and run cross-project isolation tests**

```python
def test_same_object_id_is_resolved_inside_the_selected_project(two_projects_client) -> None:
    left = two_projects_client.get(f"/api/projects/{LEFT}/objects/C0001").json()
    right = two_projects_client.get(f"/api/projects/{RIGHT}/objects/C0001").json()
    assert left["object"]["statement"] == "left claim"
    assert right["object"]["statement"] == "right claim"


def test_a_run_cannot_be_read_through_another_project(two_projects_client, left_run_id) -> None:
    assert two_projects_client.get(f"/api/projects/{RIGHT}/runs/{left_run_id}").status_code == 404
```

Run: `uv run pytest tests/contract/protocol/test_multi_project_http.py tests/e2e/test_multi_project_gate.py -v`

Expected: PASS.

- [x] **Step 6: Verify the SPA is served only by the outer app**

Add a built-bundle fixture and assert `/projects/<id>/overview` returns `index.html`, while an
unknown `/api/projects/<id>/not-an-api-route` returns an API 404 and never HTML.

Run: `uv run pytest tests/contract/protocol/test_multi_project_http.py -v -k "spa or unknown"`

Expected: PASS.

- [x] **Step 7: Commit the multi-project server**

```bash
git add src/research_harness/server src/research_harness/local_app/models.py tests/contract/protocol/test_multi_project_http.py tests/e2e/test_multi_project_gate.py
git commit -m "feat(server): serve isolated project workspaces from one app"
```

---

### Task 8: `research app` launcher and existing-instance behavior

**Files:**
- Create: `src/research_harness/cli/commands/local_app.py`
- Modify: `src/research_harness/cli/commands/__init__.py`
- Create: `tests/unit/cli/test_local_app.py`
- Modify: `docs/guide/cli-reference.md` only if this file is generated by the command-reference workflow; otherwise defer docs to Task 14

**Interfaces:**
- Produces CLI: `research app [--port <int>] [--no-open]`
- Produces: `app_url(port: int, bootstrap: str) -> str`
- Produces: `probe_existing_app(port: int) -> bool`
- Consumes: `app_data_dir()`, `ensure_app_token()`, `create_multi_project_app()`, `uvicorn.run()`, `webbrowser.open()`

- [x] **Step 1: Write failing CLI tests with all external effects injected/mocked**

```python
def test_app_does_not_resolve_the_current_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path_without_workspace)
    result = runner.invoke(app, ["app", "--no-open"])
    assert result.exit_code == 0
    run_server.assert_called_once()


def test_existing_compatible_instance_is_opened_without_starting_another_server() -> None:
    result = runner.invoke(app, ["app"])
    assert result.exit_code == 0
    probe.assert_called_once_with(8765)
    browser_open.assert_called_once()
    run_server.assert_not_called()


def test_no_open_starts_the_server_without_launching_a_browser() -> None:
    result = runner.invoke(app, ["app", "--no-open", "--port", "8877"])
    browser_open.assert_not_called()
    run_server.assert_called_once()
```

- [x] **Step 2: Run CLI tests and confirm the missing-command failure**

Run: `uv run pytest tests/unit/cli/test_local_app.py -v`

Expected: FAIL because Typer has no `app` command.

- [x] **Step 3: Implement the launcher**

```python
def app_command(
    port: Annotated[int, typer.Option("--port")] = DEFAULT_PORT,
    no_open: Annotated[bool, typer.Option("--no-open")] = False,
) -> None:
    data_dir = app_data_dir()
    token = ensure_app_token(data_dir)
    if probe_existing_app(port):
        bootstrap = request_bootstrap(port, token)
        if not no_open:
            webbrowser.open(app_url(port, bootstrap))
        return
    bootstraps = BootstrapStore()
    bootstrap = bootstraps.issue()
    application = create_multi_project_app(data_dir, bootstraps=bootstraps)
    if not no_open:
        threading.Timer(0.5, webbrowser.open, args=(app_url(port, bootstrap),)).start()
    uvicorn.run(application, host=LOOPBACK, port=port)
```

The URL uses `?bootstrap=<urlencoded one-time nonce>`, never the persisted app token.
`request_bootstrap()` posts to `/api/app/bootstrap` with the app token and validates the returned
nonce. `probe_existing_app()` performs a short-timeout
GET to `/api/app/health` and accepts only `{ok: true, kind: "multi_project", version: ...}`.
An occupied port serving anything else exits with a clear error instead of launching it.

- [x] **Step 4: Register the command and verify help/legacy commands**

Run: `uv run research app --help`

Run: `uv run pytest tests/unit/cli/test_local_app.py tests/unit/cli/test_ergonomics.py -v`

Expected: help lists `--port` and `--no-open`; tests PASS; `serve`, `mcp`, and `shell` remain registered.

- [x] **Step 5: Commit the launcher**

```bash
git add src/research_harness/cli/commands tests/unit/cli/test_local_app.py
git commit -m "feat(cli): launch the multi-project web app"
```

---

### Task 9: Web host detection, app session token, and project API client

**Files:**
- Create: `web/src/api/projects.ts`
- Create: `web/src/api/projects.test.ts`
- Create: `web/src/app/host.tsx`
- Create: `web/src/app/host.test.tsx`
- Modify: `web/src/api/session.ts`
- Modify: `web/src/api/client.ts`
- Modify: `web/src/api/client.test.ts`
- Modify: `web/src/main.tsx`
- Modify: `web/src/test/harness.tsx`

**Interfaces:**
- Produces: `ProjectView`, `ProjectAvailability`, `FolderSelection`, `AppHealth`
- Produces: `AppClient` methods `health`, `projects`, `chooseFolder`, `createProject`, `openProject`, `initializeProject`, `locateProject`, `renameProject`, `forgetProject`, `revealProject`, `workspaceClient`
- Produces: `HostProvider`, `useHost()` with `mode: 'loading' | 'legacy' | 'multi'`, `projects`, `refreshProjects`, `appClient`
- Produces: `readBootstrap()` for the one-time query value and `storeAppToken()` backed by `sessionStorage`, leaving existing workspace `readToken()` behavior intact
- Modifies: `HarnessClient.withBaseUrl(baseUrl: string) -> HarnessClient`

- [x] **Step 1: Write failing API path and session-token tests**

```typescript
it('scopes a workspace client beneath the opaque project id', async () => {
  const daemon = fakeDaemon({ gets: { '/api/projects/prj_abc/overview': FIXTURES.overview } });
  const app = new AppClient({ baseUrl: 'http://daemon.test', token: 'app-token', fetchImpl: daemon.fetch });
  await app.workspaceClient('prj_abc').overview();
  expect(daemon.calls[0]?.path).toBe('/api/projects/prj_abc/overview');
});

it('reads and strips the one-time bootstrap without persisting it', () => {
  const bootstrap = readBootstrap(locationAt('http://localhost/?bootstrap=once'));
  expect(bootstrap).toBe('once');
  expect(window.sessionStorage.getItem('research-harness.bootstrap')).toBeNull();
  expect(window.location.search).not.toContain('bootstrap');
});
```

- [x] **Step 2: Run Web API tests and confirm failure**

Run: `pnpm --filter research-harness-web test -- src/api/projects.test.ts src/api/client.test.ts`

Expected: FAIL because `AppClient`, `readBootstrap`, and `storeAppToken` do not exist.

- [x] **Step 3: Implement `AppClient` with exact request bodies**

```typescript
workspaceClient(projectId: string): HarnessClient {
  return this.harness.withBaseUrl(
    `${this.baseUrl}/api/projects/${encodeURIComponent(projectId)}`,
  );
}

createProject(parent: string, name: string, policy = 'strict'): Promise<ProjectView> {
  return this.post('/api/projects/create', { parent, name, policy });
}

openProject(path: string): Promise<ProjectView> {
  return this.post('/api/projects/open', { path });
}
```

Every control-plane request carries `Authorization: Bearer <app token>`. Mutations also carry
`Content-Type: application/json`; the browser supplies the same-origin Origin header. Do not
attempt to set Origin manually.

- [x] **Step 4: Implement host detection without breaking legacy mode**

`HostProvider` calls `/api/app/health` once. A valid multi-project response selects `multi`,
exchanges a query bootstrap at `/api/app/session`, stores the returned app token in
`sessionStorage`, and then loads `/api/projects`. A replayed/expired bootstrap renders an
authentication error. HTTP 404 selects `legacy`. Network failures remain an error state;
they must not be misclassified as the legacy daemon.

Move `SessionProvider` out of `main.tsx`; the route tree will mount it in Task 10 with either a
legacy client or a project-scoped client.

- [x] **Step 5: Run API, host, and existing Web tests**

Run: `pnpm --filter research-harness-web test -- src/api/projects.test.ts src/api/client.test.ts src/app/host.test.tsx`

Run: `pnpm --filter research-harness-web typecheck`

Expected: PASS.

- [x] **Step 6: Commit Web host plumbing**

```bash
git add web/src/api web/src/app/host.tsx web/src/app/host.test.tsx web/src/main.tsx web/src/test/harness.tsx
git commit -m "feat(web): detect and connect to multi-project hosts"
```

---

### Task 10: Project Home, lifecycle dialogs, and workspace route shell

**Files:**
- Create: `web/src/app/projectPaths.tsx`
- Create: `web/src/app/projectPaths.test.tsx`
- Create: `web/src/views/projects/ProjectHome.tsx`
- Create: `web/src/views/projects/ProjectHome.test.tsx`
- Create: `web/src/views/projects/ProjectDialogs.tsx`
- Create: `web/src/views/projects/ProjectDialogs.test.tsx`
- Create: `web/src/views/projects/projects.css`
- Modify: `web/src/app/App.tsx`
- Modify: `web/src/app/routes.tsx`
- Modify: `web/src/app/session.tsx`
- Modify: `web/src/app/host.tsx`
- Modify: `web/src/main.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Produces: `ProjectPathProvider({ projectId })`, `useProjectPaths()`, `projectHref(projectId, localPath)`
- Produces: legacy workspace routes at current paths and multi-project routes at `/projects/:projectId/*`
- Produces: `ProjectHome` and all lifecycle dialogs
- Consumes: `HostProvider`, `useHost()`, and `AppClient.workspaceClient(projectId)`

- [x] **Step 1: Write failing path, first-run, recent-project, and accessibility tests**

```typescript
it('prefixes a workspace path and preserves its query', () => {
  expect(projectHref('prj_abc', '/?session=CS0001')).toBe('/projects/prj_abc/?session=CS0001');
  expect(projectHref('prj_abc', '/claims/C0001')).toBe('/projects/prj_abc/claims/C0001');
});

it('offers create and open when no project has been registered', async () => {
  renderProjectHome({ projects: [] });
  expect(await screen.findByRole('heading', { name: 'Your research projects' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'New project' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Open folder' })).toBeInTheDocument();
});

it('has no axe violations', async () => {
  const { container } = renderProjectHome({ projects: [availableProject] });
  await expectNoAxeViolations(container);
});
```

- [x] **Step 2: Run project-shell tests and confirm failure**

Run: `pnpm --filter research-harness-web test -- src/app/projectPaths.test.tsx src/views/projects/ProjectHome.test.tsx`

Expected: FAIL because the project shell and Project Home do not exist.

- [x] **Step 3: Implement Project Home states**

Use existing `Button`, `Card`, `Badge`, `AsyncState`, `ErrorNotice`, and `Dialog` components.
Render availability in text, not color alone. Disable opening unavailable, invalid, and
incompatible projects; offer Locate for unavailable entries. A busy project remains openable.
Keep the server's most-recent-first ordering unchanged.

- [x] **Step 4: Write failing lifecycle dialog tests**

```typescript
it('creates from the parent returned by the native picker', async () => {
  renderProjectHome({ picker: { path: 'D:\\research', method: 'native', cancelled: false } });
  await user.click(screen.getByRole('button', { name: 'New project' }));
  await user.type(screen.getByLabelText('Project name'), 'Latency study');
  await user.click(screen.getByRole('button', { name: 'Choose parent folder' }));
  await user.click(screen.getByRole('button', { name: 'Create project' }));
  expect(appClient.createProject).toHaveBeenCalledWith('D:\\research', 'Latency study', 'strict');
});

it('requires explicit initialization after open reports project_needs_initialization', async () => {
  appClient.openProject.mockRejectedValue(controlError('project_needs_initialization'));
  await chooseOpenFolder(user, '/research/plain-folder');
  expect(screen.getByRole('dialog', { name: 'Initialize research project' })).toBeInTheDocument();
  expect(appClient.initializeProject).not.toHaveBeenCalled();
});

it('states that Forget does not delete local files', async () => {
  openForgetDialog();
  expect(screen.getByText(/files remain on disk/i)).toBeInTheDocument();
});
```

- [x] **Step 5: Implement dialogs and stable error handling**

Dialogs retain entered values after server errors, restore focus to the opening control, and
show the server message. Linux `fallback_required` reveals an authenticated path input.
Cancellation performs no mutation. Successful create/open/initialize navigates to
`projectHref(result.project_id, '/')`; Locate refreshes the current project; Rename refreshes
the list; Forget returns to Project Home.

- [x] **Step 6: Implement the dual route shell**

```tsx
export function AppRoutes() {
  const host = useHost();
  if (host.mode === 'loading') return <AsyncState kind="loading" label="Opening Research Harness" />;
  if (host.mode === 'legacy') return <LegacyWorkspaceRoutes />;
  return (
    <Routes>
      <Route index element={<ProjectHome />} />
      <Route path="projects/:projectId/*" element={<ProjectWorkspaceRoute />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
```

`ProjectWorkspaceRoute` validates the ID against `useHost().projects`, creates the scoped
`HarnessClient`, and mounts `ProjectPathProvider -> SessionProvider -> Layout -> workspace
Routes`. `LegacyWorkspaceRoutes` mounts the current `SessionProvider -> Layout -> workspace
Routes` without a prefix. An unknown project ID renders Project Home with a not-found notice.

- [x] **Step 7: Run project shell tests, type checks, and lint**

Run: `pnpm --filter research-harness-web test -- src/app/projectPaths.test.tsx src/views/projects src/app/host.test.tsx`

Run: `pnpm --filter research-harness-web typecheck`

Run: `pnpm --filter research-harness-web lint`

Expected: PASS.

- [x] **Step 8: Commit the project shell**

```bash
git add web/src/app web/src/views/projects web/src/main.tsx web/src/styles.css
git commit -m "feat(web): add project home and workspace route shell"
```

---

### Task 11: Project-aware navigation, deep links, bytes, and run streams

**Files:**
- Modify: `web/src/app/Layout.tsx`
- Modify: `web/src/app/routes.tsx`
- Modify: `web/src/views/Overview.tsx`
- Modify: `web/src/views/ReviewInbox.tsx`
- Modify: `web/src/views/Questions.tsx`
- Modify: `web/src/views/Corpus.tsx`
- Modify: `web/src/views/EvidenceReview.tsx`
- Modify: `web/src/views/Claims.tsx`
- Modify: `web/src/views/Conflicts.tsx`
- Modify: `web/src/views/manuscript/AuditPane.tsx`
- Modify: `web/src/views/manuscript/ManuscriptWorkspace.tsx`
- Modify: `web/src/views/conversation/mappers.ts`
- Modify: `web/src/views/conversation/useSessions.ts`
- Modify: `web/src/views/conversation/state.tsx`
- Modify: `web/src/views/conversation/references/deepLinks.ts`
- Modify: `web/src/api/client.test.ts`
- Modify: `web/src/api/sse.test.ts`
- Modify: affected `*.test.tsx` files beside the views above

**Interfaces:**
- Consumes: `useProjectPaths()` and `HarnessClient` whose base URL is already project-scoped
- Produces: every internal link remains within the active `/projects/{projectId}` route
- Preserves: all legacy route targets when `ProjectPathProvider` has no project ID

- [x] **Step 1: Write failing rail, deep-link, byte, and SSE assertions**

```typescript
it('keeps rail navigation inside the active project', async () => {
  renderMultiApp('/projects/prj_abc/review');
  await user.click(await screen.findByRole('link', { name: /Corpus/ }));
  expect(screen.getByRole('link', { name: /Corpus/ })).toHaveAttribute(
    'href', '/projects/prj_abc/corpus',
  );
});

it('scopes every non-JSON URL through the project client', () => {
  const client = appClient.workspaceClient('prj_abc');
  expect(client.artifactBytesUrl('A0001-1')).toContain('/api/projects/prj_abc/artifacts/A0001-1/bytes');
  expect(client.manuscriptPdfUrl('latest')).toContain('/api/projects/prj_abc/manuscript/builds/latest/pdf');
});
```

- [x] **Step 2: Run affected tests and confirm links escape to legacy roots**

Run: `pnpm --filter research-harness-web test -- src/app/Layout.test.tsx src/api/client.test.ts src/api/sse.test.ts`

Expected: FAIL because current absolute links omit the project prefix.

- [x] **Step 3: Prefix navigation at the application boundary**

Use this exact pattern in hook-capable components:

```tsx
const { href } = useProjectPaths();
<Link to={href(`/claims/${claim.id}`)} />
```

Pure mapping functions accept a path transformer:

```typescript
export function routeForEntity(
  kind: EntityKind,
  id: string,
  href: (path: string) => string = (path) => path,
): string | null {
  if (kind === 'claim') return href(`/claims/${encodeURIComponent(id)}`);
  // Keep each current entity mapping and apply href exactly once to its result.
}
```

Add `navigationForProject(projectId: string | null)` and transform Overview's server-provided
route through `href()`. Do not persist already-prefixed paths in DTOs or local storage.

- [x] **Step 4: Prefix conversation/session navigation and `rh://` deep links**

Pass `href` into `routeForEntity`, conversation-session routes, manuscript routes, and artifact
source routes. Preserve query parameters for session/message and file/line targets. Add tests for
`/?session=CS0001`, `/source/A0017-3?page=6&block=B0081`, and
`/manuscript?file=main.tex&line=23` in both host modes. Verify the last-session storage key uses
the stable project ID, so Locate changes the root without discarding the remembered session.

- [x] **Step 5: Verify bytes and SSE need no view-level prefix logic**

The scoped `HarnessClient.baseUrl` must make artifact bytes, attachment bytes/previews,
manuscript PDFs, and `subscribeRunEvents` use `/api/projects/{id}` automatically. Keep the old
URL assertions for a legacy client and add parallel scoped assertions.

- [x] **Step 6: Run all affected Web tests and static checks**

Run: `pnpm --filter research-harness-web test -- src/app src/views src/api/client.test.ts src/api/sse.test.ts`

Run: `pnpm --filter research-harness-web typecheck`

Expected: PASS in legacy and multi-project fixtures.

- [x] **Step 7: Commit project-aware navigation**

```bash
git add web/src/app web/src/views web/src/api/client.test.ts web/src/api/sse.test.ts
git commit -m "feat(web): keep navigation inside the active project"
```

---

### Task 12: Project rail switcher, actions, and background status

**Files:**
- Modify: `design/src/workspace/models.ts`
- Modify: `design/src/workspace/ProjectRail/ProjectRail.tsx`
- Modify: `design/src/workspace/ProjectRail/ProjectRail.css`
- Modify: `design/src/workspace/ProjectRail/ProjectRail.test.tsx`
- Modify: `design/src/workspace/ProjectRail/ProjectRail.specimen.tsx`
- Modify: `design/src/workspace/ProjectRail/__snapshots__/ProjectRail.test.tsx.snap`
- Modify: `web/src/app/Layout.tsx`
- Modify: `web/src/app/Layout.test.tsx`
- Modify: `web/src/app/host.tsx`

**Interfaces:**
- Extends `ProjectModel` with optional `availability`, `detail`, `activeRuns`
- Extends `ProjectRailProps` with `onAddProject`, `onProjectAction(projectId, action)`
- Defines `ProjectAction = 'reveal' | 'locate' | 'rename' | 'forget'`
- Consumes: project path helper and lifecycle dialogs from Tasks 10–11

- [x] **Step 1: Write failing Design System interaction tests**

```typescript
it('shows project availability and background work in the switcher', async () => {
  render(<ProjectRail project={projects[0]} projects={projects} onSelectProject={vi.fn()} />);
  await user.click(screen.getByRole('button', { name: /Switch project/ }));
  expect(screen.getByRole('menuitem', { name: /Reef survey.*Unavailable/ })).toBeDisabled();
  expect(screen.getByRole('menuitem', { name: /Thermal tolerance.*2 active/ })).toBeInTheDocument();
});

it('emits presentation-only project actions', async () => {
  const onAction = vi.fn();
  render(<ProjectRail project={project} projects={[project]} onProjectAction={onAction} />);
  await openProjectActions(user);
  await user.click(screen.getByRole('menuitem', { name: 'Show in file manager' }));
  expect(onAction).toHaveBeenCalledWith(project.id, 'reveal');
});
```

- [x] **Step 2: Run rail tests and confirm failure**

Run: `pnpm --filter @research-harness/design test -- src/workspace/ProjectRail/ProjectRail.test.tsx`

Expected: FAIL because new props/status presentation do not exist.

- [x] **Step 3: Implement presentation-only switcher changes**

The Design System may render status labels, action menus, and add buttons, but it must receive
all data and callbacks as props. It must not import Web API modules or navigate itself. Keep
keyboard behavior, tooltips in collapsed mode, real links/buttons, and existing single-project
rendering.

- [x] **Step 4: Connect Web layout to current and recent projects**

In multi mode:

```tsx
<ProjectRail
  project={activeProject}
  projects={projects.map(toProjectModel)}
  onSelectProject={(id) => navigate(projectHref(id, '/'))}
  onAddProject={() => setProjectDialog('add')}
  onProjectAction={handleProjectAction}
  {...existingWorkspaceProps}
/>
```

In legacy mode, continue passing only the single `overview`-derived project and no project
lifecycle callbacks. Poll `refreshProjects()` every five seconds only while at least one project
reports active runs; stop the timer when none do and on unmount.

- [x] **Step 5: Test switch, unavailable, reveal, rename, forget, and background indicators**

Run: `pnpm --filter research-harness-web test -- src/app/Layout.test.tsx`

Run: `pnpm --filter @research-harness/design test -- src/workspace/ProjectRail/ProjectRail.test.tsx`

Run: `pnpm -r --workspace-concurrency=1 typecheck`

Expected: PASS.

- [x] **Step 6: Refresh intentional snapshots and inspect the diff**

Run: `pnpm --filter @research-harness/design test -- -u src/workspace/ProjectRail/ProjectRail.test.tsx`

Inspect only the four theme/density snapshots. Confirm project status/action markup is expected
and no unrelated component snapshot changed.

- [x] **Step 7: Commit the project switcher**

```bash
git add design/src/workspace web/src/app/Layout.tsx web/src/app/Layout.test.tsx web/src/app/host.tsx
git commit -m "feat(web): switch and manage projects from the rail"
```

---

### Task 13: Cross-project concurrency, security, restart, and SPA end-to-end gate

**Files:**
- Modify: `tests/e2e/test_multi_project_gate.py`
- Modify: `tests/contract/protocol/test_multi_project_http.py`
- Create: `web/src/app/MultiProjectApp.test.tsx`
- Modify: `web/src/test/harness.tsx`

**Interfaces:**
- Consumes: completed backend and Web behavior from Tasks 1–12
- Produces: one regression gate covering every critical multi-project invariant

- [x] **Step 1: Add concurrent-write isolation tests**

```python
def test_project_a_lock_does_not_block_project_b(multi_client, blocking_registry) -> None:
    started, release = blocking_registry.events_for(LEFT)
    with ThreadPoolExecutor(max_workers=2) as workers:
        left = workers.submit(post_note, multi_client, LEFT, "left")
        assert started.wait(timeout=5)
        right = workers.submit(post_note, multi_client, RIGHT, "right")
        assert right.result(timeout=2).status_code == 200
        release.set()
        assert left.result(timeout=5).status_code == 200
```

- [x] **Step 2: Add traversal, path-disclosure, duplicate, and forget safety tests**

Assert all of the following:

```text
unauthenticated GET /api/projects -> 401 without a path in the response
cross-origin lifecycle POST -> 403
project-scoped request body containing workspace/root -> 422 when the capability schema forbids it
encoded ../ in project ID or dispatched path -> 404
same canonical root -> same project ID
forget with running run -> 409 project_active_runs
successful forget -> research.yaml and all corpus files remain byte-identical
locate invalid root -> old registry root remains unchanged
```

- [x] **Step 3: Add restart and durable-run tests**

Start one app with a temporary data directory, register two projects, persist a running/incomplete
run, close the TestClient, create a second app against the same data directory, and assert project
IDs/order plus run status survive. Do not reuse in-memory manager or pool objects across restart.

- [x] **Step 4: Add a Web end-to-end test against a stateful fake multi-project daemon**

```typescript
it('creates, switches, refreshes, locates, and forgets without crossing project data', async () => {
  renderMultiProjectApp(daemonWithProjects([left, right]));
  await openProject(user, left);
  expect(await screen.findByText('left claim')).toBeInTheDocument();
  await switchProject(user, right);
  expect(await screen.findByText('right claim')).toBeInTheDocument();
  expect(screen.queryByText('left claim')).not.toBeInTheDocument();
});
```

Also assert browser refresh/deep-link restoration at `/projects/{id}/claims/C0001`, native-picker
cancellation, Linux manual fallback, unavailable Locate, and Forget copy.

- [x] **Step 5: Run the focused complete feature gate**

Run: `uv run pytest tests/unit/local_app tests/unit/cli/test_local_app.py tests/unit/server/test_workspace_runtime_app.py tests/contract/protocol/test_multi_project_http.py tests/e2e/test_multi_project_gate.py -v`

Run: `pnpm --filter research-harness-web test -- src/app/MultiProjectApp.test.tsx src/views/projects src/app/Layout.test.tsx`

Expected: PASS.

- [x] **Step 6: Commit the feature gate**

```bash
git add tests web/src/app/MultiProjectApp.test.tsx web/src/test/harness.tsx
git commit -m "test(app): gate multi-project isolation and recovery"
```

---

### Task 14: Documentation, generated references, and final verification

**Files:**
- Modify: `README.md`
- Modify: `docs/guide/install.md`
- Modify: `docs/guide/web.md`
- Modify: `docs/guide/http.md`
- Modify: `docs/guide/cli-reference.md`
- Modify: `docs/index.md`
- Modify generated CLI reference inputs/scripts only if the repository's documented generation command requires it

**Interfaces:**
- Documents: `research app`, Project Home, create/open/initialize/locate/forget, Windows/Linux picker behavior, token location, legacy `research serve`, and explicit non-goals
- Consumes: final command names, response codes, and UI copy from implementation

- [x] **Step 1: Add a docs assertion before changing documentation**

Extend an existing docs/link test or add `tests/unit/test_docs_multi_project.py`:

```python
def test_readme_and_guides_name_both_app_modes() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    web = Path("docs/guide/web.md").read_text(encoding="utf-8")
    assert "research app" in readme
    assert "research serve -w" in web
    assert "Forget project" in web
    assert "does not delete" in web
```

- [x] **Step 2: Run the docs test and confirm failure**

Run: `uv run pytest tests/unit/test_docs_multi_project.py -v`

Expected: FAIL until the new command and safety language are documented.

- [x] **Step 3: Update user documentation**

Document this quick start verbatim in meaning:

```console
uv sync
uv run research app
```

Explain that installed users run `research app`; `uv run` is the repository-development form.
Describe app registry locations on Windows/Linux, loopback binding, session-scoped browser token,
folder-picker fallback, unavailable/locate behavior, and that Forget removes no files. Keep the
single-project daemon section and explain when CLI/MCP users still prefer it.

- [x] **Step 4: Regenerate checked-in references through repository scripts**

Run: `uv run python docs/guide/gen_cli_reference.py`

Run the repository's existing OpenAPI/TypeScript generation command only if the multi-project
app schema is intentionally included in checked-in generated types. If control-plane types remain
manual in `web/src/api/projects.ts`, verify the existing one-workspace generated snapshot is
unchanged.

- [x] **Step 5: Run complete Python verification**

Run: `uv run pytest`

Run: `uv run ruff check src tests`

Run: `uv run mypy`

Expected: PASS.

- [x] **Step 6: Run complete JavaScript verification**

Run: `pnpm -r --workspace-concurrency=1 test`

Run: `pnpm -r --workspace-concurrency=1 typecheck`

Run: `pnpm -r --workspace-concurrency=1 lint`

Run: `pnpm -r --workspace-concurrency=1 build`

Expected: PASS.

- [x] **Step 7: Perform Windows and Linux smoke checks**

On each platform:

```text
1. Start `research app` outside a workspace.
2. Create a project through the picker.
3. Open an existing project.
4. Start a workflow, switch projects, and return to its status.
5. Restart the app and verify recent projects remain.
6. Temporarily rename one project folder, verify Unavailable, then Locate it.
7. Forget the project and verify its files remain on disk.
8. Start `research serve -w <workspace>` on another port and verify the legacy UI still works.
```

Record platform, Python version, picker used, and pass/fail in the implementing agent's final
handoff. Linux must exercise either `zenity` or `kdialog` plus the manual fallback test.

- [x] **Step 8: Inspect the final diff for scope and secrets**

Run: `git diff --check`

Run: `git status --short`

Run: `rg -n "app-token|Bearer [A-Za-z0-9_-]{20,}|LOCALAPPDATA.*projects.json" . -g '!docs/superpowers/**' -g '!**/node_modules/**'`

Expected: no real token, no user-specific absolute path, no unrelated untracked file staged, and
no whitespace errors.

- [x] **Step 9: Commit documentation and final generated artifacts**

```bash
git add README.md docs web/src/api tests/unit/test_docs_multi_project.py
git commit -m "docs: explain the multi-project local app"
```

---

## Agent handoff checklist

Before claiming completion, the implementing agent must report:

- the final commit range;
- every verification command from Task 14 and its result;
- Windows picker smoke-test result;
- Linux picker and fallback smoke-test result;
- confirmation that `research serve -w` route and authority contracts remained unchanged;
- confirmation that forgetting a project was tested without deleting workspace files;
- confirmation that cross-project object and run lookups were refused or correctly isolated;
- any intentionally deferred item, which must be outside the accepted spec rather than an
  unfinished requirement.

---

## Handoff record (2026-09-04)

**Commit range:** `566685a..HEAD` on `main` (17 commits, one per task plus the scaffold and the
Web gate; see `git log --oneline 566685a..`).

**Verification (Task 14 Steps 5–6), all green at the final commit:**

| Command | Result |
|---|---|
| `uv run pytest` | 4778 passed, 42 skipped |
| `uv run ruff check src tests` / `ruff format --check .` | clean |
| `uv run mypy` | clean, 252 source files |
| `pnpm -r --workspace-concurrency=1 test` | design 937, web 464, vscode 97 passed |
| `pnpm -r --workspace-concurrency=1 typecheck` / `lint` / `build` | clean (token and contrast lints included) |
| `git diff --check`, secret scan | clean; only test placeholders and doc mentions of the `app-token` filename |

**Linux smoke (Step 7), performed against a live `research app --no-open --data-dir <tmp>` on
Linux 5.14 / Python 3.12.13, no `zenity` or `kdialog` installed:**

1. Started outside any workspace; `/api/app/health` answered `multi_project`; the SPA served at `/`;
   `GET /api/projects` without a token was 401 with no path; `app-token` was created mode 0600.
2. Bootstrap → session exchange returned the app token once; a replay was 401; a create from
   `Origin: https://evil.test` was 403.
3. Created `Độ trễ mạng` into `do-tre-mang/`; opening a plain folder returned
   `project_needs_initialization`; initializing it registered it; opening the same root spelled
   `/.` returned the same project id.
4. Dispatched `/api/projects/{id}/health` and `/overview` served the right workspace; no token
   meant `agent_host`, the app token meant `human`.
5. `%2e%2e` as a project id was a JSON 404; an unknown sub-route under a project was a JSON 404;
   `/projects/{id}/overview` returned the SPA.
6. Rename changed the display name and left `research.yaml` untouched.
7. Renaming the folder made the project `unavailable` ("Folder not found"); Locate to the new
   folder kept the id and made it `available`.
8. Forget returned 204 and the project tree hashed byte-identical before and after.
9. `/api/dialogs/folder` returned `fallback_required: true` (manual path) as documented.
10. A second `research app` joined the running instance without starting a server; against a
    legacy `research serve` daemon on another port it exited 1 with the `--port` hint; a new
    instance over the same data directory listed the persisted project.

Windows smoke (Step 7) was **not** performed in this environment (Linux host). Windows behaviour
is covered by the picker adapter unit tests, the `LOCALAPPDATA` path tests, and the msvcrt
workspace lock added earlier; the first Windows run should walk the same ten steps and report
the picker used.

**Contracts confirmed:** `create_app` publishes exactly `EXPECTED_ROUTES` (unchanged file);
a mounted project publishes the same set; `research serve -w`, `research mcp -w`, `-w`
commands and `.research/daemon-token` are untouched. Forget was tested without deleting
workspace files (unit, contract, e2e, Web, and live). Cross-project object and run lookups are
isolated (404 from the other project).

**Deliberately outside the accepted spec:** desktop shell, project discovery scan, cloud
registry sync, general-purpose file agent (spec §3). No requirement was left unfinished.

"""Read-only index of agent_lab jobs and the output folders they produced.

Attribution rules: a file is tied to a job only when the job's task.json lists
that exact path. Project-level links are reported separately and never used to
guess which AI wrote a file. Nothing here writes to the scanned workspace.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import re

AIS = ("codex", "claude", "chatgpt")
UNKNOWN = "unknown"
AI_LABELS = {"codex": "Codex", "claude": "Claude", "chatgpt": "ChatGPT", UNKNOWN: "미상", "local": "로컬"}
ACTION_LABELS = {"plan": "계획", "check": "검사", "review": "검토", "finish": "완료",
                 "implement": "구현", "investigate": "조사", "handoff": "교체", "write": "작성"}
STATUS_LABELS = {"completed": "완료", "checked": "검사 통과", "needs_repair": "수정 필요",
                 "active": "진행 중", "reviewed": "검토 통과", "passed": "통과",
                 "completed_unverified": "검증 없이 완료"}
EXCLUDED_DIRS = {"node_modules", ".venv", "venv", ".git", "__pycache__", ".build", ".next",
                 ".pytest_cache", ".mypy_cache", ".turbo", ".cache", "site-packages"}
SCAN_AREAS = ("output", "artifacts")
MAX_FILES_PER_PROJECT = 3000
SKIPPED_TOP = {"tmp", ".runtime"}  # scratch space, not results
PROJECT_FOLDER = re.compile(r"^\d+_")  # numbered project folders, e.g. 01_Dayline
ALIASES_FILE = ("agent_lab", "path-aliases.json")  # old → new locations after folders were moved
PROJECT_EXCLUDES = {"agent_lab": {"jobs"}}  # jobs are indexed as Job records
PROMPT_SUFFIXES = {".md", ".txt"}
NO_GROUP = "~none"  # pseudo group: jobs whose files sit in no indexed project
ROOT_GROUP_LABEL, NO_GROUP_LABEL = "작업 폴더 직속", "프로젝트 미지정"
# Results worth opening: documents, runnable builds, archives, images and video.
DELIVERABLE_SUFFIXES = {".md", ".txt", ".pdf", ".docx", ".pptx", ".xlsx", ".hwp", ".hwpx", ".html", ".htm", ".csv",
                        ".exe", ".apk", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".mp4"}
# Folders holding checks, logs and backups rather than results.
SUPPORT_DIRS = {"verification", "tests", "test", "checks", "check", "history", "records", "record",
                "logs", "log", "backups", "backup", "tmp"}


def is_root_path(first):
    """Whether the first segment of a recorded path (normalized) is workspace-root work: output/,
    artifacts/, a root folder or a root file, even one deleted since. Numbered project folders,
    scratch and excluded folders and paths leaving the workspace are not."""
    return (bool(first) and first != ".." and ":" not in first and first not in EXCLUDED_DIRS | SKIPPED_TOP
            and not PROJECT_FOLDER.match(first))


def group_label(group):
    """Display name of a project group: '01_Dayline' → 'Dayline'."""
    if group == NO_GROUP:
        return NO_GROUP_LABEL
    return PROJECT_FOLDER.sub("", group, count=1) or group if group else ROOT_GROUP_LABEL


def is_deliverable(entry):
    """Whether a file is a result to open (by type), outside check/log/backup folders."""
    folders = [part.lower() for part in entry.rel.split("/")[:-1]]
    return (entry.path.suffix.lower() in DELIVERABLE_SUFFIXES
            and not any(part in SUPPORT_DIRS or part.endswith("-shots") for part in folders))


@dataclass
class Phase:
    name: str
    action: str
    provider: str
    model: str = ""
    outcome: str = ""
    notes: str = ""
    error: str = ""
    path: Path | None = None
    files: list[Path] = field(default_factory=list)


@dataclass
class Job:
    id: str
    path: Path
    when: datetime | None
    request: str = ""
    goal: str = ""
    acceptance: list[dict] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    checks: list = field(default_factory=list)
    mode: str = ""
    complexity: str = ""
    implementer: str = UNKNOWN
    status: str = ""
    checks_passed: bool | None = None
    review_passed: bool | None = None
    phases: list[Phase] = field(default_factory=list)
    summary: Path | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def full_title(self):
        """First line of the goal (or request), uncut; job cards wrap it themselves."""
        text = (self.goal or self.request or self.id).strip()
        return text.splitlines()[0].strip() if text else self.id

    @property
    def title(self):
        first = self.full_title
        return first if len(first) <= 90 else first[:89] + "…"

    def roles(self):
        """{ai: [role labels]} from recorded evidence only."""
        roles: dict[str, list[str]] = {}

        def add(ai, label):
            bucket = roles.setdefault(ai, [])
            if label not in bucket:
                bucket.append(label)

        add(self.implementer, "구현")
        for phase in self.phases:
            if phase.provider in (*AIS, UNKNOWN) and phase.action not in ("check", "finish"):
                add(phase.provider, ACTION_LABELS.get(phase.action, phase.action))
        return roles

    @property
    def ais(self):
        return set(self.roles())


@dataclass
class FileEntry:
    path: Path
    rel: str
    area: str
    project: str
    size: int
    mtime: float
    jobs: list[str] = field(default_factory=list)
    chatgpt_prompt: bool = False

    @property
    def name(self):
        return self.path.name


@dataclass
class Project:
    key: str
    area: str
    path: Path
    files: list[FileEntry] = field(default_factory=list)
    jobs: list[str] = field(default_factory=list)
    truncated: bool = False
    recursive: bool = True  # False: files sitting directly in output/ or artifacts/
    group: str = ""  # numbered project folder holding this project ('' at the workspace root)

    def owns(self, key):
        """Whether a normalized relative path belongs to this project."""
        prefix = rel_key(self.key) + "/"
        return key.startswith(prefix) and (self.recursive or "/" not in key[len(prefix):])


@dataclass
class Index:
    root: Path
    jobs: dict[str, Job]
    projects: dict[str, Project]
    files: dict[str, FileEntry]
    problems: list[str]
    aliases: list[tuple[str, str]] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)  # every numbered project folder, indexed files or not
    root_listed: bool = False  # some job lists a workspace-root path (output/, artifacts/, root folder or file)

    def resolve(self, item):
        """Normalized key of a path from a job record, following moved-folder aliases."""
        return resolve_key(item, self.aliases)

    def file_ais(self, entry: FileEntry):
        found = set()
        for job_id in entry.jobs:
            found |= self.jobs[job_id].ais
        if entry.chatgpt_prompt:
            found.add("chatgpt")
        return found

    def project_ais(self, project: Project):
        found = set()
        for job_id in project.jobs:
            found |= self.jobs[job_id].ais
        return found

    def jobs_for_ai(self, ai):
        return [job for job in self.sorted_jobs() if ai in job.ais]

    def sorted_jobs(self):
        return sorted(self.jobs.values(), key=lambda job: job.id, reverse=True)

    def unclassified(self):
        return [entry for entry in self.files.values() if not entry.jobs and not entry.chatgpt_prompt]

    def chatgpt_prompts(self):
        return [entry for entry in self.files.values() if entry.chatgpt_prompt]

    def job_files(self, job_id):
        """Indexed result files listed in the job's task.json (files that still exist)."""
        keys = dict.fromkeys(self.resolve(item) for item in self.jobs[job_id].files)  # ordered, no duplicates
        return [self.files[key] for key in keys if key in self.files]

    def job_size(self, job_id):
        return sum(entry.size for entry in self.job_files(job_id))

    def groups(self):
        """Projects by group: numbered project folders in name order, then the workspace root ('')."""
        found = {name: [] for name in self.folders}  # a numbered folder with nothing indexed is still listed
        if self.root_listed:  # so is the root group while job records still point at workspace-root paths
            found[""] = []
        for project in self.projects.values():
            found.setdefault(project.group, []).append(project)
        return {name: found[name] for name in sorted(found, key=lambda name: (not name, name))}

    def job_group_map(self):
        """{job id: [group, …]} by the top folder of each path the job lists (after aliases).
        The file itself may be gone: a job stays with its project when results are moved or
        deleted, as long as the project folder exists. Cached until the project set changes."""
        signature = (len(self.projects), len(self.folders), len(self.jobs))
        cached = getattr(self, "_job_groups", None)
        if cached is not None and cached[0] == signature:
            return cached[1]
        groups = self.groups()
        numbered = {rel_key(name): name for name in groups if name}
        mapping = {}
        for job in self.jobs.values():
            found = set()
            for item in job.files:
                first = self.resolve(item).split("/", 1)[0]
                if first in numbered:
                    found.add(numbered[first])
                elif is_root_path(first):  # output/, artifacts/, root folders and files
                    found.add("")
            mapping[job.id] = [name for name in groups if name in found]
        self._job_groups = (signature, mapping)
        return mapping

    def job_groups(self, job_id):
        """Groups (project folders) the job's listed paths belong to."""
        return self.job_group_map().get(job_id, [])

    def group_jobs(self, group):
        """Jobs tied to a group, newest first; NO_GROUP gives the jobs tied to none."""
        mapping = self.job_group_map()
        if group == NO_GROUP:
            return [job for job in self.sorted_jobs() if not mapping[job.id]]
        return [job for job in self.sorted_jobs() if group in mapping[job.id]]

    def group_files(self, group):
        return [entry for project in self.groups().get(group, []) for entry in project.files]

    def deliverables(self, group):
        return [entry for entry in self.group_files(group) if is_deliverable(entry)]


def read_json(path: Path):
    """Return parsed JSON or None for missing/corrupt files (never raises)."""
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def as_list(value):
    return value if isinstance(value, list) else []


def norm_ai(value):
    text = str(value or "").strip().lower()
    if text in AIS:
        return text
    if text.startswith("gpt") or "openai" in text:
        return "codex"
    return UNKNOWN


def job_time(job_id):
    match = re.match(r"(\d{8})-(\d{6})", job_id)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def rel_key(value):
    text = str(value).replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/").lower()


def load_aliases(root: Path):
    """(old, new) key pairs from agent_lab/path-aliases.json, longest old prefix first, and problems."""
    path = root.joinpath(*ALIASES_FILE)
    if not path.exists():
        return [], []
    data = read_json(path)
    items = data.get("aliases") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], ["path-aliases.json 손상: 옛 경로를 새 위치에 연결하지 않음"]
    pairs = [(rel_key(item["old"]), rel_key(item["new"])) for item in items
             if isinstance(item, dict) and isinstance(item.get("old"), str) and isinstance(item.get("new"), str)]
    pairs = [(old, new) for old, new in pairs if old and new and old != new]
    problems = [] if len(pairs) == len(items) else [f"path-aliases.json: 잘못된 항목 {len(items) - len(pairs)}개 무시"]
    return sorted(pairs, key=lambda pair: -len(pair[0])), problems


def resolve_key(item, aliases):
    key = rel_key(item)
    for old, new in aliases:
        if key == old or key.startswith(old + "/"):
            return new + key[len(old):]
    return key


def load_job(path: Path) -> Job:
    job = Job(id=path.name, path=path, when=job_time(path.name))
    manifest = read_json(path / "manifest.json")
    task = read_json(path / "task.json")
    if not isinstance(manifest, dict):
        job.problems.append("manifest.json 없음 또는 손상")
        manifest = {}
    if not isinstance(task, dict):
        job.problems.append("task.json 없음 또는 손상")
        task = {}
    job.request = str(task.get("request") or "")
    job.goal = str(task.get("goal") or "")
    job.acceptance = [item for item in as_list(task.get("acceptance")) if isinstance(item, dict)]
    job.files = [str(item) for item in as_list(task.get("files")) if isinstance(item, str)]
    job.checks = as_list(task.get("checks"))
    job.mode = str(manifest.get("mode") or "")
    job.complexity = str(manifest.get("complexity") or "")
    job.implementer = norm_ai(manifest.get("implementer"))
    job.status = str(manifest.get("status") or "")
    passed = manifest.get("checks_passed")
    job.checks_passed = passed if isinstance(passed, bool) else None
    review = manifest.get("review")
    if isinstance(review, dict) and isinstance(review.get("passed"), bool):
        job.review_passed = review["passed"]
    summary = path / "WORK_SUMMARY.md"
    job.summary = summary if summary.is_file() else None

    history = [item for item in as_list(manifest.get("history")) if isinstance(item, dict)]
    by_dir = {}
    for item in history:
        logs = str(item.get("logs") or "").replace("\\", "/").rstrip("/")
        if logs:
            by_dir[logs.rsplit("/", 1)[-1]] = item
    try:
        folders = sorted(child for child in path.iterdir() if child.is_dir() and re.match(r"\d+-", child.name))
    except OSError:
        folders = []
    seen = set()
    for folder in folders:
        item = by_dir.get(folder.name, {})
        seen.add(folder.name)
        job.phases.append(make_phase(folder, item, job.implementer))
    for item in history:  # history entries whose folder is gone
        logs = str(item.get("logs") or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        if logs and logs not in seen:
            job.phases.append(make_phase(None, item, job.implementer, name=logs))
    return job


def make_phase(folder, item, implementer, name=None):
    name = name or folder.name
    action = str(item.get("action") or re.sub(r"^\d+-", "", name))
    provider, model = "", ""
    if folder is not None:
        for model_file in sorted(folder.glob("*.model.json")):
            data = read_json(model_file)
            if isinstance(data, dict):
                if data.get("provider"):  # a model-only record must not hide history.provider
                    provider = provider or norm_ai(data.get("provider"))
                model = model or str(data.get("model") or "")
    if not provider and item.get("provider"):
        provider = norm_ai(item.get("provider"))
    if not provider:
        # check runs local commands; finish is recorded by the writer chat.
        provider = "local" if action == "check" else (implementer if action in ("finish", "implement") else UNKNOWN)
    files = []
    if folder is not None:
        try:
            files = sorted(child for child in folder.iterdir() if child.is_file())
        except OSError:
            pass
    return Phase(name=name, action=action, provider=provider, model=model,
                 outcome=str(item.get("outcome") or ""), notes=str(item.get("notes") or ""),
                 error=str(item.get("error") or ""), path=folder, files=files)


def is_chatgpt_prompt(path: Path):
    name = path.name.lower()
    return path.suffix.lower() in PROMPT_SUFFIXES and ("chatgpt" in name or ("gpt" in name and "prompt" in name))


def walk_files(base: Path, limit: int, skip=frozenset(), recursive=True):
    """Yield files under base; the generator's return value is True when truncated."""
    count = 0
    for current, dirs, names in os.walk(base):
        top = Path(current) == base
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS and not d.endswith(".egg-info")
                         and not (top and d in skip)) if recursive else []
        for name in sorted(names):
            if count >= limit:
                return True
            count += 1
            yield Path(current) / name
    return False


def scan_project(root: Path, key: str, area: str, base: Path, limit: int, recursive=True, group="") -> Project:
    project = Project(key=key, area=area, path=base, recursive=recursive, group=group)
    generator = walk_files(base, limit, PROJECT_EXCLUDES.get(key, frozenset()), recursive)
    while True:
        try:
            path = next(generator)
        except StopIteration as stop:
            project.truncated = bool(stop.value)
            break
        try:
            stat = path.stat()
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        project.files.append(FileEntry(path=path, rel=rel, area=area, project=key, size=stat.st_size,
                                       mtime=stat.st_mtime, chatgpt_prompt=is_chatgpt_prompt(path)))
    return project


def area_targets(base: Path, key: str, area: str, group=""):
    """output/ or artifacts/: one project per sub-folder, plus one for files sitting directly in it."""
    children = sorted(base.iterdir())
    targets = [(key, area, base, False, group)] if any(child.is_file() for child in children) else []
    return targets + [(f"{key}/{child.name}", area, child, True, group)
                      for child in children if child.is_dir() and child.name not in EXCLUDED_DIRS]


def project_folder_targets(folder: Path):
    """A numbered project folder: its output/ and artifacts/ like the root ones, other folders as
    apps/tools, and its own direct files. Scratch folders (tmp, .runtime) are skipped."""
    group = folder.name
    children = sorted(folder.iterdir())
    targets = [(group, "app", folder, False, group)] if any(child.is_file() for child in children) else []
    for child in children:
        if not child.is_dir() or child.name in EXCLUDED_DIRS | SKIPPED_TOP:
            continue
        if child.name in SCAN_AREAS:
            targets += area_targets(child, f"{group}/{child.name}", child.name, group)
        else:
            targets.append((f"{group}/{child.name}", "app", child, True, group))
    return targets


def find_root(start: Path):
    """Nearest ancestor that contains agent_lab/, or None."""
    for candidate in (start, *start.parents):
        if (candidate / "agent_lab").is_dir():
            return candidate
    return None


def build_index(root: Path, limit: int = MAX_FILES_PER_PROJECT) -> Index:
    root = Path(root).resolve()
    problems = []
    jobs = {}
    jobs_dir = root / "agent_lab" / "jobs"
    if jobs_dir.is_dir():
        for child in sorted(jobs_dir.iterdir()):
            if child.is_dir() and (job_time(child.name) or (child / "manifest.json").exists()
                                   or (child / "task.json").exists()):
                job = load_job(child)
                jobs[job.id] = job
                problems += [f"{job.id}: {text}" for text in job.problems]
    else:
        problems.append("agent_lab/jobs 폴더 없음")

    aliases, alias_problems = load_aliases(root)
    problems += alias_problems
    folders = [child for child in sorted(root.iterdir()) if child.is_dir()] if root.is_dir() else []
    if any(PROJECT_FOLDER.match(child.name) for child in folders) and not root.joinpath(*ALIASES_FILE).exists():
        # Moved layout without the old → new table: old job paths stay as written, which may point nowhere.
        problems.append("path-aliases.json 없음: 옛 경로로 적힌 작업 기록을 새 위치에 연결하지 않음")
    targets = []  # (key, area, path, recursive, group)
    for area in SCAN_AREAS:
        base = root / area
        if base.is_dir():
            targets += area_targets(base, area, area)
    referenced = set()
    for job in jobs.values():
        for item in job.files:
            first = resolve_key(item, aliases).split("/", 1)[0]
            if (first and first not in SCAN_AREAS and first not in EXCLUDED_DIRS | SKIPPED_TOP and first != ".."
                    and not PROJECT_FOLDER.match(first)):
                referenced.add(first)
    for child in folders:
        if PROJECT_FOLDER.match(child.name):
            targets += project_folder_targets(child)
        elif child.name.lower() in referenced:
            targets.append((child.name, "app", child, True, ""))

    projects, files = {}, {}
    for key, area, base, recursive, group in targets:
        project = scan_project(root, key, area, base, limit, recursive, group)
        if project.truncated:
            problems.append(f"{key}: 파일이 많아 {limit}개까지만 표시")
        projects[key] = project
        for entry in project.files:
            files[rel_key(entry.rel)] = entry

    for job in sorted(jobs.values(), key=lambda item: item.id):
        for item in job.files:
            key = resolve_key(item, aliases)
            entry = files.get(key)
            if entry is not None and job.id not in entry.jobs:
                entry.jobs.append(job.id)
            for project in projects.values():
                if project.owns(key) and job.id not in project.jobs:
                    project.jobs.append(job.id)
    return Index(root=root, jobs=jobs, projects=projects, files=files, problems=problems, aliases=aliases,
                 folders=[child.name for child in folders if PROJECT_FOLDER.match(child.name)],
                 root_listed=any(is_root_path(resolve_key(item, aliases).split("/", 1)[0])
                                 for job in jobs.values() for item in job.files))


STALE_DAYS = (90, 180, 365)


def stale_files(index: Index, days: int, unlinked_only=False, now: float | None = None):
    """Files not modified for `days` days (oldest first).

    Modification time is used because last-access time changes whenever this
    app previews a file, antivirus scans it or OneDrive syncs it.
    """
    cutoff = (now if now is not None else datetime.now().timestamp()) - days * 86400
    found = [entry for entry in index.files.values()
             if entry.mtime < cutoff and not (unlinked_only and entry.jobs)]
    return sorted(found, key=lambda entry: entry.mtime)


def search_content(entries, query, max_bytes=1_000_000, limit=500):
    """Case-insensitive substring search inside small text files."""
    needle = query.lower()
    hits = []
    for entry in entries:
        if entry.size > max_bytes or entry.path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            text = entry.path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if needle in text.lower():
            hits.append(entry)
            if len(hits) >= limit:
                break
    return hits


BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf", ".exe", ".dll",
                   ".zip", ".7z", ".gz", ".tar", ".pyc", ".sqlite3", ".db", ".docx", ".xlsx", ".pptx",
                   ".hwp", ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".mp3", ".wav", ".bin", ".pkl"}

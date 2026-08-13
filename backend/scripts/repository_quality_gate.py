from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase" / "migrations"
ALLOWED_ENV_FILES = {
    "backend/.env.example",
    "frontend/.env.example",
    "KnowledgeBase/api-java-demo/chatdoc-api-java-demo/.env.example",
    "KnowledgeBase/api-python-demo/chatdoc-api-python-demo/.env.example",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "OpenAI-style token": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "JWT": re.compile(
        r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\b"
    ),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def check_dependency_lock() -> list[str]:
    requirements = ROOT / "backend" / "requirements.txt"
    development = ROOT / "backend" / "requirements-dev.txt"
    lock = ROOT / "backend" / "requirements.lock"
    if not lock.is_file():
        return ["backend/requirements.lock is missing"]

    lock_lines = [
        line.strip()
        for line in lock.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    failures = [
        f"unlocked dependency in backend/requirements.lock: {line}"
        for line in lock_lines
        if "==" not in line
    ]
    locked_names = {
        re.split(r"==", line, maxsplit=1)[0].lower().replace("_", "-")
        for line in lock_lines
    }
    direct_names: set[str] = set()
    for path in (requirements, development):
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("#", "-r")):
                continue
            name = re.split(r"[<>=!~\[]", line, maxsplit=1)[0]
            direct_names.add(name.lower().replace("_", "-"))
    for name in sorted(direct_names - locked_names):
        failures.append(f"direct backend dependency is absent from lock: {name}")
    return failures


def check_environment_files(files: list[Path]) -> list[str]:
    failures: list[str] = []
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if path.name.startswith(".env") and relative not in ALLOWED_ENV_FILES:
            failures.append(f"tracked environment file is forbidden: {relative}")
    return failures


def check_secrets(files: list[Path]) -> list[str]:
    failures: list[str] = []
    for path in files:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            match = pattern.search(content)
            if match:
                line = content.count("\n", 0, match.start()) + 1
                failures.append(
                    f"possible {label} in {path.relative_to(ROOT).as_posix()}:{line}"
                )
    return failures


def check_migrations() -> list[str]:
    failures: list[str] = []
    seen_versions: dict[str, str] = {}
    migrations = sorted(MIGRATIONS.glob("*.sql"))
    if not migrations:
        return ["no Supabase migrations found"]

    for path in migrations:
        match = re.match(r"^(\d+)_([a-z0-9_]+)\.sql$", path.name)
        if not match:
            failures.append(f"invalid migration filename: {path.name}")
            continue
        version = match.group(1)
        if version in seen_versions:
            failures.append(
                f"duplicate migration version {version}: {seen_versions[version]}, {path.name}"
            )
        seen_versions[version] = path.name
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            failures.append(f"empty migration: {path.name}")
        if re.search(r"disable\s+row\s+level\s+security", content, re.IGNORECASE):
            failures.append(f"migration disables RLS: {path.name}")
    return failures


def main() -> int:
    files = tracked_files()
    failures = [
        *check_environment_files(files),
        *check_secrets(files),
        *check_dependency_lock(),
        *check_migrations(),
    ]
    if failures:
        print("Repository quality gate failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(
        f"Repository quality gate passed: {len(files)} repository files, "
        f"{len(list(MIGRATIONS.glob('*.sql')))} migrations checked."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

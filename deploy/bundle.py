"""Build a Linux migration bundle, or a code-only update, without Windows runtimes."""
from __future__ import annotations

import argparse
import tarfile
from pathlib import Path


def create_bundle(root: Path, output: Path, with_state: bool = False) -> int:
    excluded_dirs = {".git", ".git.bak", ".venv", "__pycache__", ".pytest_cache", "node_modules",
                     "logs", "cache", "image_cache"}
    state_dirs = {"config", "data", "rag_data", "memory"}
    state_suffixes = {".json", ".yaml", ".yml", ".db", ".sqlite", ".sqlite3", ".bin"}
    excluded_suffixes = {".pyc", ".pyo", ".pyd", ".exe", ".dll", ".bat", ".log"}
    roots = [root / "plugins", root / "deploy"]
    if with_state:
        roots.extend(root / name for name in ("data", "memory"))
    files = [p for p in root.iterdir() if p.suffix == ".py" or p.name in
             {"requirements.txt", "README.md", "LICENSE", "as812.png"}]
    if with_state and (root / "config.yaml").is_file():
        files.append(root / "config.yaml")
    for directory in roots:
        if directory.is_dir():
            files.extend(directory.rglob("*"))
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(output, "w:gz") as archive:
        for path in sorted(files):
            relative = path.relative_to(root)
            if path.is_symlink() or not path.is_file() or path.resolve() == output:
                continue
            if excluded_dirs.intersection(relative.parts) or path.suffix in excluded_suffixes:
                continue
            if path.name == ".env" or path.name.startswith(".env."):
                continue
            if not with_state:
                if state_dirs.intersection(relative.parts) or path.name == "config.toml":
                    continue
                template = (path.name.endswith(".example.json") or "assets" in relative.parts
                            or path.name == "package.json")
                if not template and (path.suffix in state_suffixes or
                                     path.name.endswith((".db-wal", ".db-shm", "-journal"))):
                    continue
            archive.add(path, arcname=relative.as_posix(), recursive=False)
            count += 1
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--with-state", action="store_true",
                        help="Initial migration only: include private config and runtime data; stop bot first")
    args = parser.parse_args()
    count = create_bundle(args.root.resolve(), args.output, args.with_state)
    print(f"Packed {count} files into {args.output}")

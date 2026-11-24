"""File-system agent, confined to the user's folders (settings.file_roots).

Moves/renames/new folders are reversible (undo). Deleting goes to the Recycle Bin and needs approval.
Bulk changes: the agent is told to present a dry-run plan first.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import fnmatch
import os
import shutil
from pathlib import Path

from ..safety.policy import Risk, wrap_untrusted
from .registry import S, Tool, ToolResult

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css", ".xml", ".yaml", ".yml",
            ".log", ".ini", ".cfg", ".toml", ".sql", ".bat", ".ps1"}


class PathNotAllowed(Exception):
    pass


def resolve(path: str, roots: list[str]) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.is_absolute():
        p = Path(roots[0]) / p
    p = p.resolve()
    for r in roots:
        try:
            p.relative_to(Path(r).resolve())
            return p
        except ValueError:
            continue
    raise PathNotAllowed(f"{p} is outside the folders JARVIS may touch: {roots}")


def register(svc) -> None:
    reg = svc.registry
    roots = lambda: svc.settings.file_roots  # noqa: E731

    def th(fn):
        async def run(a):
            try:
                return await asyncio.to_thread(fn, a)
            except PathNotAllowed as e:
                return ToolResult(str(e), is_error=True)
        return run

    def list_dir(a):
        p = resolve(a.get("path") or roots()[0], roots())
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = []
        for x in items[:300]:
            st = x.stat()
            kind = "dir " if x.is_dir() else f"{st.st_size:>9,}B"
            lines.append(f"{kind} {dt.datetime.fromtimestamp(st.st_mtime):%Y-%m-%d} {x.name}")
        return f"{p} ({len(items)} items)\n" + "\n".join(lines)
    reg.register(Tool("list_folder", f"List a folder. Allowed roots: Desktop, Documents, Downloads, Pictures, "
                      f"Music, Videos. Relative paths start at the Desktop.",
                      {"path": S("string", "Folder path, e.g. Desktop or C:/Users/.../Documents/Projects")},
                      th(list_dir), required=[], category="files"))

    def search(a):
        pattern = a["pattern"]
        if not any(c in pattern for c in "*?"):
            pattern = f"*{pattern}*"
        base = resolve(a.get("folder") or roots()[0], roots()) if a.get("folder") else None
        bases = [base] if base else [Path(r) for r in roots() if Path(r).exists()]
        hits = []
        for b in bases:
            for dirpath, dirnames, files in os.walk(b):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", ".venv")]
                for f in files:
                    if fnmatch.fnmatch(f.lower(), pattern.lower()):
                        hits.append(os.path.join(dirpath, f))
                        if len(hits) >= 50:
                            return "\n".join(hits) + "\n(first 50 matches)"
        return "\n".join(hits) or "No files match."
    reg.register(Tool("search_files", "Find files by name pattern (e.g. '*.pdf', 'invoice').",
                      {"pattern": S("string", ""), "folder": S("string", "Optional folder to search in.")},
                      th(search), required=["pattern"], timeout=60, category="files"))

    def read(a):
        p = resolve(a["path"], roots())
        if p.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader
                text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages[:30])
            except ImportError:
                return ToolResult("PDF reading needs the pypdf package.", is_error=True)
        elif p.suffix.lower() in TEXT_EXT or p.stat().st_size < 200_000:
            text = p.read_text("utf-8", errors="replace")
        else:
            return ToolResult(f"{p.name} is not a text file I can read.", is_error=True)
        return ToolResult(wrap_untrusted(text[:20000], f"file {p}"), sources=[f"file:{p}"])
    reg.register(Tool("read_file", "Read a text/markdown/csv/code/PDF file.", {"path": S("string", "")},
                      th(read), category="files"))

    def write(a):
        p = resolve(a["path"], roots())
        if p.exists():
            return ToolResult(f"{p} already exists; choose another name (I don't overwrite files).", is_error=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(a["content"], "utf-8")
        return ToolResult(f"Created {p}.", undo=("file_create", {"path": str(p)}))
    reg.register(Tool("create_file", "Create a new text/markdown/csv file (never overwrites).",
                      {"path": S("string", ""), "content": S("string", "")}, th(write), Risk.LOCAL,
                      summarize=lambda a: f"create file {a['path']}", category="files"))

    def move(a):
        src, dst = resolve(a["source"], roots()), resolve(a["destination"], roots())
        if dst.is_dir():
            dst = dst / src.name
        if dst.exists():
            return ToolResult(f"{dst} already exists; not overwriting.", is_error=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return ToolResult(f"Moved {src} -> {dst}.", undo=("file_move", {"from": str(dst), "to": str(src)}))
    reg.register(Tool("move_file", "Move or rename a file/folder. For more than a few files, first present the "
                      "plan to the user (dry run) and proceed only when they agree.",
                      {"source": S("string", ""), "destination": S("string", "Folder or new path")},
                      th(move), Risk.LOCAL, summarize=lambda a: f"move {a['source']} to {a['destination']}",
                      category="files"))

    def mkdir(a):
        p = resolve(a["path"], roots())
        if p.exists():
            return "Folder already exists."
        p.mkdir(parents=True)
        return ToolResult(f"Created folder {p}.", undo=("folder_create", {"path": str(p)}))
    reg.register(Tool("create_folder", "Create a folder.", {"path": S("string", "")}, th(mkdir), Risk.LOCAL,
                      category="files"))

    def recycle(a):
        from send2trash import send2trash
        p = resolve(a["path"], roots())
        send2trash(str(p))
        return f"Moved {p.name} to the Recycle Bin (restore it from there if needed)."
    reg.register(Tool("delete_to_recycle_bin", "Delete a file/folder by moving it to the Recycle Bin. Always needs "
                      "approval.", {"path": S("string", "")}, th(recycle), Risk.DANGEROUS,
                      summarize=lambda a: f"delete {a['path']} (to Recycle Bin)", category="files"))

    async def undo_move(p):
        await asyncio.to_thread(shutil.move, p["from"], p["to"])
        return "File moved back."

    async def undo_create_file(p):
        from send2trash import send2trash
        await asyncio.to_thread(send2trash, p["path"])
        return "File sent to Recycle Bin."

    async def undo_mkdir(p):
        try:
            os.rmdir(p["path"])
            return "Folder removed."
        except OSError:
            return "The folder isn't empty any more, so I left it."
    reg.register_undo("file_move", undo_move)
    reg.register_undo("file_create", undo_create_file)
    reg.register_undo("folder_create", undo_mkdir)

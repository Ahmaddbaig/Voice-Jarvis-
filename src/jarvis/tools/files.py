"""File I/O tools — read, write, delete, search.

ACT-FILE-01..05: Five tools for filesystem interaction within allow-listed
directories.  Every tool validates paths via ``check_file_access`` before
performing any I/O.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf4llm
import send2trash

from jarvis.tools._registry import tool, mark_external_content
from jarvis.core.file_access import check_file_access


@tool(tier=0)
def read_file(path: str) -> str:
    '''Read a text, markdown, or code file and return its contents.

    Args:
        path: Absolute or relative file path to read.
    '''
    check_file_access(path)
    resolved = Path(path).resolve()

    try:
        text = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = resolved.read_text(encoding="latin-1")

    mark_external_content()
    return text


@tool(tier=0)
def read_pdf(path: str) -> str:
    '''Read a PDF file and return its contents as markdown for summarization.

    Args:
        path: Absolute or relative path to a PDF file.
    '''
    check_file_access(path)
    resolved = Path(path).resolve()

    if not resolved.exists():
        return f"[error] File not found: {resolved}"
    if not resolved.suffix.lower() == ".pdf":
        return f"[error] Not a PDF file: {resolved}"

    md = pymupdf4llm.to_markdown(str(resolved))
    mark_external_content()
    return md


@tool(tier=2)
def write_file(path: str, content: str) -> str:
    '''Write text content to a file. Creates the file if it does not exist, overwrites if it does.

    Args:
        path: Absolute or relative file path to write.
        content: The text content to write to the file.
    '''
    check_file_access(path)
    resolved = Path(path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"Written {len(content)} chars to {resolved}"


@tool(tier=2)
def delete_file(path: str) -> str:
    '''Delete a file by sending it to the Recycle Bin (recoverable).

    Args:
        path: Absolute or relative file path to delete.
    '''
    check_file_access(path)
    resolved = Path(path).resolve()

    if not resolved.exists():
        return f"[error] File not found: {resolved}"

    send2trash.send2trash(str(resolved))
    return f"Sent to Recycle Bin: {resolved}"


@tool(tier=0)
def search_files(directory: str, pattern: str) -> str:
    '''Search for files matching a glob pattern within an allow-listed directory.

    Args:
        directory: Directory to search in.
        pattern: Glob pattern to match (e.g. "*.txt", "report*", "**/*.pdf").
    '''
    check_file_access(directory)
    resolved = Path(directory).resolve()

    if not resolved.is_dir():
        return f"[error] Not a directory: {resolved}"

    matches: list[str] = []
    for hit in resolved.glob(pattern):
        # Limit depth to 3 levels when not using recursive glob
        try:
            rel = hit.relative_to(resolved)
        except ValueError:
            continue
        if len(rel.parts) > 3 and not pattern.startswith("**"):
            continue
        matches.append(str(rel))
        if len(matches) >= 50:
            break

    if not matches:
        return f"No files found matching '{pattern}' in {directory}"

    return "\n".join(matches)

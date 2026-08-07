from __future__ import annotations

import os
import re
from pathlib import Path

import base64
from html import escape

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def normalize_output_filename(
    raw_title: str | None,
    *,
    default: str = "pulse_program",
) -> str:
    """
    Convert a user-provided title into a safe local filename.

    A file extension is not forced because Bruker pulse programs may
    intentionally be saved without an extension.
    """
    filename = (raw_title or "").strip()

    if not filename:
        filename = default

    filename = _INVALID_FILENAME_CHARS.sub("_", filename)
    filename = filename.strip(" .")

    if not filename or filename in {".", ".."}:
        filename = default

    stem = Path(filename).stem.upper()

    if stem in _WINDOWS_RESERVED_NAMES:
        filename = f"_{filename}"

    return filename


def find_project_root(
    start: str | Path | None = None,
) -> Path:
    """
    Find the nearest parent directory containing pyproject.toml.
    """
    current = Path(start or __file__).resolve()

    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate

    return Path.cwd().resolve()


def get_default_local_output_dir() -> Path:
    """
    Return the default local output directory.

    The NMRPAINT_OUTPUT_DIR environment variable may override it.
    """
    override = os.environ.get("NMRPAINT_OUTPUT_DIR")

    if override:
        return Path(override).expanduser().resolve()

    return find_project_root() / "output"


def write_text_file(
    path: str | Path,
    content: str,
) -> Path:
    """
    Write UTF-8 text to an explicit local path.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:
        file.write(content)

    return output_path


def save_text_local(
    *,
    content: str,
    filename: str,
    output_dir: str | Path | None = None,
) -> Path:
    """
    Save text in the local NMRpaint output directory.
    """
    safe_filename = normalize_output_filename(filename)

    destination = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else get_default_local_output_dir()
    )

    destination.mkdir(parents=True, exist_ok=True)

    return write_text_file(
        path=destination / safe_filename,
        content=content,
    )


def build_text_download_href(content: str) -> str:
    encoded_content = base64.b64encode(
        content.encode("utf-8")
    ).decode("ascii")

    return (
        "data:application/octet-stream;base64,"
        f"{encoded_content}"
    )

def build_text_download_link_html(
    *,
    content: str,
    filename: str,
    label: str = "Download pulse program",
) -> str:
    """
    Build an HTML download link for text content.

    The returned HTML can be displayed using ipywidgets.HTML.
    """
    safe_filename = normalize_output_filename(filename)
    safe_label = escape(label)
    escaped_filename = escape(
        safe_filename,
        quote=True,
    )

    href = build_text_download_href(content)

    return (
        f'<a href="{href}" '
        f'download="{escaped_filename}" '
        'style="'
        'display:inline-block;'
        'padding:6px 12px;'
        'border:1px solid #777;'
        'border-radius:4px;'
        'text-decoration:none;'
        'font-weight:500;'
        '">'
        f"{safe_label}"
        "</a>"
    )

def build_png_download_href(
    png_bytes: bytes,
) -> str:
    """
    Build a browser download href for PNG bytes.
    """
    encoded_content = base64.b64encode(
        png_bytes
    ).decode("ascii")

    return (
        "data:image/png;base64,"
        f"{encoded_content}"
    )


def build_png_download_link_html(
    *,
    png_bytes: bytes,
    filename: str,
    label: str = "Download PNG",
) -> str:
    """
    Build an HTML download link for PNG content.
    """
    safe_filename = normalize_output_filename(
        filename,
        default="canvas",
    )

    if not safe_filename.lower().endswith(".png"):
        safe_filename += ".png"

    safe_label = escape(label)
    escaped_filename = escape(
        safe_filename,
        quote=True,
    )

    href = build_png_download_href(png_bytes)

    return (
        f'<a href="{href}" '
        f'download="{escaped_filename}" '
        'style="'
        'display:inline-block;'
        'padding:6px 12px;'
        'border:1px solid #777;'
        'border-radius:4px;'
        'text-decoration:none;'
        'font-weight:500;'
        '">'
        f"{safe_label}"
        "</a>"
    )
    

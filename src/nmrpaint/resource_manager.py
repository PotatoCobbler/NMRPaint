from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Iterable


_RESOURCE_PACKAGE = "nmrpaint.resources"


def resource_root():
    """Return the root Traversable object for packaged NMRpaint resources."""
    return files(_RESOURCE_PACKAGE)


def resource_path(*parts: str):
    """
    Return a Traversable resource location.

    This may represent a real filesystem path or a packaged resource.
    """
    resource = resource_root()

    for part in parts:
        resource = resource.joinpath(part)

    return resource


def resource_exists(*parts: str) -> bool:
    """Return True when the requested packaged resource exists."""
    return resource_path(*parts).is_file()


def resource_directory_exists(*parts: str) -> bool:
    """Return True when the requested packaged resource directory exists."""
    return resource_path(*parts).is_dir()


def read_resource_text(*parts: str, encoding: str = "utf-8") -> str:
    """Read a packaged UTF-8 text resource."""
    resource = resource_path(*parts)

    if not resource.is_file():
        joined = "/".join(parts)
        raise FileNotFoundError(f"NMRpaint resource not found: {joined}")

    return resource.read_text(encoding=encoding)


def list_resource_names(
    *parts: str,
    suffix: str | None = None,
) -> list[str]:
    """List filenames inside a packaged resource directory."""
    directory = resource_path(*parts)

    if not directory.is_dir():
        joined = "/".join(parts)
        raise FileNotFoundError(
            f"NMRpaint resource directory not found: {joined}"
        )

    names: list[str] = []

    for item in directory.iterdir():
        if not item.is_file():
            continue

        if suffix is not None and not item.name.lower().endswith(
            suffix.lower()
        ):
            continue

        names.append(item.name)

    return sorted(names)


def iter_resource_files(
    *parts: str,
    suffix: str | None = None,
):
    """Yield packaged file resources inside a directory."""
    directory = resource_path(*parts)

    if not directory.is_dir():
        return

    for item in sorted(directory.iterdir(), key=lambda value: value.name):
        if not item.is_file():
            continue

        if suffix is not None and not item.name.lower().endswith(
            suffix.lower()
        ):
            continue

        yield item
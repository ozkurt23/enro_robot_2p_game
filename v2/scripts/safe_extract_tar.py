#!/usr/bin/env python3
"""Safely extract the pinned llama.cpp tarball under one expected root."""

from __future__ import annotations

import argparse
import os
import tarfile
from pathlib import Path, PurePosixPath


class UnsafeArchive(ValueError):
    pass


def _normalized_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\x00" in name:
        raise UnsafeArchive(f"güvenli olmayan arşiv yolu: {name!r}")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts:
        raise UnsafeArchive(f"boş arşiv yolu: {name!r}")
    return PurePosixPath(*parts)


def _link_stays_inside(member_path: PurePosixPath, link_name: str, expected_root: str) -> None:
    link = PurePosixPath(link_name)
    if link.is_absolute() or "\x00" in link_name:
        raise UnsafeArchive(f"absolute link hedefi: {link_name!r}")
    if link.parts and link.parts[0] == expected_root:
        candidate = link
    else:
        candidate = member_path.parent / link
    stack: list[str] = []
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not stack:
                raise UnsafeArchive(f"dışarı taşan link hedefi: {link_name!r}")
            stack.pop()
        else:
            stack.append(part)
    if not stack or stack[0] != expected_root:
        raise UnsafeArchive(f"beklenen kökün dışına link: {link_name!r}")


def extract_verified_archive(archive: Path, destination: Path, expected_root: str) -> Path:
    if not archive.is_file():
        raise UnsafeArchive(f"arşiv bulunamadı: {archive}")
    if not destination.is_dir():
        raise UnsafeArchive(f"hedef dizin bulunamadı: {destination}")
    if any(destination.iterdir()):
        raise UnsafeArchive(f"extract hedefi boş değil: {destination}")
    if PurePosixPath(expected_root).name != expected_root or expected_root in {".", ".."}:
        raise UnsafeArchive("expected root tek güvenli yol bileşeni olmalı")

    with tarfile.open(archive, mode="r:gz") as bundle:
        members = bundle.getmembers()
        if not members:
            raise UnsafeArchive("arşiv boş")
        for member in members:
            path = _normalized_member(member.name)
            if path.parts[0] != expected_root:
                raise UnsafeArchive(
                    f"beklenmeyen arşiv kökü: {member.name!r}; beklenen={expected_root!r}"
                )
            if member.ischr() or member.isblk() or member.isfifo():
                raise UnsafeArchive(f"device/FIFO üyesi kabul edilmez: {member.name!r}")
            if member.issym() or member.islnk():
                _link_stays_inside(path, member.linkname, expected_root)

        # Python 3.12's data filter rejects absolute paths, traversal, devices,
        # unsafe link targets, and surprising ownership/mode metadata again at
        # extraction time. The checks above also enforce our single-root layout.
        bundle.extractall(destination, members=members, filter="data")

    root = destination / expected_root
    if not root.is_dir():
        raise UnsafeArchive(f"extract edilen kök bulunamadı: {root}")
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("expected_root")
    args = parser.parse_args()
    try:
        root = extract_verified_archive(
            args.archive.resolve(), args.destination.resolve(), args.expected_root
        )
    except (OSError, tarfile.TarError, UnsafeArchive) as exc:
        parser.error(str(exc))
    print(os.fspath(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

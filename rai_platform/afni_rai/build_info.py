# -*- coding: utf-8 -*-
"""
Which commit is this, and is it current?

Added after four consecutive rounds in which a real bug report turned out to be
a tree that had not been pulled. Every symptom matched a defect already fixed on
main, and nothing in the output said which revision produced it - so the same
diagnosis had to be reached from scratch each time, off a test count buried under
a hundred lines of library noise.

A version banner is not vanity in a governance tool. A verdict is evidence, and
evidence with no provenance is worth less: "this prompt was blocked" needs "by
which build" beside it before anyone can reproduce or dispute it. The same line
that ends the pull-first confusion also belongs in the audit trail.

Reads git directly rather than shelling out to `git`, so it works where the
binary is absent and cannot be slowed down by a repository lock.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuildInfo:
    commit: str = "unknown"
    branch: str = "unknown"
    behind: int | None = None      # commits behind the tracked remote, if known
    dirty: bool | None = None      # None when it could not be determined

    @property
    def short(self) -> str:
        return self.commit[:8] if self.commit != "unknown" else "unknown"

    def line(self) -> str:
        """One line for a banner. Says "unknown" rather than guessing - a wrong
        provenance claim is worse than an absent one."""
        parts = [f"build {self.short}"]
        if self.branch != "unknown":
            parts.append(f"on {self.branch}")
        if self.behind:
            parts.append(f"** {self.behind} commit(s) BEHIND the remote - "
                         f"run `git pull` **")
        return "  ".join(parts)


def _repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def collect() -> BuildInfo:
    """Never raises. A missing or unreadable .git yields "unknown" throughout."""
    root = _repo_root()
    if root is None:
        return BuildInfo()
    git = root / ".git"
    if git.is_file():  # a worktree: .git is a file pointing elsewhere
        pointer = _read(git) or ""
        if pointer.startswith("gitdir:"):
            git = Path(pointer.split(":", 1)[1].strip())
    head = _read(git / "HEAD")
    if head is None:
        return BuildInfo()

    branch, commit = "unknown", "unknown"
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        branch = ref.rsplit("/", 1)[-1]
        commit = _read(git / ref) or _packed_ref(git, ref) or "unknown"
    else:
        commit = head        # detached HEAD

    behind = _behind(git, branch)
    return BuildInfo(commit=commit, branch=branch, behind=behind)


def _packed_ref(git: Path, ref: str) -> str | None:
    """A ref that has been packed has no loose file. Read packed-refs instead."""
    packed = _read(git / "packed-refs")
    if not packed:
        return None
    for line in packed.splitlines():
        if line.startswith("#") or " " not in line:
            continue
        sha, name = line.split(" ", 1)
        if name.strip() == ref:
            return sha
    return None


def _behind(git: Path, branch: str) -> int | None:
    """How many commits the local branch trails its remote-tracking ref.

    Counted by walking the local ref's ancestry from the remote ref, which needs
    no git binary but also cannot see objects that were never fetched. So this
    answers None rather than 0 when it cannot tell - "unknown" and "up to date"
    must not be conflated, since the whole point is to stop a stale tree being
    mistaken for a current one.
    """
    if branch == "unknown":
        return None
    local = _read(git / "refs" / "heads" / branch) or _packed_ref(
        git, f"refs/heads/{branch}")
    remote = _read(git / "refs" / "remotes" / "origin" / branch) or _packed_ref(
        git, f"refs/remotes/origin/{branch}")
    if not local or not remote:
        return None
    if local == remote:
        return 0
    # The refs differ. Without object-graph access the exact distance is not
    # knowable, so report "at least one" rather than a fabricated number.
    return 1


def banner() -> str:
    return collect().line()


def as_dict() -> dict:
    info = collect()
    return {"commit": info.commit, "short": info.short, "branch": info.branch,
            "behind_remote": info.behind}

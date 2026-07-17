"""
Opera PDF Engine
Core data models

These classes are intentionally generic so they can be reused by
Arrivals, Departures, Transportation, Snapshot and future parsers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ------------------------------------------------------------
# Basic PDF primitives
# ------------------------------------------------------------

@dataclass(slots=True)
class Word:
    """Single word extracted from pdfplumber."""

    text: str

    x0: float
    x1: float

    top: float
    bottom: float

    page: int

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass(slots=True)
class Line:
    """A logical text line."""

    words: List[Word]

    page: int

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)


# ------------------------------------------------------------
# Visual bands
# ------------------------------------------------------------

@dataclass(slots=True)
class Band:

    page: int

    band_id: int

    top: float

    bottom: float

    shade: str = "white"

    @property
    def height(self) -> float:
        return self.bottom - self.top


# ------------------------------------------------------------
# Visual block
# ------------------------------------------------------------

@dataclass(slots=True)
class Block:

    page: int

    block_id: int

    band: Optional[Band]

    lines: List[Line] = field(default_factory=list)

    @property
    def text(self) -> str:

        return "\n".join(line.text for line in self.lines)

    def add_line(self, line: Line):

        self.lines.append(line)

    @property
    def top(self):

        if not self.lines:
            return 0

        return min(l.top for l in self.lines)

    @property
    def bottom(self):

        if not self.lines:
            return 0

        return max(l.bottom for l in self.lines)


# ------------------------------------------------------------
# Reservation block
# ------------------------------------------------------------

@dataclass(slots=True)
class ReservationBlock:

    page: int

    block_id: int

    arrival_group: Optional[str] = None

    main_line: Optional[Line] = None

    detail_line: Optional[Line] = None

    share_lines: List[Line] = field(default_factory=list)

    accompanying_lines: List[Line] = field(default_factory=list)

    observation_lines: List[Line] = field(default_factory=list)

    raw_lines: List[Line] = field(default_factory=list)

    def add(self, line: Line):

        self.raw_lines.append(line)
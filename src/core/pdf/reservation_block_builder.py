from __future__ import annotations

"""Build reservation-level records from generic OPERA PDF blocks.

This module intentionally sits between ``PdfEngine`` and report parsers.

``PdfEngine`` detects words, lines, visual bands, and generic blocks.
``ReservationBlockBuilder`` applies OPERA reservation-report rules and turns
those generic lines into one logical ``ReservationBlock`` per reservation.

The initial profile targets ODATA Arrivals Detail reports. The design keeps
classification methods overridable so departures and transportation profiles
can reuse the same state machine later.
"""

from dataclasses import fields, is_dataclass
from datetime import datetime
import inspect
import re
from typing import Any, Iterable, Iterator, Mapping, Sequence

from src.core.pdf.models import Line, ReservationBlock


class ReservationBlockBuilderError(RuntimeError):
    """Raised when reservation blocks cannot be built safely."""


class ReservationBlockBuilder:
    """Convert generic PDF lines into OPERA reservation blocks.

    Parameters
    ----------
    strict:
        When ``True``, incomplete reservations raise an exception. When
        ``False`` (default), incomplete candidates are retained with their raw
        lines so they remain visible in diagnostics.
    """

    DATE_PATTERN = r"\d{2}-\d{2}-\d{2}"
    DATE_RE = re.compile(rf"^{DATE_PATTERN}$")
    ARRIVAL_GROUP_RE = re.compile(
        rf"^Arrival\s+Date\s+(?P<date>{DATE_PATTERN})$",
        re.IGNORECASE,
    )
    RESERVATION_START_RE = re.compile(
        rf"""
        ^\s*
        (?P<room>\d{{1,5}}|[A-Z][A-Z0-9-]{{0,8}})
        \s+
        (?P<guest>.+?)
        \s+
        (?P<arr>{DATE_PATTERN})
        \s+
        (?P<dep>{DATE_PATTERN})
        \s+
        (?P<tail>.+)
        $
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    DETAIL_START_RE = re.compile(r"^\s*\d{6,}\b")
    TOTAL_RE = re.compile(
        r"^(Arrival\s+Date\s+Total|Grand\s+Total)\b",
        re.IGNORECASE,
    )

    ACCOMPANYING_RE = re.compile(
        r"^Accompanying\s+Names?\s*:",
        re.IGNORECASE,
    )
    SHARE_RE = re.compile(
        r"^(Share\s+With|Sharers?|Sharing\s+With)\s*:",
        re.IGNORECASE,
    )
    OBSERVATION_RE = re.compile(
        r"^(Comments?|Notes?|Remarks?|Observations?|Preferences?|"
        r"Special\s+Requests?|Transportation|Traces?)\s*:",
        re.IGNORECASE,
    )

    HEADER_PREFIXES = (
        "sandy lane hotel",
        "odata_arr_detail",
        "room name company",
        "no. travel agent",
        "conf no. vip",
        "room # of arrival",
    )
    FOOTER_PREFIXES = (
        "filter arrival from date",
        "room class all",
        "market code all",
        "from arrival time",
        "include checked-in",
        "room assignment all reservations",
    )
    STANDALONE_HEADERS = {
        "source",
    }

    def __init__(self, *, strict: bool = False) -> None:
        self.strict = bool(strict)
        self.warnings: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_from_engine(self, engine: Any) -> list[ReservationBlock]:
        """Build reservations directly from a ``PdfEngine`` instance."""
        if not hasattr(engine, "blocks"):
            raise TypeError("engine must provide a blocks() method")
        return self.build(engine.blocks())

    def build(self, blocks: Iterable[Any]) -> list[ReservationBlock]:
        """Build reservation blocks from typed or dictionary-like blocks."""
        self.warnings = []

        logical: list[ReservationBlock] = []
        current: _Candidate | None = None
        arrival_group = ""
        next_block_id = 1

        for source_block in self._ordered_blocks(blocks):
            page = self._block_page(source_block)
            source_block_id = self._block_id(source_block)

            print()
            print("=" * 100)
            print(f"SOURCE BLOCK={source_block_id} PAGE={page}")
            print("=" * 100)
            for l in self._block_lines(source_block):
                print(self._line_text(l))
            print()

            # original page/block assignment removed below
            page = self._block_page(source_block)
            source_block_id = self._block_id(source_block)

            for line in self._block_lines(source_block):
                text = self._line_text(line)

                if not text:
                    continue

                group_match = self.ARRIVAL_GROUP_RE.match(text)
                if group_match:
                    print()
                    print(f">>> ARRIVAL GROUP FOUND: {group_match.group('date')}")
                    if current is not None:
                        logical.append(
                            self._finalize(
                                current,
                                logical_block_id=next_block_id,
                            )
                        )
                        next_block_id += 1
                        current = None

                    arrival_group = self._normalize_date(
                        group_match.group("date")
                    )
                    print(f">>> NORMALIZED: {arrival_group}")
                    print()
                    continue

                if self._is_noise(text):
                    if current is not None and self._is_footer(text):
                        logical.append(
                            self._finalize(
                                current,
                                logical_block_id=next_block_id,
                            )
                        )
                        next_block_id += 1
                        current = None
                    continue

                if self._is_total(text):
                    if current is not None:
                        logical.append(
                            self._finalize(
                                current,
                                logical_block_id=next_block_id,
                            )
                        )
                        next_block_id += 1
                        current = None
                    continue

                if self._is_reservation_start(text):
                    if current is not None:
                        logical.append(
                            self._finalize(
                                current,
                                logical_block_id=next_block_id,
                            )
                        )
                        next_block_id += 1

                    print(f"START RESERVATION -> ArrivalGroup={arrival_group}")
                    print(text)

                    current = _Candidate(
                        page=page,
                        source_block_id=source_block_id,
                        arrival_group=arrival_group,
                        main_line=line,
                        raw_lines=[line],
                    )
                    continue

                if current is None:
                    self._warn(
                        "orphan_line",
                        page=page,
                        source_block_id=source_block_id,
                        text=text,
                    )
                    continue

                current.raw_lines.append(line)

                if self._is_accompanying(text):
                    current.accompanying_lines.append(line)
                elif self._is_share(text):
                    current.share_lines.append(line)
                elif self._is_observation(text):
                    current.observation_lines.append(line)
                elif current.detail_line is None and self._is_detail_start(text):
                    current.detail_line = line
                else:
                    current.continuation_lines.append(line)

        if current is not None:
            logical.append(
                self._finalize(
                    current,
                    logical_block_id=next_block_id,
                )
            )

        return logical

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _is_reservation_start(self, text: str) -> bool:
        """Return whether a line has the Arrivals main-row structure."""
        match = self.RESERVATION_START_RE.match(text)
        if not match:
            return False

        tail = match.group("tail").split()
        # The tail normally contains room type, adults, children, rooms,
        # market, source, and reservation status. Requiring at least four
        # tokens avoids treating titles or totals as reservations.
        return len(tail) >= 4

    def _is_detail_start(self, text: str) -> bool:
        return self.DETAIL_START_RE.match(text) is not None

    def _is_accompanying(self, text: str) -> bool:
        return self.ACCOMPANYING_RE.match(text) is not None

    def _is_share(self, text: str) -> bool:
        return self.SHARE_RE.match(text) is not None

    def _is_observation(self, text: str) -> bool:
        return self.OBSERVATION_RE.match(text) is not None

    def _is_total(self, text: str) -> bool:
        return self.TOTAL_RE.match(text) is not None

    def _is_header(self, text: str) -> bool:
        normalized = text.casefold().strip()

        if normalized in self.STANDALONE_HEADERS:
            return True

        if any(normalized.startswith(prefix) for prefix in self.HEADER_PREFIXES):
            return True

        # OPERA prints the report generation time by itself.
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
            return True

        return False

    def _is_footer(self, text: str) -> bool:
        normalized = text.casefold().strip()
        return any(
            normalized.startswith(prefix)
            for prefix in self.FOOTER_PREFIXES
        )

    def _is_noise(self, text: str) -> bool:
        return self._is_header(text) or self._is_footer(text)

    # ------------------------------------------------------------------
    # Candidate finalization
    # ------------------------------------------------------------------

    def _finalize(
        self,
        candidate: "_Candidate",
        *,
        logical_block_id: int,
    ) -> ReservationBlock:
        if candidate.detail_line is None:
            self._warn(
                "missing_detail_line",
                page=candidate.page,
                source_block_id=candidate.source_block_id,
                text=self._line_text(candidate.main_line),
            )
            if self.strict:
                raise ReservationBlockBuilderError(
                    "Reservation candidate is missing its detail line: "
                    f"{self._line_text(candidate.main_line)}"
                )

        values = {
            "page": candidate.page,
            "block_id": logical_block_id,
            "arrival_group": candidate.arrival_group,
            "main_line": candidate.main_line,
            "detail_line": candidate.detail_line,
            "share_lines": list(candidate.share_lines),
            "accompanying_lines": list(candidate.accompanying_lines),
            "observation_lines": list(candidate.observation_lines),
            "continuation_lines": list(candidate.continuation_lines),
            "raw_lines": list(candidate.raw_lines),
            "source_block_id": candidate.source_block_id,
        }

        print(
            f"FINALIZE -> Block={logical_block_id} ArrivalGroup={candidate.arrival_group}"
        )
        print(self._line_text(candidate.main_line))
        return self._construct_reservation_block(values)

    @staticmethod
    def _construct_reservation_block(
        values: Mapping[str, Any],
    ) -> ReservationBlock:
        """Instantiate the project's model while tolerating model evolution.

        Only constructor fields currently defined by ``ReservationBlock`` are
        passed. This allows the model to gain optional fields without forcing
        this builder and older branches to change simultaneously.
        """
        try:
            signature = inspect.signature(ReservationBlock)
            accepted = {
                name
                for name, parameter in signature.parameters.items()
                if name != "self"
                and parameter.kind
                in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                )
            }
        except (TypeError, ValueError):
            accepted = set(values)

        if is_dataclass(ReservationBlock):
            accepted = {field.name for field in fields(ReservationBlock)}

        kwargs = {
            key: value
            for key, value in values.items()
            if key in accepted
        }

        try:
            return ReservationBlock(**kwargs)
        except TypeError as exc:
            raise ReservationBlockBuilderError(
                "ReservationBlock model is not compatible with the builder. "
                f"Accepted fields: {sorted(accepted)}; supplied fields: "
                f"{sorted(kwargs)}"
            ) from exc

    # ------------------------------------------------------------------
    # Generic block/line adapters
    # ------------------------------------------------------------------

    @classmethod
    def _ordered_blocks(cls, blocks: Iterable[Any]) -> list[Any]:
        return sorted(
            list(blocks),
            key=lambda block: (
                cls._block_page(block),
                cls._block_id(block),
            ),
        )

    @staticmethod
    def _block_page(block: Any) -> int:
        if isinstance(block, Mapping):
            return int(
                block.get("page")
                or block.get("page_number")
                or 0
            )
        return int(
            getattr(block, "page", None)
            or getattr(block, "page_number", None)
            or 0
        )

    @staticmethod
    def _block_id(block: Any) -> int:
        if isinstance(block, Mapping):
            return int(block.get("block_id") or 0)
        return int(getattr(block, "block_id", 0) or 0)

    @staticmethod
    def _block_lines(block: Any) -> list[Any]:
        if isinstance(block, Mapping):
            values = block.get("lines") or []
        else:
            values = getattr(block, "lines", None) or []

        return list(values)

    @staticmethod
    def _line_text(line: Any) -> str:
        if line is None:
            return ""

        if isinstance(line, str):
            text = line
        elif isinstance(line, Mapping):
            text = str(line.get("text") or "")
        else:
            text = str(getattr(line, "text", "") or "")

        return " ".join(text.replace("\ufffe", "").split())

    @staticmethod
    def _normalize_date(value: str) -> str:
        try:
            return datetime.strptime(value, "%d-%m-%y").date().isoformat()
        except ValueError:
            return value

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def _warn(
        self,
        warning_type: str,
        *,
        page: int,
        source_block_id: int,
        text: str,
    ) -> None:
        self.warnings.append(
            {
                "warning_type": warning_type,
                "page": page,
                "source_block_id": source_block_id,
                "text": text,
            }
        )


class _Candidate:
    """Mutable internal state used while reading consecutive PDF lines."""

    def __init__(
        self,
        *,
        page: int,
        source_block_id: int,
        arrival_group: str,
        main_line: Line,
        raw_lines: list[Line],
    ) -> None:
        self.page = page
        self.source_block_id = source_block_id
        self.arrival_group = arrival_group
        self.main_line = main_line
        self.detail_line: Line | None = None
        self.share_lines: list[Line] = []
        self.accompanying_lines: list[Line] = []
        self.observation_lines: list[Line] = []
        self.continuation_lines: list[Line] = []
        self.raw_lines = raw_lines

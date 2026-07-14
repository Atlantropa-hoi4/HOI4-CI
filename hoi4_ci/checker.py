"""Core HOI4 static checks.

The script scanner deliberately implements only the structural subset needed
to identify top-level event, state, and strategic-region definitions. It is not
a replacement for the game parser or CWTools.
"""

from __future__ import annotations

import fnmatch
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .models import CheckResult, Diagnostic


TEXT_EXTENSIONS = frozenset(
    {
        ".asset",
        ".csv",
        ".fxh",
        ".gfx",
        ".gui",
        ".lua",
        ".mod",
        ".shader",
        ".txt",
        ".yaml",
        ".yml",
    }
)
LOCALISATION_EXTENSIONS = frozenset({".yaml", ".yml"})
IGNORED_DIRECTORY_NAMES = frozenset(
    {".git", ".hg", ".svn", ".venv", "__pycache__"}
)
LANGUAGE_HEADER_RE = re.compile(r"^(l_[a-z][a-z0-9_]*):\s*$")
LOCALISATION_ENTRY_RE = re.compile(
    r"^\s+([^#\s][^:]*)\s*:\s*(\d*)\s*(.*)$"
)
LOCALISATION_KEY_RE = re.compile(r"^[A-Za-z0-9_.@'\-]+$")
FILENAME_ID_RE = re.compile(r"^(\d+)\b")


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int


@dataclass(frozen=True)
class Definition:
    identifier: str
    path: Path
    line: int


@dataclass(frozen=True)
class DefinitionSpec:
    name: str
    directory: str
    block_names: frozenset[str]
    duplicate_code: str
    missing_code: str
    stat_name: str
    filename_code: str | None = None


DEFINITION_SPECS = (
    DefinitionSpec(
        name="event",
        directory="events",
        block_names=frozenset(
            {
                "country_event",
                "news_event",
                "operative_leader_event",
                "state_event",
                "unit_leader_event",
            }
        ),
        duplicate_code="DUPLICATE_EVENT_ID",
        missing_code="MISSING_EVENT_ID",
        stat_name="event_definitions",
    ),
    DefinitionSpec(
        name="state",
        directory="history/states",
        block_names=frozenset({"state"}),
        duplicate_code="DUPLICATE_STATE_ID",
        missing_code="MISSING_STATE_ID",
        filename_code="STATE_FILENAME_ID",
        stat_name="state_definitions",
    ),
    DefinitionSpec(
        name="strategic region",
        directory="map/strategicregions",
        block_names=frozenset({"strategic_region"}),
        duplicate_code="DUPLICATE_STRATEGIC_REGION_ID",
        missing_code="MISSING_STRATEGIC_REGION_ID",
        filename_code="STRATEGIC_REGION_FILENAME_ID",
        stat_name="strategic_region_definitions",
    ),
)


class Checker:
    """Run common read-only checks against one HOI4 mod root."""

    def __init__(self, root: Path, excludes: Iterable[str] = ()) -> None:
        self.root = root.resolve()
        self.excludes = tuple(excludes)
        self.result = CheckResult(root=str(self.root))
        self._decoded: dict[Path, str | None] = {}

    def run(
        self,
        checks: Iterable[str] = ("encoding", "localisation", "duplicates"),
    ) -> CheckResult:
        if not self.root.is_dir():
            raise ValueError(f"mod root is not a directory: {self.root}")

        selected = tuple(dict.fromkeys(checks))
        unknown = sorted(set(selected) - {"encoding", "localisation", "duplicates"})
        if unknown:
            raise ValueError(f"unknown checks: {', '.join(unknown)}")

        if "encoding" in selected:
            self._check_encoding()
        if "localisation" in selected:
            self._check_localisation()
        if "duplicates" in selected:
            self._check_duplicate_ids()

        self.result.diagnostics.sort(
            key=lambda item: (
                item.path.casefold(),
                item.line or 0,
                item.code,
                item.message,
            )
        )
        return self.result

    def _add(
        self,
        code: str,
        message: str,
        path: Path | None = None,
        line: int | None = None,
    ) -> None:
        self.result.diagnostics.append(
            Diagnostic(
                code=code,
                message=message,
                path=self._relative(path) if path is not None else "",
                line=line,
            )
        )

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def _is_excluded(self, path: Path) -> bool:
        relative = self._relative(path)
        parts = Path(relative).parts
        if any(part in IGNORED_DIRECTORY_NAMES for part in parts):
            return True
        return any(fnmatch.fnmatchcase(relative, pattern) for pattern in self.excludes)

    def _iter_files(
        self,
        extensions: frozenset[str],
        directory: Path | None = None,
    ) -> Iterator[Path]:
        base = directory or self.root
        if not base.is_dir():
            return
        paths = (
            path
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix.casefold() in extensions
            and not self._is_excluded(path)
        )
        yield from sorted(paths, key=lambda item: self._relative(item).casefold())

    def _decode(self, path: Path) -> str | None:
        if path in self._decoded:
            return self._decoded[path]
        try:
            data = path.read_bytes()
        except OSError as exc:
            self._add("FILE_READ", f"could not read file: {exc}", path)
            self._decoded[path] = None
            return None

        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            line = data[: exc.start].count(b"\n") + 1
            self._add(
                "TEXT_ENCODING",
                f"file is not valid UTF-8 at byte {exc.start}: {exc.reason}",
                path,
                line,
            )
            text = None
        self._decoded[path] = text
        return text

    def _check_encoding(self) -> None:
        files = list(self._iter_files(TEXT_EXTENSIONS))
        self.result.stats["text_files"] = len(files)
        for path in files:
            self._decode(path)

    def _check_localisation(self) -> None:
        root = self.root / "localisation"
        files = list(self._iter_files(LOCALISATION_EXTENSIONS, root))
        self.result.stats["localisation_files"] = len(files)
        keys: dict[tuple[str, str], list[tuple[Path, int]]] = defaultdict(list)

        for path in files:
            try:
                data = path.read_bytes()
            except OSError:
                self._decode(path)
                continue
            if not data.startswith(b"\xef\xbb\xbf"):
                self._add(
                    "LOCALISATION_BOM",
                    "localisation file must start with a UTF-8 BOM",
                    path,
                    1,
                )

            text = self._decode(path)
            if text is None:
                continue
            # Kaiserreich uses BOM-only files to suppress inherited vanilla
            # localisation without defining replacement keys.
            if not text:
                continue
            lines = text.splitlines()
            first_line = lines[0] if lines else ""
            header_match = LANGUAGE_HEADER_RE.fullmatch(first_line)
            if header_match is None:
                self._add(
                    "LOCALISATION_HEADER",
                    f"first line must be one language header, found {first_line!r}",
                    path,
                    1,
                )
                language = ""
            else:
                language = header_match.group(1)

            for line_number, line in enumerate(lines[1:], 2):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if LANGUAGE_HEADER_RE.fullmatch(line):
                    self._add(
                        "LOCALISATION_HEADER",
                        "localisation file contains more than one language header",
                        path,
                        line_number,
                    )
                    continue

                match = LOCALISATION_ENTRY_RE.fullmatch(line)
                if match is None:
                    self._add(
                        "LOCALISATION_SYNTAX",
                        "entry must be indented and use KEY: [VERSION] \"VALUE\"",
                        path,
                        line_number,
                    )
                    continue

                key = match.group(1).strip()
                payload = match.group(3)
                if LOCALISATION_KEY_RE.fullmatch(key) is None:
                    self._add(
                        "LOCALISATION_KEY",
                        f"invalid localisation key {key!r}",
                        path,
                        line_number,
                    )
                    continue
                payload_error = _localisation_payload_error(payload)
                if payload_error is not None:
                    self._add(
                        "LOCALISATION_SYNTAX",
                        payload_error,
                        path,
                        line_number,
                    )
                if language:
                    keys[(language, key)].append((path, line_number))

        for (language, key), locations in sorted(keys.items()):
            if len(locations) < 2:
                continue
            first_path, first_line = locations[0]
            first_location = f"{self._relative(first_path)}:{first_line}"
            for path, line in locations[1:]:
                self._add(
                    "DUPLICATE_LOCALISATION_KEY",
                    f"{key!r} is already defined for {language} at {first_location}",
                    path,
                    line,
                )

        self.result.stats["localisation_keys"] = len(keys)

    def _check_duplicate_ids(self) -> None:
        for spec in DEFINITION_SPECS:
            definitions: list[Definition] = []
            directory = self.root / spec.directory
            for path in self._iter_files(frozenset({".txt"}), directory):
                text = self._decode(path)
                if text is None:
                    continue
                definitions.extend(self._definitions_in_file(path, text, spec))

            self.result.stats[spec.stat_name] = len(definitions)
            by_identifier: dict[str, list[Definition]] = defaultdict(list)
            for definition in definitions:
                by_identifier[definition.identifier].append(definition)
                self._check_filename_id(definition, spec)

            for identifier, occurrences in sorted(by_identifier.items()):
                if len(occurrences) < 2:
                    continue
                first = occurrences[0]
                first_location = f"{self._relative(first.path)}:{first.line}"
                for duplicate in occurrences[1:]:
                    self._add(
                        spec.duplicate_code,
                        f"{spec.name} ID {identifier!r} is already defined at {first_location}",
                        duplicate.path,
                        duplicate.line,
                    )

    def _check_filename_id(self, definition: Definition, spec: DefinitionSpec) -> None:
        if spec.filename_code is None:
            return
        match = FILENAME_ID_RE.match(definition.path.stem)
        if match is None or not definition.identifier.isdecimal():
            return
        filename_id = match.group(1)
        if int(filename_id) != int(definition.identifier):
            self._add(
                spec.filename_code,
                f"filename ID {filename_id} does not match internal ID {definition.identifier}",
                definition.path,
                definition.line,
            )

    def _definitions_in_file(
        self,
        path: Path,
        text: str,
        spec: DefinitionSpec,
    ) -> list[Definition]:
        tokens, string_error = _tokenize(text)
        if string_error is not None:
            self._add(
                "SCRIPT_UNTERMINATED_STRING",
                "quoted string has no closing quote",
                path,
                string_error,
            )

        brace_error = _brace_error(tokens)
        if brace_error is not None:
            message, line = brace_error
            self._add("SCRIPT_UNBALANCED_BRACES", message, path, line)
            return []

        definitions: list[Definition] = []
        depth = 0
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if (
                depth == 0
                and token.kind == "atom"
                and token.value in spec.block_names
                and index + 2 < len(tokens)
                and tokens[index + 1].kind == "equals"
                and tokens[index + 2].kind == "open"
            ):
                closing_index, identifiers = _direct_ids(tokens, index + 2)
                if not identifiers:
                    self._add(
                        spec.missing_code,
                        f"top-level {token.value} block has no scalar id",
                        path,
                        token.line,
                    )
                else:
                    first = identifiers[0]
                    definitions.append(Definition(first.value, path, first.line))
                    for extra in identifiers[1:]:
                        self._add(
                            "MULTIPLE_ID_FIELDS",
                            f"top-level {token.value} block has multiple direct id fields",
                            path,
                            extra.line,
                        )
                index = closing_index + 1
                continue

            if token.kind == "open":
                depth += 1
            elif token.kind == "close":
                depth -= 1
            index += 1
        return definitions


def _localisation_payload_error(payload: str) -> str | None:
    if not payload.startswith('"'):
        return "localisation value must begin with a quote"
    closing_index = payload.rfind('"')
    if closing_index == 0:
        return "localisation value has no closing quote"
    trailing = payload[closing_index + 1 :].strip()
    if trailing and not trailing.startswith("#"):
        return f"unexpected text after closing quote: {trailing!r}"
    return None


def _tokenize(text: str) -> tuple[list[Token], int | None]:
    tokens: list[Token] = []
    index = 0
    line = 1
    unterminated_string_line: int | None = None

    while index < len(text):
        char = text[index]
        if char.isspace():
            if char == "\n":
                line += 1
            index += 1
            continue
        if char == "#":
            newline = text.find("\n", index)
            if newline == -1:
                break
            index = newline
            continue
        if char in "{}=":
            kind = {"{": "open", "}": "close", "=": "equals"}[char]
            tokens.append(Token(kind, char, line))
            index += 1
            continue
        if char == '"':
            start_line = line
            index += 1
            value: list[str] = []
            escaped = False
            closed = False
            while index < len(text):
                current = text[index]
                if current == "\n":
                    line += 1
                if escaped:
                    value.append(current)
                    escaped = False
                elif current == "\\":
                    value.append(current)
                    escaped = True
                elif current == '"':
                    closed = True
                    index += 1
                    break
                else:
                    value.append(current)
                index += 1
            tokens.append(Token("string", "".join(value), start_line))
            if not closed and unterminated_string_line is None:
                unterminated_string_line = start_line
            continue

        start = index
        while index < len(text):
            current = text[index]
            if current.isspace() or current in '{}=#"':
                break
            index += 1
        tokens.append(Token("atom", text[start:index], line))

    return tokens, unterminated_string_line


def _brace_error(tokens: list[Token]) -> tuple[str, int] | None:
    openings: list[int] = []
    for token in tokens:
        if token.kind == "open":
            openings.append(token.line)
        elif token.kind == "close":
            if not openings:
                return "closing brace has no matching opening brace", token.line
            openings.pop()
    if openings:
        return "opening brace has no matching closing brace", openings[-1]
    return None


def _direct_ids(tokens: list[Token], opening_index: int) -> tuple[int, list[Token]]:
    depth = 1
    identifiers: list[Token] = []
    index = opening_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "open":
            depth += 1
        elif token.kind == "close":
            depth -= 1
            if depth == 0:
                return index, identifiers
        elif (
            depth == 1
            and token.kind == "atom"
            and token.value == "id"
            and index + 2 < len(tokens)
            and tokens[index + 1].kind == "equals"
            and tokens[index + 2].kind in {"atom", "string"}
        ):
            identifiers.append(tokens[index + 2])
        index += 1
    raise AssertionError("balanced token stream ended before block closed")

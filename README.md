# HOI4 CI

HOI4 CI is a dependency-free static checker for Hearts of Iron IV mod
repositories. It is designed for Linux CI runners where the game and vanilla
data are not installed.

The initial rule set follows the repository structure and script forms used by
`Kaiserreich/Kaiserreich-4-Development`, while keeping project-specific IDs and
policies outside the checker. `Faith-in-Steel/Faith-in-Steel` is the first
integration target.

## Checks

- UTF-8 decoding for common HOI4 text formats.
- UTF-8 BOM, one language header, quoted entry syntax, and per-language key
  uniqueness for `localisation/**/*.yml` and `*.yaml`.
- Duplicate top-level event IDs in `events/**/*.txt`.
- Duplicate state IDs and filename/internal-ID mismatches in
  `history/states/**/*.txt`.
- Duplicate strategic-region IDs and filename/internal-ID mismatches in
  `map/strategicregions/**/*.txt`.
- Unbalanced braces and unterminated strings in files scanned for definitions.

The structural scanner ignores comments and quoted braces. It reads only direct
`id` fields of top-level definition blocks, so an event call such as
`country_event = { id = example.2 }` inside an option is not mistaken for a new
event definition. Whitespace is not significant; both `id = 1` and `id=1` are
accepted.

BOM-only localisation placeholders and unescaped quote characters inside a
quoted value are accepted because both forms are present in the Kaiserreich
reference. Non-empty localisation files still require exactly one language
header as their first line.

This is a fast smoke gate, not a full Clausewitz parser or a replacement for
CWTools, the game parser, or project-specific validation.

## Usage

Python 3.11 or newer is recommended. No package installation is required.

```bash
python -m hoi4_ci /path/to/mod
```

Select checks or exclude generated paths when needed:

```bash
python -m hoi4_ci /path/to/mod \
  --check localisation \
  --check duplicates \
  --exclude 'generated/**'
```

For GitHub Actions annotations and a complete JSON artifact:

```bash
python -m hoi4_ci /path/to/mod \
  --format github \
  --json-report hoi4-ci-report.json
```

The command exits with `0` on success, `1` when diagnostics are found, and `2`
for invalid arguments or an unusable mod root.

## GitHub Action

After publishing this repository, a mod repository can call the composite
action after checking out its files. Pin the action to a reviewed commit SHA:

```yaml
steps:
  - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
  - uses: Atlantropa-hoi4/HOI4-CI@REVIEWED_COMMIT_SHA
    with:
      path: .
      format: github
      json-report: hoi4-ci-report.json
```

The action sets up Python 3.11 and runs the same dependency-free CLI. A caller
can upload the optional JSON report even when the validation step fails.

## Direct-push workflow

The recommended mod workflow does not depend on pull requests:

- A push to `main` runs a five-minute smoke job over the core script paths.
- The daily schedule and manual dispatch run a broader ten-minute text-data job.
- Both jobs preserve a JSON report for seven days.
- Concurrency cancellation keeps only the latest run for the same branch.

The Faith in Steel template is available at
`examples/faith-in-steel/hoi4-static-checks.yml`. Copy it to
`.github/workflows/hoi4-static-checks.yml` in the mod repository, then replace
`REVIEWED_COMMIT_SHA` with the reviewed HOI4-CI commit. The placeholder is
intentional: an unpinned branch reference would allow checker changes to alter
the mod's CI without review.

## Development

Run the dependency-free test suite with:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

The repository workflow runs these tests and checks sparse checkouts of the
latest Faith in Steel `main` branch. Pushes run the smoke path set; scheduled
and manual runs add the remaining runtime text definitions while still omitting
tooling data, large image, audio, and map raster assets.

Reference inspection for the initial implementation used read-only snapshots
of Kaiserreich `master` at `394740903e51d4c014b8ccd84ecd4267c9b21348`
and Faith in Steel `main` at
`bcd63d3ea7126562a68ace2b49fcbd1909a5c592` on 2026-07-14.

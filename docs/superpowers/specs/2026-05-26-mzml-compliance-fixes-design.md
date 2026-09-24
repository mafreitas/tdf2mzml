# v0.6.1 — mzML Compliance & Robustness Fixes

**Date:** 2026-05-26
**Branch (to be created):** `feature/0.6.1-compliance-fixes`
**Base:** `main` @ `a09ab5c` (post v0.6 merge)
**Closes:** #31, #32, #33
**Status:** DRAFT (rev 2) — codex re-review 2026-05-26 verdict: ready to implement; pending user sign-off

## Goal

Ship v0.6.1 as a point release containing three correctness fixes against the v0.6 baseline. Address each bug at the class level — fix every site exhibiting the pattern, not only the one each issue happens to name.

## Scope

Three bugs, each generalized:

1. **#33 — XML attribute escaping**: `xml.sax.saxutils.escape()` doesn't escape `"` by default, so values containing double quotes break the surrounding attribute. The issue names `sample description`; the same pattern exists at ~8 attribute-emit sites in `src/tdf2mzml/output/xml_elements.py`.
2. **#32 — Ion mobility cvParam**: `CV_INVERSE_REDUCED_ION_MOBILITY` is set to `MS:1002814` (the unit accession `volt-second per square centimeter`), not a term. The emitted cvParam therefore has both `accession` and `unitAccession` equal to `MS:1002814`, and uses the non-standard term name `mean inverse reduced ion mobility`.
3. **#31 — SQL `IN (?, ?, ...)` overflow on Windows**: `get_pasef_frame_info_batch()` in `src/tdf2mzml/io/reader.py` passes every precursor ID as a separate placeholder. CPython on Windows ships SQLite with `SQLITE_MAX_VARIABLE_NUMBER=32766`; files with more DDA precursors fail. The same unchunked-`IN` pattern lives at 5 sites across `io/reader.py`, `io/tsf_reader.py`, `io/baf_reader.py`.

## Decisions (locked in)

| Topic | Decision | Rationale |
|---|---|---|
| Release context | v0.6.1 point release: bump version, CHANGELOG entry, plan to tag/release after merge | Bugfixes warrant a patch release; clean install target for users |
| #33 fix scope | Helper-based fix; replace at all attribute-emit sites | Same-class bug at 8 places, ~10 line diff, byte-identical output otherwise |
| #32 cvParam | Emit SINGLE `MS:1002815 "inverse reduced ion mobility"`; delete misnamed constant `CV_MEAN_INVERSE_REDUCED_ION_MOBILITY` | PSI-MS OBO verification (2026-05-26): no scalar "mean" term exists. MS:1003008 is `raw inverse reduced ion mobility *array*`, not a scalar; the existing constant's comment was wrong. MS:1002815 is the only valid scalar term for per-spectrum 1/K0 |
| #31 fix scope | Shared chunking helper; apply at all 5 SQL sites including BAF 2D | Same-class bug across all three readers |
| Chunk size | Hardcoded `SQL_IN_CHUNK_SIZE = 500` | Half of worst-case 999 SQLite default; safe on every build, including older Windows CPython |
| Commit structure | One PR, four commits: (#33), (#32), (#31), version bump + CHANGELOG | Each fix isolated in `git log` / `git blame`; bisect/revert friendly; matches v0.6 merge-commit style |
| Branch | `feature/0.6.1-compliance-fixes` off `main` | Indicates release intent, fits existing `feature/<title>` convention |

## Architecture

### `src/tdf2mzml/output/xml_elements.py`

Add a private helper near the top of the module:

```python
def _xml_attr(value: object) -> str:
    """Escape a value for use inside an XML attribute (handles quotes)."""
    return _xml_escape(str(value), {'"': "&quot;"})
```

Replace every `_xml_escape(...)` call that appears *inside* a `"..."` attribute value with `_xml_attr(...)`. Keep `_xml_escape` for element-text content (it's still correct there — `"` doesn't need escaping in text nodes).

Call sites to convert (8 sites):
- L247: `_cv(..., _xml_escape(sf['sha1']))` — actually inside `_cv()` value, attribute-bound (verify)
- L252-253: `<sourceFile id="..." name="..." location="...">` (3 attributes)
- L286: cv_name inside `_cv()` — verify
- L291-292: `<userParam name="..." value="..." type="xsd:string"/>` (2 attributes)
- L295: `<software id="..." version="...">` (2 attributes)
- L329, L334: `<userParam name="instrument model" value="..."/>` and `<userParam name="instrument vendor" value="..."/>`
- L339: `_cv(CV_INSTRUMENT_SERIAL, ..., _xml_escape(serial_number))` — value-side, verify
- L388: `<userParam name="sample description" value="..."/>` (#33 reported case)
- L394: `<sample id="..." name="...">`

Exact site list will be confirmed during implementation; the principle is: any string interpolated into an `attribute="..."` slot uses `_xml_attr`.

### `src/tdf2mzml/io/_sql.py` (new module)

```python
"""SQL helpers shared by the Bruker readers."""
from collections.abc import Iterable, Iterator
from typing import Any

SQL_IN_CHUNK_SIZE = 500


def batched_in_query(
    conn: Any,
    sql_template: str,
    ids: list[int],
    *,
    extra_params: tuple[Any, ...] = (),
) -> Iterator[Any]:
    """Execute a SQL IN-clause query in chunks.

    sql_template must contain exactly one '{placeholders}' format slot.
    Each chunk is sent as a separate execute(); rows are yielded as they arrive.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection.
    sql_template : str
        Query string with one '{placeholders}' slot, e.g.
        "SELECT a, b FROM T WHERE x IN ({placeholders})".
    ids : list[int]
        Values to substitute. Splits into chunks of SQL_IN_CHUNK_SIZE.
    extra_params : tuple, optional
        Additional positional params appended to each chunk's params.
        Used when the SQL has both IN(...) and other bound parameters.

    Yields
    ------
    sqlite3.Row
        Rows in chunk order (which may differ from `ids` order — callers
        that need order must dict-map by key or sort downstream).
    """
    if not ids:
        return
    for i in range(0, len(ids), SQL_IN_CHUNK_SIZE):
        chunk = ids[i : i + SQL_IN_CHUNK_SIZE]
        placeholders = ",".join("?" * len(chunk))
        yield from conn.execute(
            sql_template.format(placeholders=placeholders),
            tuple(chunk) + extra_params,
        )
```

Applied at 5 sites:

- `io/reader.py:353` — PASEF/TDF `Precursor IN (...)`
- `io/tsf_reader.py:243` — TSF `Frame IN (...)` query 1
- `io/tsf_reader.py:275` — TSF `Frame IN (...)` query 2
- `io/baf_reader.py:257` — BAF `TargetSpectrum IN (...)`
- `io/baf_reader.py:283` — BAF `Spectrum IN (?) AND Variable IN (?)` (2D)

**BAF 2D handling** (`io/baf_reader.py:283`): The query has two `IN` clauses. Strategy: chunk the *larger* list with `batched_in_query`, pass the *smaller* list (typically bounded — only a small fixed set of MS variables) as `extra_params`. The smaller list is inlined verbatim into the SQL template since it's known to be small. If both lists are unbounded in some pathological case, we'd need a 2D loop — but a quick read of the schema suggests one is always bounded.

### `src/tdf2mzml/constants.py`

Two changes:

```python
# Was: CV_INVERSE_REDUCED_ION_MOBILITY: str = "MS:1002814"  (a UNIT accession, not a term)
CV_INVERSE_REDUCED_ION_MOBILITY: str = "MS:1002815"  # PSI-MS scalar term

# Delete entirely — the existing constant is dead code with a misleading comment.
# MS:1003008 is the PSI-MS term `raw inverse reduced ion mobility array` (an array,
# not a scalar mean), so this constant cannot be used on a scan element.
# CV_MEAN_INVERSE_REDUCED_ION_MOBILITY: str = "MS:1003008"  ← REMOVE
```

PSI-MS OBO verification (2026-05-26, `raw.githubusercontent.com/HUPO-PSI/psi-ms-CV/master/psi-ms.obo`):
- `MS:1002814` `volt-second per square centimeter` `is_a: UO:0000000 ! unit` — confirmed UNIT.
- `MS:1002815` `inverse reduced ion mobility` `is_a: MS:1000455 ! ion selection attribute, MS:1002892 ! ion mobility attribute, MS:1003254 ! peak attribute` — SCALAR, applicable to scan/spectrum elements.
- `MS:1003008` `raw inverse reduced ion mobility array` `is_a: MS:1002893 ! ion mobility array` — ARRAY, not valid on a scan element.
- No scalar "mean" variant exists in the CV. All `mean ...` terms are arrays.

### `src/tdf2mzml/output/xml_elements.py:553` (#32 emit site)

Was:

```python
im_scan_cv = f"\n          {_cv(CV_INVERSE_REDUCED_ION_MOBILITY, 'mean inverse reduced ion mobility', f'{one_over_k0:.6f}', unit_accession=UNIT_VSCC, unit_name='volt-second per square centimeter')}"
```

After: emit a single conformant cvParam — `MS:1002815 "inverse reduced ion mobility"`. The "mean" semantic is implicit in how tdf2mzml computes the per-frame value; no separate CV term encodes it.

Pseudocode:

```python
im_scan_cv = (
    f"\n          {_cv(CV_INVERSE_REDUCED_ION_MOBILITY, 'inverse reduced ion mobility', f'{one_over_k0:.6f}', unit_accession=UNIT_VSCC, unit_name='volt-second per square centimeter')}"
)
```

Note: the ion mobility *array* cvParam (`MS:1002816 "mean ion mobility array"`) at L658 stays unchanged — it's already a correct array term.

## Test plan

New tests in `tests/test_xml_compliance.py` and `tests/test_reader.py`. The v0.6 compliance suite has strong patterns we extend. Codex review (2026-05-26) trimmed #33 redundancy and broadened #31 coverage.

**For #33** — `tests/test_xml_compliance.py`:
- Unit: `_xml_attr('a"b') == 'a&quot;b'`, `_xml_attr('plain') == 'plain'`, `_xml_attr('he said "hi" & ok') == 'he said &quot;hi&quot; &amp; ok'`.
- Integration: render `sample_list(...)` with a description containing `"`; parse the chunk with strict lxml; assert no `XMLSyntaxError` and that the attribute value round-trips.
- (Dropped from rev 1: mutation-test variant — codex flagged it as redundant with the integration test above.)

**For #32** — `tests/test_xml_compliance.py`:
- Assert the per-spectrum ion-mobility cvParam on the scan element has `accession="MS:1002815"`, `name="inverse reduced ion mobility"`, `cvRef="PSI-MS"`.
- Assert `accession != unitAccession` (the exact failure mode in issue #32).
- Assert `unitAccession="MS:1002814"`, `unitName="volt-second per square centimeter"`, `unitCvRef="PSI-MS"`.
- Negative assertion: no second cvParam with accession `MS:1003008` is emitted on the scan element (guards against accidental regression to the rev-1 dual-emit plan).

**For #31** — `tests/test_reader.py`:
- Unit on `batched_in_query`: pass `list(range(50_000))`, count `conn.execute` calls on a recording fake → expect `ceil(50000/500) == 100`. Verify no chunk has > 500 placeholders.
- Unit on `extra_params`: same template plus `extra_params=("foo",)`; assert each chunk's parameter tuple ends with `"foo"`.
- Parametrized integration over all 5 SQL sites (per codex recommendation — closes the under-coverage gap):
  - `io/reader.py:353` → `get_pasef_frame_info_batch`
  - `io/tsf_reader.py:243` → first TSF batch (verify caller name during implementation)
  - `io/tsf_reader.py:275` → second TSF batch
  - `io/baf_reader.py:257` → BAF `TargetSpectrum IN (...)`
  - `io/baf_reader.py:283` → BAF 2D `Spectrum IN (...) AND Variable IN (...)`

  Each site gets an integration test that builds an in-memory SQLite with the relevant synthetic schema, passes ≥40,000 IDs, asserts the result count matches and that the internal `execute` call count > 1 (proves chunking actually ran).
- BAF 2D specifically: assert the inner `var_ids` list is left intact (no chunking), only the outer `Spectrum` list is chunked.
- (No change to existing reader tests; the refactor must keep them passing.)

**CI** — existing pipeline (ruff, mypy, pytest) covers all three fixes. No new CI jobs.

### PR-review checklist (manual, at review time)

- **#33 site coverage**: integration test only exercises `sample_description`. Reviewer must inspect the diff and confirm every attribute-bound `_xml_escape(...)` call in `xml_elements.py` was replaced with `_xml_attr(...)`. (Spec lists the candidate sites — verify against the actual file at PR time.)

## Release artifacts

1. `pyproject.toml` — bump `version = "0.6.1"`.
2. `CHANGELOG.md` — new section under "Unreleased" or new `## [0.6.1]` entry summarizing the three fixes with issue refs.
3. No Docker rebuild in this branch (per project decision); Docker work happens after merge.

## Board moves (workflow side effects)

- #28 — already in **Done** (auto-moved when PR #30 merged).
- #29 (PyPI) — stays in **Planning**, untouched.
- #31, #32, #33 — move from **Backlog** to **Planning** once this spec is approved, then to **In Progress** when implementation starts.

## Out of scope

- ElementTree/lxml rewrite of XML generation (Approach C earlier — deferred to a future architectural pass; #33 fix is local).
- Runtime detection of `SQLITE_LIMIT_VARIABLE_NUMBER` (deferred — hardcoded 500 is sufficient).
- Strict mzML XSD validation gate in CI (deferred — codex confirmed it's a fine future enhancement but not needed for v0.6.1).
- PyPI work (#29) — unrelated, stays in Planning.
- Docker `latest` retag and removal of legacy `0.5_cvparam-compliance*` tags — orthogonal release-mechanics task.

## Resolved questions (from rev 1)

1. **BAF 2D `IN` chunking API.** `extra_params` is fine — the smaller list at `io/baf_reader.py:283` is bounded (codex verified: only `_var_collision_energy` and `_var_isolation_width` appended, max 2 values). No 2D loop needed.
2. **#32 cvParam dual-emit validity.** Resolved by PSI-MS OBO verification: the rev-1 dual-emit plan was based on a misnamed constant. MS:1003008 is an array term, not a scalar mean. Revised plan emits only `MS:1002815`.
3. **#32 cvParam emit order.** N/A — only one cvParam is emitted now.

## Open questions for review

None at this revision. The earlier three are resolved above. Codex review identified two test-plan gaps (now fixed) and one CV-validity gap (now resolved by OBO lookup).

# Releasing tdf2mzml to PyPI

This project publishes platform-specific wheels (`manylinux_2_24_x86_64` and
`win_amd64`) plus an sdist to PyPI on every `v*.*.*` git tag, via a GitHub
Actions workflow using PyPI's OIDC trusted publisher (no API tokens).

## One-time setup

### 1. Register the project on TestPyPI and PyPI

- Create account on https://test.pypi.org and https://pypi.org if you don't
  have one. Enable 2FA on both.
- Reserve the `tdf2mzml` name by manually uploading a first release once,
  or by configuring trusted publishing before the first release using the
  "pending publisher" flow.

### 2. Configure trusted publishers

For each of TestPyPI and PyPI:

1. Project page → Settings → Publishing → Add a new pending publisher.
2. Fill in:
   - **PyPI Project Name:** `tdf2mzml`
   - **Owner:** `mafreitas`
   - **Repository name:** `tdf2mzml`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi` (or `testpypi`)
3. Save.

### 3. Configure GitHub environments

In the GitHub repo → Settings → Environments → New environment:

- Create `testpypi` and `pypi` environments.
- For `pypi`, add a required reviewer (yourself) so production uploads
  pause for manual approval.

## Cutting a release

1. Update `CHANGELOG.md` with the new version's notes.
2. Bump the version in **two** places (must match exactly):
   - `pyproject.toml` (`version = "X.Y.Z"`)
   - `src/tdf2mzml/__init__.py` (`__version__ = "X.Y.Z"`)
3. If the bundled SDK versions changed, update:
   - `src/tdf2mzml/__init__.py` (`__bruker_tdf_sdk_version__`, `__bruker_baf2sql_version__`)
   - `NOTICE` (SDK version line)
   - `README.md` (the dependencies paragraph)
4. Commit and PR; merge once green.
5. From `main`:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
6. Watch the Actions tab. The workflow will:
   - Build sdist + both wheels
   - Verify `tdf2mzml.__version__` matches the tag
   - Run compliance tests
   - Publish to TestPyPI
   - Wait for `pypi` environment approval, then publish to PyPI

## Dry run (TestPyPI only)

```bash
gh workflow run publish.yml -f target=testpypi
```

Then install from TestPyPI to verify:
```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            tdf2mzml==X.Y.Z
tdf2mzml --version    # must show Bruker copyright lines
```

## Local manual release (emergency only)

If the GHA workflow is unavailable:

```bash
# Ensure you're on the tagged commit, working tree clean
make wheels                  # produces dist/*
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*
# install + smoke test, then:
python -m twine upload dist/*
```

This requires API tokens stored in `~/.pypirc`; prefer the OIDC workflow.

## Updating the bundled Bruker SDK

The canonical "host location" for SDK source files is
`Incoming_updates_data/`:

- `Incoming_updates_data/timsdata/` — Bruker TDF SDK install tree
- `Incoming_updates_data/baf2sql-c-2.9.0/` — Baf2Sql install tree

To pick up a new SDK release:

1. Replace the contents of those directories with the new SDK install.
2. Re-read each `redist.txt` — confirm the allowlist hasn't changed.
   If it has, update `scripts/sync_sdk_libs.py`'s `COPY_MAP`.
3. Update version constants in `src/tdf2mzml/__init__.py` and `NOTICE`.
4. Run `make sync-libs` to re-vendor the redistributable files.
5. Run `make ci` and `make wheels` to verify nothing broke.
6. If the new `.so` requires a newer glibc, run `auditwheel show` on the
   Linux wheel and update the platform tag in `scripts/build_wheels.sh`
   (line containing `build_platform_wheel manylinux_X_YY_x86_64`).
   **Never** run `auditwheel repair` — it modifies the binary, which the
   Bruker EULA does not permit.
7. Commit the SDK refresh in a single commit:
   ```bash
   git add Incoming_updates_data/ src/tdf2mzml/libs/ \
           src/tdf2mzml/__init__.py NOTICE scripts/sync_sdk_libs.py \
           scripts/build_wheels.sh
   git commit -m "build: update Bruker TDF SDK to vX.Y.Z and Baf2Sql to vA.B.C"
   ```

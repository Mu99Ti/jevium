# Jevium Repository Reset Design

## Context

The current checkout contains the Jevium product code plus a separate legacy browser-loop package, historical planning documents, and an existing GitHub remote. The intended source changes are uncommitted and must be preserved.

## Goals

- Preserve current Jevium functionality while renaming the non-product source package.
- Remove legacy package names, legacy project names, upstream URLs, and fork language from every file that will be tracked in the new repository.
- Replace `README.md` with a fresh Jevium-only README.
- Create a new public GitHub repository at `Mu99Ti/jevium` with fresh history.
- Keep a local backup and rollback path until the new remote is verified.

## Scope

### Package and code

- Rename the current non-product source package directory to `jevium_core/`.
- Update imports, tests, scripts, examples, package metadata, entry points, and static-file paths to use `jevium_core`.
- Keep the existing `jevium/` package as the product-facing package.
- Set the distribution name to `jevium`.
- Preserve all existing Jevium CLI/TUI behavior.

### Documentation and tracked files

- Write a new `README.md` that describes only Jevium, its CLI, TUI, HITL behavior, setup, and development checks.
- Remove or rewrite tracked documentation, planning files, examples, scripts, and configuration that contain legacy identifiers or upstream references.
- Update `AGENTS.md` to describe Jevium and its current checks.
- Retain required MIT license text; do not remove copyright attribution without explicit rights confirmation.
- Do not track `.env`, virtual environments, caches, recordings, build outputs, or other ignored local artifacts.

### Repository history and remotes

1. Create and verify a local Git bundle backup of the current repository.
2. Build a fresh local history containing only the cleaned source tree.
3. Temporarily rename the existing GitHub repository so the target name is available.
4. Create public `Mu99Ti/jevium`.
5. Push the fresh `main` branch and configure it as `origin`.
6. Verify the new remote contents and searches.
7. Delete the old GitHub repository only after verification succeeds.
8. Remove the old upstream remote from the local and new remote configuration.

## Error Handling and Rollback

- If any verification step fails, stop before deleting the old GitHub repository.
- Restore the old repository name if the new repository cannot be created or pushed.
- Keep the local bundle until the new remote has passed all verification checks.
- Never overwrite the old remote before a successful new push.

## Verification

- Search tracked files for legacy package names, legacy project names, upstream URLs, and fork language.
- Run `ruff`, `pytest`, renamed JavaScript syntax checks, `uv build`, and CLI smoke tests.
- Inspect the new GitHub repository tree, README, license, remotes, and visibility.
- Confirm that no ignored secrets or local artifacts are tracked.
- Confirm that the old remote is deleted only after all checks pass.

## Success Criteria

- Current Jevium functionality works after the package rename.
- The fresh repository contains no legacy identifiers in tracked files or new commit history.
- The README contains no legacy upstream references.
- Public `Mu99Ti/jevium` exists, the cleaned `main` branch is pushed, and the old repository is removed after verification.

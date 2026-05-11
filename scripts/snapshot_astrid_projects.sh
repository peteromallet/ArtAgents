#!/usr/bin/env bash
# Snapshot the user's astrid-projects/ tree to a dated tarball outside the repo.
# Exit codes: 1 = source dir missing, 2 = tarball clobber refused, 3 = tarball empty.
set -euo pipefail

SOURCE_DIR="${HOME}/Documents/reigh-workspace/astrid-projects"
SNAPSHOT_ROOT="${HOME}/astrid-snapshots"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TARBALL="${SNAPSHOT_ROOT}/astrid-projects-${TIMESTAMP}.tar.gz"

# --- Guard: source directory must exist ---
if [[ ! -d "${SOURCE_DIR}" ]]; then
    echo "ERROR: source directory does not exist: ${SOURCE_DIR}" >&2
    exit 1
fi

# --- Guard: refuse to clobber an existing tarball with the same timestamp ---
if [[ -f "${TARBALL}" ]]; then
    echo "ERROR: tarball already exists (clobber refused): ${TARBALL}" >&2
    exit 2
fi

# --- Create snapshot root if needed ---
mkdir -p "${SNAPSHOT_ROOT}"

# --- Create the tarball ---
tar -czf "${TARBALL}" -C "$(dirname "${SOURCE_DIR}")" "$(basename "${SOURCE_DIR}")"

# --- Guard: tarball must not be empty (0 bytes) ---
if [[ ! -s "${TARBALL}" ]]; then
    echo "ERROR: tarball is empty (0 bytes): ${TARBALL}" >&2
    rm -f "${TARBALL}"
    exit 3
fi

# --- Verify the tarball is a valid gzip archive ---
if ! tar -tzf "${TARBALL}" >/dev/null 2>&1; then
    echo "ERROR: tarball verification failed: ${TARBALL}" >&2
    rm -f "${TARBALL}"
    exit 3
fi

# --- Guard: tarball must contain at least one regular file (not just directories) ---
FILE_COUNT=$(tar -tzf "${TARBALL}" 2>/dev/null | grep -c -v '/$' || true)
if [[ "${FILE_COUNT}" -eq 0 ]]; then
    echo "ERROR: tarball contains no files (only directories): ${TARBALL}" >&2
    rm -f "${TARBALL}"
    exit 3
fi

# --- Success: print absolute path ---
echo "${TARBALL}"
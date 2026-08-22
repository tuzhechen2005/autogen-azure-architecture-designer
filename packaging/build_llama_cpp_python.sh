#!/usr/bin/env bash
# Build llama-cpp-python from the official upstream sdist with the local
# security patch applied.
#
# The upstream package metadata hard-requires `diskcache`, whose pickle-backed
# persistence is affected by CVE-2025-69872 (CWE-502, no fixed release exists:
# 5.6.3 is both the latest and the last affected version). The patch removes
# that dependency and the pickle-backed LlamaDiskCache implementation while
# keeping the Llama API, LlamaRAMCache, and Metal/CPU inference intact.
#
# Everything is pinned by hash, so the result is reproducible and auditable:
#   * upstream sdist  -> SDIST_SHA256 (identical to the hash in requirements.lock)
#   * local patch     -> PATCH_SHA256
#
# Usage:  packaging/build_llama_cpp_python.sh <output-wheel-dir>
set -euo pipefail

VERSION="0.3.35"
SDIST_SHA256="1139dbb54509074b70893fab8554e3b079aa9f4d312058ce4018ef0019e3de12"
PATCH_SHA256="c2d1ecee23235f71af35e8a4fce0eff504cffef9aaa94a463d2b1d5518bd6ad4"
SDIST_URL="https://files.pythonhosted.org/packages/source/l/llama_cpp_python/llama_cpp_python-${VERSION}.tar.gz"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
patch_file="${repo_root}/packaging/patches/llama-cpp-python-${VERSION}-remove-diskcache.patch"
out_dir="${1:?usage: build_llama_cpp_python.sh <output-wheel-dir>}"
mkdir -p "${out_dir}"
out_dir="$(cd "${out_dir}" && pwd)"

verify_sha256() {
  local file="$1" expected="$2" actual
  actual="$(shasum -a 256 "${file}" | awk '{print $1}')"
  if [ "${actual}" != "${expected}" ]; then
    echo "hash mismatch for ${file}: expected ${expected}, got ${actual}" >&2
    exit 1
  fi
}

verify_sha256 "${patch_file}" "${PATCH_SHA256}"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

sdist="${work}/llama_cpp_python-${VERSION}.tar.gz"
curl -fsSL -o "${sdist}" "${SDIST_URL}"
verify_sha256 "${sdist}" "${SDIST_SHA256}"

tar xzf "${sdist}" -C "${work}"
cd "${work}/llama_cpp_python-${VERSION}"
patch -p1 < "${patch_file}"

# Fail closed: the build must not depend on diskcache in any form.
if grep -rn "^import diskcache\|^ *\"diskcache" pyproject.toml llama_cpp/*.py; then
  echo "diskcache still referenced after patching" >&2
  exit 1
fi

export CMAKE_ARGS="${CMAKE_ARGS:--DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_APPLE_SILICON_PROCESSOR=arm64 -DGGML_METAL=on}"
python -m pip wheel . --no-deps -w "${out_dir}"

echo "built wheel(s) in ${out_dir}:"
ls -1 "${out_dir}"

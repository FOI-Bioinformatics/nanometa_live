#!/usr/bin/env bash
# Activate Nextflow's pre-warmed per-process conda cache shipped with a
# Nanometa Live offline bundle.
#
# Usage:
#     source ./activate_offline_envs.sh
#
# The script auto-detects the bundle install directory from its own
# location, exports NXF_CONDA_CACHEDIR to the bundled cache directory,
# and prints a single-line ready message. Source this from the
# operator's shell before launching Nanometa Live.
#
# This script is safe to run when sourced or executed directly; it
# uses parameter expansion to recover its own location either way.

set -euo pipefail

# Resolve the install directory from the script's own path. Handles
# both `source ./activate_offline_envs.sh` and direct execution.
if [ -n "${BASH_SOURCE[0]:-}" ]; then
    _script_path="${BASH_SOURCE[0]}"
else
    _script_path="$0"
fi
_install_dir="$(cd "$(dirname "${_script_path}")" && pwd)"

# The conda_cache directory sits next to the script when written by
# import_bundle. If the script was placed inside an installed bundle's
# scripts/ subdirectory, climb one level up.
if [ -d "${_install_dir}/conda_cache" ]; then
    _cache_dir="${_install_dir}/conda_cache"
elif [ -d "${_install_dir}/../conda_cache" ]; then
    _cache_dir="$(cd "${_install_dir}/.." && pwd)/conda_cache"
else
    echo "activate_offline_envs.sh: conda_cache directory not found near ${_install_dir}" >&2
    return 1 2>/dev/null || exit 1
fi

export NXF_CONDA_CACHEDIR="${_cache_dir}"

# Discourage Nextflow from auto-updating itself on a field machine
# without network access. Operators who do have network can override.
export NXF_OFFLINE="${NXF_OFFLINE:-true}"

echo "Nanometa Live offline envs ready: NXF_CONDA_CACHEDIR=${NXF_CONDA_CACHEDIR}"

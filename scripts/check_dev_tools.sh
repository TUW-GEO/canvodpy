#!/usr/bin/env bash
# Check that required development tools are installed.
set -euo pipefail

errors=0

for cmd in uv just; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1 | head -1)
        printf "  ✓ %-10s %s\n" "$cmd" "$version"
    else
        printf "  ✗ %-10s not found\n" "$cmd"
        errors=$((errors + 1))
    fi
done

echo ""
if [ "$errors" -gt 0 ]; then
    echo "$errors tool(s) missing. See docs/guides/contributor-setup.md for install instructions."
    exit 1
else
    echo "All development tools are installed."
fi

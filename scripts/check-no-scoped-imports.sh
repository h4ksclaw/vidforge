#!/usr/bin/env bash
# Check for scoped imports — all imports should be at top of file
# Exceptions: imports inside _get_* helper functions (lazy loading)

set -e

violations=$(grep -rn "^[[:space:]].*\bimport\b" src/ --include="*.py" | grep -v "^[^:]*:[[:space:]]*#")

if [ -z "$violations" ]; then
    exit 0
fi

while IFS=: read -r file line content; do
    # Check if this import is inside a _get_* helper function
    # Look at previous lines for the function def
    is_lazy=false
    for i in $(seq 1 5); do
        prev=$(sed -n "$((line-i))p" "$file" 2>/dev/null || true)
        if echo "$prev" | grep -q "def _get_"; then
            is_lazy=true
            break
        fi
        # Stop if we hit another function def or end of function
        if echo "$prev" | grep -qE "^[^[:space:]]"; then
            break
        fi
    done

    if [ "$is_lazy" = true ]; then
        continue
    fi

    echo "❌ Scoped import at $file:$line — all imports must be at top of file"
    echo "   $content"
    exit 1
done <<< "$violations"

exit 0

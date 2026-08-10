"""Per-module coverage gate checker.

CLAUDE.md requires:
  - skills.database, mcp_server, auth, common >= 90%
  - other modules >= 80%

Usage:
    python scripts/check_coverage.py

Reads coverage.json produced by:
    python -m pytest --cov=platform_mcp --cov-report=json -q
"""

import json
import sys
from pathlib import Path

HIGH_GATE_MODULES = {
    "platform_mcp/skills/database": 90,
    "platform_mcp/mcp_server": 90,
    "platform_mcp/auth": 90,
    "platform_mcp/common": 90,
}
DEFAULT_GATE = 80


def main() -> int:
    cov_path = Path("coverage.json")
    if not cov_path.exists():
        print("ERROR: coverage.json not found. Run: python -m pytest --cov=platform_mcp --cov-report=json -q")
        return 1

    with open(cov_path) as f:
        data = json.load(f)

    files = data.get("files", {})
    # Group by module
    module_stats: dict[str, list[tuple[str, float]]] = {}
    for filepath, info in files.items():
        parts = Path(filepath).parts
        if len(parts) < 2 or parts[0] != "platform_mcp":
            continue
        # Determine module key: platform_mcp/skills/database, platform_mcp/auth, etc.
        module = str(Path(filepath).parent)
        pct = info["summary"]["percent_covered"]
        module_stats.setdefault(module, []).append((filepath, pct))

    failures = []
    for module, entries in sorted(module_stats.items()):
        avg = sum(p for _, p in entries) / len(entries)
        gate = HIGH_GATE_MODULES.get(module, DEFAULT_GATE)
        status = "PASS" if avg >= gate else "FAIL"
        if status == "FAIL":
            failures.append((module, avg, gate))
        print(f"  [{status}] {module}: {avg:.1f}% (gate: {gate}%)")

    if failures:
        print(f"\nFAILED: {len(failures)} module(s) below gate:")
        for mod, avg, gate in failures:
            print(f"  - {mod}: {avg:.1f}% < {gate}%")
        return 1

    print("\nAll module coverage gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

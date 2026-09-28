"""List dbt models, seeds and sources that nothing consumes.

Reads a dbt manifest (run `dbt parse` first) and prints every model, seed and source whose
children in child_map are only tests (or nothing). Exposures count as consumers.

    python ../src/utils/find_unused_nodes.py                       # from game_market/
    python src/utils/find_unused_nodes.py game_market/target/manifest.json

Exposures only cover what was declared: check dashboard code for direct use before removing.
"""
import json
import sys
from pathlib import Path

CHECKED = ("model", "seed", "source")


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "target/manifest.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    project = manifest["metadata"].get("project_name")

    unused = []
    for node_id, children in manifest["child_map"].items():
        resource_type, package = node_id.split(".")[:2]
        if resource_type not in CHECKED or package != project:
            continue
        if not [c for c in children if not c.startswith("test.")]:
            unused.append(node_id)

    for node_id in sorted(unused):
        print(node_id)
    print(f"\n{len(unused)} unused node(s)", file=sys.stderr)


if __name__ == "__main__":
    main()

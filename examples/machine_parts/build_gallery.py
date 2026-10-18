"""Build one editable gallery model from the ten individual JSON models."""

import json
import re
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "00_all_machine_parts"


def main():
    files = sorted(HERE.glob("[0-9][0-9]_*.json"))
    files = [path for path in files if path.name != OUTPUT.name + ".json"]
    if len(files) != 10:
        raise ValueError(f"expected 10 part models, found {len(files)}")

    sections = ["# Ten mechanical parts, arranged in two rows of five.",
                "# Spacing: 90 in X, 110 in Y. Each part retains its own material."]
    for index, path in enumerate(files):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["mode"] != "text":
            raise ValueError(f"{path.name} must use text mode")
        source = re.sub(r"\bbody\b", f"part_{index + 1:02d}", document["source"])
        x = (index % 5 - 2) * 90
        y = 55 if index < 5 else -55
        sections.append(f"\n# {path.stem} at ({x}, {y})\n"
                        f"group station_{index + 1:02d}\n"
                        f"  position {x} {y} 0\n"
                        + "\n".join("  " + line if line else "" for line in source.rstrip().splitlines())
                        + "\nend")

    source = "\n".join(sections) + "\n"
    result = {
        "format": "smlib-model", "version": 1, "mode": "text", "source": source,
        "parameters": {"chord": 0.18, "angle": 18, "finish": "none",
                       "finishSize": 1, "exportScale": 1},
    }
    OUTPUT.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT.with_suffix(".txt").write_text(source, encoding="utf-8")
    print(f"Created {OUTPUT.name}.json and {OUTPUT.name}.txt")


if __name__ == "__main__":
    main()

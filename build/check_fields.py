import json, re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
model = root / "pbi/AdventureWorks Internet Sales.SemanticModel/definition/tables"
cols, meas = {}, {}
for f in model.glob("*.tmdl"):
    text = f.read_text(encoding="utf-8")
    t = f.stem
    cols[t] = set(c.strip("'") for c in re.findall(r"^\tcolumn (.+)$", text, re.M))
    meas[t] = set(m.strip("'") for m in re.findall(r"^\tmeasure (.+?) = ", text, re.M))

used = set()


def srcs_in(node, acc):
    if isinstance(node, dict):
        sr = node.get("SourceRef")
        if isinstance(sr, dict) and "Entity" in sr:
            acc.append(sr["Entity"])
        for v in node.values():
            srcs_in(v, acc)
    elif isinstance(node, list):
        for v in node:
            srcs_in(v, acc)


def walk(node):
    if isinstance(node, dict):
        for kind in ("Column", "Measure"):
            body = node.get(kind)
            if isinstance(body, dict) and "Property" in body:
                acc = []
                srcs_in(body.get("Expression", {}), acc)
                if acc:
                    used.add((acc[0], body["Property"], kind))
        for v in node.values():
            walk(v)
    elif isinstance(node, list):
        for v in node:
            walk(v)


for v in (root / "pbi/AdventureWorks Internet Sales.Report/definition/pages").rglob("visual.json"):
    walk(json.loads(v.read_text(encoding="utf-8")))

bad = []
for ent, prop, kind in sorted(used):
    pool = meas.get(ent, set()) if kind == "Measure" else cols.get(ent, set())
    if prop in pool:
        continue
    other = cols.get(ent, set()) if kind == "Measure" else meas.get(ent, set())
    bad.append(f"{kind} {ent}[{prop}]" + ("  (exists as other kind!)" if prop in other else ""))

print("distinct field refs:", len(used))
print("unknown fields:", "; ".join(bad) if bad else "none")
print("entities:", sorted({e for e, _, _ in used}))

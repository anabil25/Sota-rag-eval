"""Distill the 22K-line search.json swagger into a concise API map."""
import json

with open("search.json") as f:
    spec = json.load(f)

summary = {"paths": {}, "definitions": {}}

# Extract all paths with methods, operationIds, descriptions
for path, methods in {**spec.get("paths", {}), **spec.get("x-ms-paths", {})}.items():
    summary["paths"][path] = {}
    for method, details in methods.items():
        if method in ("get", "post", "put", "delete", "patch"):
            entry = {}
            if "operationId" in details:
                entry["operationId"] = details["operationId"]
            if "description" in details:
                entry["description"] = details["description"][:150]
            if "parameters" in details:
                entry["params"] = [
                    p.get("name", "?") for p in details.get("parameters", []) if isinstance(p, dict)
                ]
            summary["paths"][path][method] = entry

# Extract definitions: description, required, property names, enums, inheritance
for name, defn in spec.get("definitions", {}).items():
    entry = {}
    if "description" in defn:
        entry["description"] = defn["description"][:200]
    if "required" in defn:
        entry["required"] = defn["required"]
    if "properties" in defn:
        entry["properties"] = list(defn["properties"].keys())
    if "enum" in defn:
        entry["enum"] = defn["enum"]
    if "allOf" in defn:
        refs = [r.get("$ref", "").split("/")[-1] for r in defn["allOf"] if "$ref" in r]
        if refs:
            entry["extends"] = refs
    if "x-ms-discriminator-value" in defn:
        entry["discriminator"] = defn["x-ms-discriminator-value"]
    summary["definitions"][name] = entry

with open("search-api-map.json", "w") as f:
    json.dump(summary, f, indent=2)

print(f"Paths: {len(summary['paths'])}")
print(f"Definitions: {len(summary['definitions'])}")
print(f"Written to search-api-map.json")

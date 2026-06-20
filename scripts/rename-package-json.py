import os
import json

packages = [
    ".",
    "packages/agent",
    "packages/ai",
    "packages/catalog",
    "packages/coding-agent",
    "packages/collab-web",
    "packages/hashline",
    "packages/mnemopi",
    "packages/natives",
    "packages/snapcompact",
    "packages/stats",
    "packages/swarm-extension",
    "packages/tui",
    "packages/typescript-edit-benchmark",
    "packages/utils",
    "packages/wire",
    "python/robomp/web"
]

old_scope = "@oh-my-pi/"
new_scope = "@pk-nerdsaver-ai/"

def rename_package_json(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Load as JSON to modify keys safely, but write back as formatted text
    data = json.loads(content)
    
    # Rename name
    if "name" in data and data["name"].startswith(old_scope):
        data["name"] = data["name"].replace(old_scope, new_scope)

    # Rename in dependencies
    for dep_type in ["dependencies", "devDependencies", "peerDependencies"]:
        if dep_type in data:
            new_deps = {}
            for k, v in data[dep_type].items():
                new_key = k.replace(old_scope, new_scope) if k.startswith(old_scope) else k
                new_deps[new_key] = v
            data[dep_type] = new_deps

    # Also check workspaces catalog
    if "workspaces" in data and isinstance(data["workspaces"], dict):
        if "catalog" in data["workspaces"]:
            new_cat = {}
            for k, v in data["workspaces"]["catalog"].items():
                new_key = k.replace(old_scope, new_scope) if k.startswith(old_scope) else k
                new_cat[new_key] = v
            data["workspaces"]["catalog"] = new_cat

    # Format properly
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Renamed scope in {path}")

for p in packages:
    pkg_json = os.path.join(p, "package.json")
    if os.path.exists(pkg_json):
        rename_package_json(pkg_json)

print("Package.json scope rename done.")

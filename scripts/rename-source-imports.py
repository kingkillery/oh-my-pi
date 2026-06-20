import os

old_scope = "@oh-my-pi/"
new_scope = "@pk-nerdsaver-ai/"

extensions = (".ts", ".tsx", ".js", ".jsx", ".md", ".json", ".toml", ".patch", ".plist", ".rs", ".jsonl", ".py", ".sh", "dockerfile", ".ps1")
exclude_dirs = {
    "node_modules", "target", "dist", ".git", ".codegraph", "target",
    "python/robomp/web/node_modules"
}
exclude_files = {
    "rename-package-json.py", "rename-source-imports.py"
}

def rename_in_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        # Ignore binary files
        return

    if old_scope in content:
        updated = content.replace(old_scope, new_scope)
        with open(path, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"Updated imports in {path}")

for root, dirs, files in os.walk("."):
    # Modify dirs in-place to exclude them from recursive walk
    dirs[:] = [d for d in dirs if d not in exclude_dirs]
    
    for file in files:
        if file in exclude_files:
            continue
        # Check extensions (case-insensitive)
        if any(file.lower().endswith(ext) for ext in extensions):
            file_path = os.path.join(root, file)
            rename_in_file(file_path)

print("Source scope rename done.")

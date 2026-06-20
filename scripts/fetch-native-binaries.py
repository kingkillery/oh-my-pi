import os
import tarfile
import subprocess
import shutil

targets = [
    "linux-x64",
    "linux-arm64",
    "darwin-x64",
    "darwin-arm64",
    "win32-x64"
]

version = "16.0.6"
scope = "@oh-my-pi"
dest_dir = "packages/natives/native"

os.makedirs(dest_dir, exist_ok=True)

tmp_dir = "packages/natives/native/tmp_extract"
os.makedirs(tmp_dir, exist_ok=True)

try:
    for target in targets:
        pkg_name = f"{scope}/pi-natives-{target}@{version}"
        print(f"Downloading {pkg_name}...")
        
        # Run npm pack
        result = subprocess.run(
            ["npm", "pack", pkg_name],
            cwd=tmp_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=True
        )
        
        if result.returncode != 0:
            print(f"Failed to pack {pkg_name}: {result.stderr}")
            continue
            
        tarball_name = result.stdout.strip()
        tarball_path = os.path.join(tmp_dir, tarball_name)
        
        # Extract tarball
        with tarfile.open(tarball_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(".node"):
                    # Extract to packages/natives/native/
                    filename = os.path.basename(member.name)
                    member.name = filename # extract flat
                    tar.extract(member, dest_dir)
                    print(f"  Extracted {filename}")
                    
        # Cleanup tarball
        os.remove(tarball_path)

finally:
    # Cleanup temp dir
    shutil.rmtree(tmp_dir, ignore_errors=True)

print("Finished fetching native binaries.")

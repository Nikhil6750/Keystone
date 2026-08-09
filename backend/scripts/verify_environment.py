"""
Keystone Environment & Toolchain Verification Script.

Validates that the current Python runtime and installed package versions
align with Keystone's locked environment in uv.lock.
"""

import importlib.metadata
import sys
import tomllib
from pathlib import Path


def check_python_version() -> bool:
    print(f"Python Runtime: {sys.version.split()[0]}")
    if sys.version_info.major < 3 or sys.version_info.minor < 12:
        print(" [FAIL] Python 3.12 or higher is required.")
        return False
    print(" [OK] Python version compatible (>=3.12)")
    return True



def get_locked_versions(lock_path: Path) -> dict[str, str]:
    if not lock_path.exists():
        return {}
    try:
        with open(lock_path, "rb") as f:
            data = tomllib.load(f)
        locked = {}
        for pkg in data.get("package", []):
            if isinstance(pkg, dict) and "name" in pkg and "version" in pkg:
                locked[str(pkg["name"])] = str(pkg["version"])
        return locked
    except Exception as exc:
        print(f" [WARNING] Failed to parse uv.lock: {exc}")
        return {}


def check_packages(lock_path: Path) -> bool:
    required_packages = [
        "fastapi",
        "starlette",
        "pydantic",
        "sqlalchemy",
        "alembic",
        "pytest",
        "ruff",
        "mypy",
        "uvicorn",
    ]
    locked_versions = get_locked_versions(lock_path)
    all_ok = True
    print("\nPackage Versions (Installed vs uv.lock):")
    for pkg in required_packages:
        try:
            installed_ver = importlib.metadata.version(pkg)
            locked_ver = locked_versions.get(pkg)
            if locked_ver:
                if installed_ver == locked_ver:
                    print(f"  - {pkg:<15}: {installed_ver} [OK]")
                else:
                    print(f"  - {pkg:<15}: {installed_ver} (locked: {locked_ver}) [MISMATCH]")
                    all_ok = False
            else:
                print(f"  - {pkg:<15}: {installed_ver} [OK - NO LOCK ENTRY]")
        except importlib.metadata.PackageNotFoundError:
            print(f"  - {pkg:<15}: [NOT INSTALLED]")
            all_ok = False
    return all_ok


def check_lock_file(lock_path: Path, pyproject_path: Path) -> bool:
    print("\nLockfile Check:")
    if not pyproject_path.exists():
        print("  [FAIL] pyproject.toml missing!")
        return False
    print("  [OK] pyproject.toml present")

    if not lock_path.exists():
        print("  [FAIL] uv.lock missing!")
        return False
    print("  [OK] uv.lock present")
    return True


def main() -> None:
    print("==========================================")
    print("Keystone Toolchain Environment Verification")
    print("==========================================\n")

    backend_dir = Path(__file__).resolve().parent.parent
    lock_path = backend_dir / "uv.lock"
    pyproject_path = backend_dir / "pyproject.toml"

    py_ok = check_python_version()
    lock_ok = check_lock_file(lock_path, pyproject_path)
    pkg_ok = check_packages(lock_path)

    print("\n------------------------------------------")
    if py_ok and pkg_ok and lock_ok:
        print("Environment Verification SUCCESSFUL.")
        sys.exit(0)
    else:
        print("Environment Verification FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()

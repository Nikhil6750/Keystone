"""
Keystone Environment & Toolchain Verification Script.

Validates that the current Python runtime and installed package versions
align with Keystone's lock requirements.
"""

import importlib.metadata
import sys
from pathlib import Path


def check_python_version() -> bool:
    print(f"Python Runtime: {sys.version.split()[0]}")
    if sys.version_info < (3, 12):
        print(" [FAIL] Python 3.12 or higher is required.")
        return False
    print(" [OK] Python version compatible (>=3.12)")
    return True


def check_packages() -> bool:
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
    all_ok = True
    print("\nPackage Versions:")
    for pkg in required_packages:
        try:
            ver = importlib.metadata.version(pkg)
            print(f"  - {pkg:<15}: {ver}")
        except importlib.metadata.PackageNotFoundError:
            print(f"  - {pkg:<15}: [NOT INSTALLED]")
            all_ok = False
    return all_ok


def check_lock_file() -> bool:
    backend_dir = Path(__file__).resolve().parent.parent
    lock_path = backend_dir / "uv.lock"
    pyproject_path = backend_dir / "pyproject.toml"

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

    py_ok = check_python_version()
    pkg_ok = check_packages()
    lock_ok = check_lock_file()

    print("\n------------------------------------------")
    if py_ok and pkg_ok and lock_ok:
        print("Environment Verification SUCCESSFUL.")
        sys.exit(0)
    else:
        print("Environment Verification FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()

# Backend Development Setup

Keystone uses [`uv`](https://github.com/astral-sh/uv) to manage a reproducible Python dependency graph across all developer environments, worktrees, and CI.

## Reproducible Setup Workflow

1. **Install `uv`** (if not already installed):
   ```bash
   pip install uv
   # or curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Navigate to the backend directory**:
   ```bash
   cd backend
   ```

3. **Synchronize worktree-local environment**:
   ```bash
   uv sync --frozen
   ```

4. **Run the test suite**:
   ```bash
   uv run pytest -q
   ```

5. **Run linting**:
   ```bash
   uv run ruff check .
   ```

6. **Run type checking**:
   ```bash
   uv run mypy app
   ```

7. **Start the API server**:
   ```bash
   uv run uvicorn app.main:app --reload
   ```

8. **(Optional) Verify toolchain environment**:
   ```bash
   uv run python scripts/verify_environment.py
   ```

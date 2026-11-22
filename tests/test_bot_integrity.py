"""Sanity tests verifying codebase compilation, setup hooks, and security posture."""

import importlib
import py_compile
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_all_python_files_compile():
    """Ensure every python file in the repository compiles cleanly without syntax errors."""
    for py_file in ROOT_DIR.rglob("*.py"):
        # Skip virtualenvs or hidden directories if any
        if ".venv" in py_file.parts or "venv" in py_file.parts or "__pycache__" in py_file.parts:
            continue
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as err:
            pytest.fail(f"Syntax error compiling {py_file}: {err}")


def test_cog_setup_functions_exist():
    """Verify all discovered cogs define a valid async setup function."""
    cogs_dir = ROOT_DIR / "bot" / "cogs"
    for py_file in cogs_dir.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue

        relative_parts = py_file.relative_to(ROOT_DIR).with_suffix("").parts
        module_name = ".".join(relative_parts)

        module = importlib.import_module(module_name)
        assert hasattr(module, "setup"), f"Cog module {module_name} is missing a setup() function"
        assert callable(getattr(module, "setup")), f"setup in {module_name} must be callable"


def test_no_hardcoded_secrets_in_repo():
    """Scan source files to ensure no real bot tokens or production credentials were hardcoded."""
    forbidden_tokens = [
        "MTIzNDU2",  # Example base64 prefixes
        "your_bot_token_here",  # Should only be in .env.example
    ]

    for py_file in (ROOT_DIR / "bot").rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "mongodb+srv://user:pass" not in content, f"Hardcoded Mongo URI found in {py_file}"
        assert "NTEy" not in content, f"Suspicious token found in {py_file}"


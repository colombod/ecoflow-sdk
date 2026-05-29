"""Tests that scaffold files exist with the required content.

These tests are the RED-first verification for task-2-scaffold-pyproject-tooling.
They check that pyproject.toml, pyrightconfig.json, and .gitignore exist with
exactly the content required by the spec.
"""

import json
import tomllib
from pathlib import Path

# Resolve root = ecoflow-python/python/ (where tests/ lives)
ROOT = Path(__file__).parent.parent


class TestPyprojectToml:
    """Verify pyproject.toml exists with required structure."""

    def test_pyproject_exists(self) -> None:
        assert (ROOT / "pyproject.toml").exists(), "pyproject.toml must exist"

    def test_build_system(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        bs = data["build-system"]
        assert "setuptools>=69" in bs["requires"]
        assert "wheel" in bs["requires"]
        assert bs["build-backend"] == "setuptools.build_meta"

    def test_project_metadata(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        proj = data["project"]
        assert proj["name"] == "ecoflow-python"
        assert proj["version"] == "0.2.0"
        assert proj["requires-python"] == ">=3.11"

    def test_runtime_dependencies(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        deps = data["project"]["dependencies"]
        assert any(d.startswith("httpx") for d in deps)
        assert any(d.startswith("aiomqtt") for d in deps)

    def test_dev_optional_dependencies(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        dev_deps = data["project"]["optional-dependencies"]["dev"]
        names = [d.split(">=")[0].split("[")[0] for d in dev_deps]
        expected = [
            "pytest",
            "pytest-asyncio",
            "pytest-timeout",
            "respx",
            "ruff",
            "pyright",
            "python-dotenv",
        ]
        for required in expected:
            assert required in names, f"Missing dev dependency: {required}"

    def test_pytest_config(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        # TOML parses [tool.pytest.ini_options] as data["tool"]["pytest"]["ini_options"]
        opts = data["tool"]["pytest"]["ini_options"]
        assert opts["asyncio_mode"] == "auto"
        assert opts["testpaths"] == ["tests"]
        markers = opts["markers"]
        assert any("integration" in m for m in markers)

    def test_ruff_config(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        ruff = data["tool"]["ruff"]
        assert ruff["target-version"] == "py311"
        assert ruff["line-length"] == 88
        assert "ASYNC" in ruff["lint"]["select"]

    def test_pyright_config(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        pr = data["tool"]["pyright"]
        assert pr["pythonVersion"] == "3.11"
        assert pr["typeCheckingMode"] == "strict"

    def test_setuptools_packages_find(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        assert data["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]


class TestPyrightconfigJson:
    """Verify pyrightconfig.json exists with required content."""

    def test_pyrightconfig_exists(self) -> None:
        assert (ROOT / "pyrightconfig.json").exists(), "pyrightconfig.json must exist"

    def test_pyrightconfig_content(self) -> None:
        data = json.loads((ROOT / "pyrightconfig.json").read_text())
        assert data["include"] == ["src", "tests"]
        assert data["venvPath"] == "."
        assert data["venv"] == ".venv"
        assert data["pythonVersion"] == "3.11"
        assert data["typeCheckingMode"] == "strict"


class TestGitignore:
    """Verify .gitignore exists with required entries."""

    def test_gitignore_exists(self) -> None:
        assert (ROOT / ".gitignore").exists(), ".gitignore must exist"

    def test_gitignore_entries(self) -> None:
        content = (ROOT / ".gitignore").read_text()
        required = [
            ".venv/",
            "__pycache__/",
            "*.pyc",
            "*.egg-info/",
            "dist/",
            "build/",
            ".pytest_cache/",
            ".ruff_cache/",
            "tests/.env",
        ]
        for entry in required:
            assert entry in content, f"Missing .gitignore entry: {entry}"


class TestVenvCreated:
    """Verify uv sync created the virtual environment."""

    def test_venv_directory_exists(self) -> None:
        assert (ROOT / ".venv").is_dir(), ".venv/ must exist after uv sync --all-extras"

    def test_venv_has_pytest(self) -> None:
        pytest_bin = ROOT / ".venv" / "bin" / "pytest"
        assert pytest_bin.exists(), "pytest must be installed in .venv"

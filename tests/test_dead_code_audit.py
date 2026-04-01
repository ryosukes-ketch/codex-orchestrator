import ast
import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _all_python_files(base: Path) -> list[Path]:
    return sorted(
        path
        for path in base.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def test_package_export_surfaces_are_unique_and_resolvable() -> None:
    package_modules = [
        "app.agents",
        "app.intake",
        "app.orchestrator",
        "app.providers",
        "app.schemas",
        "app.services",
        "app.state",
    ]
    for module_name in package_modules:
        module = importlib.import_module(module_name)
        exports = list(getattr(module, "__all__", []))
        assert len(exports) == len(set(exports)), module_name
        missing = [name for name in exports if not hasattr(module, name)]
        assert missing == [], f"{module_name}: missing exports {missing}"


def test_docs_examples_artifacts_are_referenced_by_docs_or_tests() -> None:
    example_paths = sorted((ROOT / "docs" / "examples").glob("*"))
    docs_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "docs").glob("**/*.md")
    )
    tests_text = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "tests").glob("*.py")
    )
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    unreferenced: list[str] = []
    for path in example_paths:
        rel = f"docs/examples/{path.name}"
        refs = docs_text.count(rel) + tests_text.count(rel) + readme_text.count(rel)
        if refs == 0:
            unreferenced.append(rel)
    assert unreferenced == []


def test_no_orphan_private_top_level_helpers_in_app_modules() -> None:
    app_files = _all_python_files(ROOT / "app")
    test_files = _all_python_files(ROOT / "tests")
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in app_files + test_files)

    orphans: list[str] = []
    for path in app_files:
        if path.name == "__init__.py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if (
                isinstance(node, ast.FunctionDef)
                and node.name.startswith("_")
                and not node.name.startswith("__")
            ):
                pattern = re.compile(rf"\b{re.escape(node.name)}\b")
                if len(pattern.findall(corpus)) <= 1:
                    orphans.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")
    assert orphans == []


def test_env_example_keeps_provider_keys_in_sync_with_supported_adapters() -> None:
    env_lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    env_keys = {
        line.split("=", 1)[0].strip()
        for line in env_lines
        if line.strip() and not line.strip().startswith("#") and "=" in line
    }
    provider_keys = {key for key in env_keys if key.endswith("_API_KEY")}

    expected = {"OPENAI_API_KEY", "GEMINI_API_KEY", "GROK_API_KEY"}
    assert provider_keys == expected

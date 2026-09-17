"""The image ships an explicit file list, and CI does not build it on a PR.

PR #32 added embed.py, retrieval.py, schedule.py, oral.py and tts.py, went green, merged, and every
deploy that day died with ModuleNotFoundError before the container could bind port 8080 — because the
Dockerfile's COPY line had not grown with it. CI could not catch it: CI has the whole repository, and
only the image is missing the files.

This is that missing check, as a unit test rather than a docker build: whatever the image ships must
be able to import what it imports.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Deliberately not shipped: one-off scripts run by hand against a database, never imported by the app.
NOT_SHIPPED_ON_PURPOSE = {"import_claude_export", "migrate_sqlite", "migrate_storage"}


def _shipped_modules() -> set[str]:
    """Root-level .py modules the Dockerfile copies into the image."""
    shipped = set()
    for line in ROOT.joinpath("Dockerfile").read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        for token in line.split()[1:]:
            if token.endswith(".py") and "/" not in token:
                shipped.add(token[:-3])
    return shipped


def _root_imports(module: str) -> set[str]:
    """Top-level module names imported by a root module, at any depth in the file."""
    names = set()
    for node in ast.walk(ast.parse(ROOT.joinpath(module + ".py").read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_image_ships_every_module_it_imports():
    """A module in the image must not import a root module the image left behind."""
    shipped = _shipped_modules()
    assert "run" in shipped, "the Dockerfile no longer copies run.py; this test is reading it wrong"
    root_modules = {p.stem for p in ROOT.glob("*.py")}

    missing = {
        module: sorted(_root_imports(module) & (root_modules - shipped))
        for module in sorted(shipped)
        if _root_imports(module) & (root_modules - shipped)
    }
    assert not missing, (
        "these modules are in the image but import root modules that are not:\n"
        + "\n".join(f"  {m} imports {', '.join(v)}" for m, v in missing.items())
        + "\nAdd them to the COPY line in the Dockerfile."
    )


def test_every_module_the_image_names_actually_exists():
    """A typo or a rename in the COPY line fails the build, so catch it here instead."""
    absent = sorted(m for m in _shipped_modules() if not ROOT.joinpath(m + ".py").exists())
    assert not absent, f"the Dockerfile copies files that do not exist: {absent}"


def test_unshipped_root_modules_are_the_ones_we_meant_to_leave_out():
    """A new root module should be a deliberate decision, not an oversight.

    If this fails, either add the module to the Dockerfile's COPY line or, if it is a one-off script,
    add it to NOT_SHIPPED_ON_PURPOSE above.
    """
    root_modules = {p.stem for p in ROOT.glob("*.py")}
    unaccounted = sorted(root_modules - _shipped_modules() - NOT_SHIPPED_ON_PURPOSE)
    assert not unaccounted, (
        f"new root modules are neither shipped nor listed as deliberately excluded: {unaccounted}"
    )


def test_the_start_script_and_env_check_are_shipped():
    """scripts/start.sh is the entrypoint and scripts/check_env.py is imported by run.py."""
    dockerfile = ROOT.joinpath("Dockerfile").read_text()
    assert re.search(r"^COPY .*scripts/check_env\.py", dockerfile, re.M), "check_env.py is not copied"
    assert re.search(r"^COPY .*scripts/start\.sh", dockerfile, re.M), "start.sh is not copied"

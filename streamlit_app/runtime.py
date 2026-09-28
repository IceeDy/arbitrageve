from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def load_repo_module(module_name: str, relative_path: str, force: bool = False):
    """Load a repository module into its canonical import name.

    Streamlit Cloud can retain an installed/cached package module across
    reruns. Replacing sys.modules with the source-tree module guarantees that
    the app and its pages use the same ORM classes and loader functions.
    """
    path = (SRC_DIR / relative_path).resolve()
    existing = sys.modules.get(module_name)
    if not force and existing is not None:
        existing_path = getattr(existing, "__file__", None)
        if existing_path and Path(existing_path).resolve() == path:
            return existing

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load repository module from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Load dependencies in order so SQLAlchemy Base and ORM models have one identity.
load_repo_module("arbitrageve.db.database", "arbitrageve/db/database.py")
load_repo_module("arbitrageve.db.models", "arbitrageve/db/models.py")
load_repo_module("arbitrageve.sde.loader", "arbitrageve/sde/loader.py")
load_repo_module("arbitrageve.sde.routes", "arbitrageve/sde/routes.py")
load_repo_module("arbitrageve.services.opportunities", "arbitrageve/services/opportunities.py", force=True)

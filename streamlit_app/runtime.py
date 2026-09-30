from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"

# Streamlit Cloud exposes deployment configuration through st.secrets rather
# than the process environment. The application package uses pydantic-settings
# and reads environment variables, so bridge the supported deployment keys
# before loading any repository module that instantiates Settings.
_STREAMLIT_SECRET_ENV_MAP = {
    "DATABASE_URL": "DATABASE_URL",
    "ESI_BASE_URL": "ESI_BASE_URL",
    "ESI_USER_AGENT": "ESI_USER_AGENT",
    "CAPITAL_ISK": "CAPITAL_ISK",
    "CARGO_M3": "CARGO_M3",
    "MARKET_MAX_REGIONS_PER_RUN": "MARKET_MAX_REGIONS_PER_RUN",
    "MARKET_REGION_PRIORITY": "MARKET_REGION_PRIORITY",
}

_DATABASE_URL_SECRET_PATHS = (
    ("DATABASE_URL",),
    ("database_url",),
    ("database", "url"),
    ("connections", "postgresql", "url"),
    ("connections", "postgres", "url"),
)


def _read_secret_path(secrets, path: tuple[str, ...]):
    current = secrets
    for key in path:
        try:
            current = current[key]
        except (KeyError, TypeError):
            return None
    return current


def _resolve_database_url(secrets) -> str | None:
    """Resolve a PostgreSQL URL from common Streamlit secrets layouts."""
    for path in _DATABASE_URL_SECRET_PATHS:
        value = _read_secret_path(secrets, path)
        if value:
            return str(value)
    return None


def _configure_streamlit_environment() -> None:
    """Expose supported Streamlit secrets as environment variables.

    Existing environment variables always win, which keeps local execution
    and other deployment environments unchanged. DATABASE_URL is also accepted
    from the common [database] and [connections.postgresql] Streamlit layouts.

    A missing local secrets.toml is normal in CI and local unit tests; in that
    case repository configuration continues to be resolved by pydantic-settings
    from the process environment or .env file.
    """
    try:
        import streamlit as st
        from streamlit.errors import StreamlitSecretNotFoundError
    except ImportError:
        return

    try:
        secrets = st.secrets
        database_url = (
            _resolve_database_url(secrets)
            if "DATABASE_URL" not in os.environ
            else None
        )

        if database_url and "DATABASE_URL" not in os.environ:
            os.environ["DATABASE_URL"] = database_url

        for env_name, secret_name in _STREAMLIT_SECRET_ENV_MAP.items():
            if env_name == "DATABASE_URL" or env_name in os.environ:
                continue
            if secret_name not in secrets:
                continue
            os.environ[env_name] = str(secrets[secret_name])
    except StreamlitSecretNotFoundError:
        return

    if "DATABASE_URL" not in os.environ:
        try:
            has_secrets = bool(st.secrets)
        except StreamlitSecretNotFoundError:
            return
        if has_secrets:
            raise RuntimeError(
                "ArbitrageVE requires DATABASE_URL in Streamlit secrets. "
                "Add a root-level DATABASE_URL, or [database].url / "
                "[connections.postgresql].url pointing to the persistent PostgreSQL database."
            )


_configure_streamlit_environment()


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
load_repo_module(
    "arbitrageve.services.opportunities",
    "arbitrageve/services/opportunities.py",
    force=True,
)

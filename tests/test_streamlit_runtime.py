from streamlit_app.runtime import _resolve_database_url


def test_resolve_database_url_accepts_root_level_secret():
    secrets = {"DATABASE_URL": "postgresql+psycopg://user:pass@host/db"}

    assert _resolve_database_url(secrets) == secrets["DATABASE_URL"]


def test_resolve_database_url_accepts_common_streamlit_connection_layout():
    secrets = {
        "connections": {
            "postgresql": {
                "url": "postgresql+psycopg://user:pass@host/db",
            }
        }
    }

    assert _resolve_database_url(secrets) == secrets["connections"]["postgresql"]["url"]


def test_resolve_database_url_accepts_database_section():
    secrets = {
        "database": {
            "url": "postgresql+psycopg://user:pass@host/db",
        }
    }

    assert _resolve_database_url(secrets) == secrets["database"]["url"]

import importlib


def test_settings_require_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ESI_BASE_URL", "https://esi.evetech.net")

    import arbitrageve.config.settings as settings_module

    monkeypatch.setattr(settings_module.Settings, "model_config", settings_module.Settings.model_config)

    with monkeypatch.context() as ctx:
        ctx.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@host/db")
        module = importlib.reload(settings_module)
        assert module.settings.database_url.startswith("postgresql+psycopg://")

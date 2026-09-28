from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///data/arbitrageve.db'
    esi_base_url: str = 'https://esi.evetech.net/latest'
    esi_user_agent: str = 'ArbitrageVE/0.1.0 contact: your-email@example.com'
    capital_isk: float = 100000000
    cargo_m3: float = 400

settings = Settings()

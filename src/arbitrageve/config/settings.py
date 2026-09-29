from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/arbitrageve.db"
    esi_base_url: str = "https://esi.evetech.net"
    esi_user_agent: str = "ArbitrageVE/0.1.0 contact: your-email@example.com"
    capital_isk: float = 100_000_000
    cargo_m3: float = 400

    # Base interval used by the adaptive order-volume scheduler.
    market_refresh_minutes: int = 60
    market_refresh_min_minutes: int = 15
    market_refresh_max_minutes: int = 360
    market_refresh_reference_orders: int = 50_000
    market_refresh_order_exponent: float = 0.5
    market_max_regions_per_run: int = 2
    market_region_priority: str = "The Forge,Domain,Sinq Laison,Heimatar,Metropolis,Essence,Tash-Murkon,Everyshore"

settings = Settings()

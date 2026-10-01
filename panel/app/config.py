from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    technitium_url: str = "http://technitium:5380"
    panel_session_secret: str = "change-me-lab-secret"
    session_cookie: str = "dns_panel_token"
    session_max_age: int = 60 * 60 * 8
    blocky_config_path: str = "/var/lib/blocky/config.yml"
    blocky_upstream: str = "blocky"
    panel_data_dir: str = "/var/lib/panel"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

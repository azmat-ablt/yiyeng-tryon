from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VTON_", extra="ignore")

    data_dir: Path = Path("data")
    public_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000"

    inference_provider: str = "stub"
    local_inference_url: str = "http://127.0.0.1:9000"
    remote_api_url: str = ""
    remote_api_key: str = ""

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

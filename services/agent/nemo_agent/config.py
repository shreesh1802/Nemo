import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model_fast: str
    model_standard: str
    model_deep: str
    tavily_api_key: str
    db_path: str

    def model_for(self, tier: str) -> str:
        model = {
            "fast": self.model_fast,
            "standard": self.model_standard,
            "deep": self.model_deep,
        }[tier]
        # Unset tiers fall back to the next one up so a single model still works.
        return model or self.model_standard or self.model_fast or self.model_deep


def load_settings() -> Settings:
    return Settings(
        api_key=os.getenv("NEBIUS_API_KEY", ""),
        base_url=os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1"),
        model_fast=os.getenv("NEMO_MODEL_FAST", ""),
        model_standard=os.getenv("NEMO_MODEL_STANDARD", ""),
        model_deep=os.getenv("NEMO_MODEL_DEEP", ""),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        db_path=os.getenv("NEMO_DB_PATH", "nemo_memory.sqlite3"),
    )

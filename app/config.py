from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Solara Backend"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/solara_dev"
    DATABASE_URL_SYNC: str = "postgresql://postgres:postgres@localhost:5432/solara_dev"

    # Auth — RS256 JWT (llave privada firma, pública verifica)
    JWT_PRIVATE_KEY_PATH: str = "app/assets/keys/private_key.pem"
    JWT_PUBLIC_KEY_PATH: str = "app/assets/keys/public_key_local.pem"
    JWT_ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Fallback HS256 legacy (solo para verificar tokens viejos durante migración)
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8081"]

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL_NL2SQL: str = "gpt-4.1-mini"
    OPENAI_MODEL_INTERPRET: str = "gpt-4.1-mini"
    OPENAI_MAX_ROWS: int = 500

    # Gemini TTS
    GEMINI_API_KEY: str = ""
    GEMINI_TTS_MODEL: str = "gemini-2.5-flash-preview-tts"
    GEMINI_TTS_VOICE: str = "Leda"

    # Weather API
    WEATHER_API_KEY: str = ""
    WEATHER_CACHE_TTL_MINUTES: int = 30

    # Uploads
    UPLOAD_DIR: str = "uploads"
    MAX_IMAGE_SIZE: int = 5_242_880  # 5MB
    ALLOWED_IMAGE_TYPES: list[str] = ["image/jpeg", "image/png", "image/webp"]

    # DB Timezone
    DB_TIMEZONE: str = "America/Mexico_City"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

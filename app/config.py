from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Core ──────────────────────────────────────────────────────────────────
    supabase_url: str
    supabase_service_key: str
    openai_api_key: str          # used for insight embeddings only
    # ── HTTP server ───────────────────────────────────────────────────────────
    base_url: str = "http://localhost:8083"
    # Public URL of this server, e.g. "https://abc.trycloudflare.com"
    # Used to build the Google OAuth redirect_uri.

    # ── Google OAuth ──────────────────────────────────────────────────────────
    google_client_id: str = ""
    google_client_secret: str = ""

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt_secret: str = ""
    # Strong random string. Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

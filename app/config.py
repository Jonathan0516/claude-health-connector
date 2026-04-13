from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    openai_api_key: str          # used for insight embeddings only
    default_user_id: str         # the single local user's UUID in Supabase

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

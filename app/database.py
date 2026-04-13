from supabase import create_client, Client
from app.config import settings

_client: Client | None = None


def _validate_supabase_service_key(key: str) -> None:
    # Service role / anon keys are JWTs. Reject publishable keys early with
    # a clearer message than the SDK's generic "Invalid API key".
    if key.startswith("sb_publishable_"):
        raise ValueError(
            "SUPABASE_SERVICE_KEY is using a publishable key. "
            "Tests need the Supabase service role JWT instead."
        )
    if key.count(".") < 2:
        raise ValueError(
            "SUPABASE_SERVICE_KEY must be a JWT-style key from Supabase "
            "(for example the service_role key), not a publishable key."
        )


def get_db() -> Client:
    global _client
    if _client is None:
        _validate_supabase_service_key(settings.supabase_service_key)
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _client

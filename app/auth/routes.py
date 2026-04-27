"""
OAuth 2.0 authorization server endpoints — PKCE authorization code flow.

Flow
────
1. Claude.ai → GET /authorize?redirect_uri=...&state=...&code_challenge=...
2. We save those params (keyed by internal_state), redirect user to Google.
3. Google → GET /callback?code=...&state=internal_state
4. We exchange Google code → get user → issue short-lived auth_code
   → redirect to Claude.ai's redirect_uri?code=auth_code&state=original_state
5. Claude.ai → POST /token  {code, code_verifier}
6. We verify PKCE, return JWT as access_token.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, HTMLResponse
from starlette.routing import Route

from app.config import settings
from app.auth import google as google_oauth
from app.auth import jwt_utils
from app.dal import users as users_dal


# ─────────────────────────────────────────────────────────────────────────────
# In-memory stores (single-process; fine for this deployment)
# ─────────────────────────────────────────────────────────────────────────────

# state → {client_state, redirect_uri, code_challenge, code_challenge_method, expires_at}
_pending: dict[str, dict] = {}

# auth_code → {user_id, code_challenge, code_challenge_method, expires_at}
_codes: dict[str, dict] = {}

_PENDING_TTL = 600   # 10 min for user to complete login
_CODE_TTL    = 120   # 2 min to exchange code for token


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _google_callback_uri() -> str:
    return f"{settings.base_url.rstrip('/')}/callback"


# ─────────────────────────────────────────────────────────────────────────────
# Discovery endpoints
# ─────────────────────────────────────────────────────────────────────────────

async def oauth_metadata(request: Request) -> JSONResponse:
    base = settings.base_url.rstrip("/")
    return JSONResponse({
        "issuer":                                base,
        "authorization_endpoint":                f"{base}/authorize",
        "token_endpoint":                        f"{base}/token",
        "registration_endpoint":                 f"{base}/register",
        "response_types_supported":              ["code"],
        "grant_types_supported":                 ["authorization_code"],
        "code_challenge_methods_supported":      ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


async def openid_configuration(request: Request) -> JSONResponse:
    base = settings.base_url.rstrip("/")
    return JSONResponse({
        "issuer":                                base,
        "authorization_endpoint":                f"{base}/authorize",
        "token_endpoint":                        f"{base}/token",
        "registration_endpoint":                 f"{base}/register",
        "response_types_supported":              ["code"],
        "grant_types_supported":                 ["authorization_code"],
        "code_challenge_methods_supported":      ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "subject_types_supported":               ["public"],
        "id_token_signing_alg_values_supported": ["HS256"],
    })


async def protected_resource_metadata(request: Request) -> JSONResponse:
    base = settings.base_url.rstrip("/")
    return JSONResponse({
        "resource":              base,
        "authorization_servers": [base],
    })


# ─────────────────────────────────────────────────────────────────────────────
# OAuth endpoints
# ─────────────────────────────────────────────────────────────────────────────

async def authorize(request: Request) -> RedirectResponse | HTMLResponse:
    """
    Step 1 — Claude.ai sends the user here.
    Save PKCE params + redirect_uri, then send user to Google.
    """
    if not settings.google_client_id:
        return HTMLResponse("<h2>Google OAuth not configured.</h2>", status_code=503)

    client_redirect_uri  = request.query_params.get("redirect_uri", "")
    client_state         = request.query_params.get("state", "")
    code_challenge       = request.query_params.get("code_challenge", "")
    code_challenge_method = request.query_params.get("code_challenge_method", "S256")

    # Use a fresh internal state so we can look up the pending session in /callback.
    internal_state = secrets.token_urlsafe(24)
    _pending[internal_state] = {
        "client_state":          client_state,
        "redirect_uri":          client_redirect_uri,
        "code_challenge":        code_challenge,
        "code_challenge_method": code_challenge_method,
        "expires_at":            time.time() + _PENDING_TTL,
    }

    google_url = google_oauth.get_auth_url(
        client_id=settings.google_client_id,
        redirect_uri=_google_callback_uri(),
        state=internal_state,
    )
    return RedirectResponse(google_url)


async def callback(request: Request) -> RedirectResponse | HTMLResponse:
    """
    Step 3 — Google redirects here with ?code=...&state=internal_state.
    Exchange Google code → get user → issue auth_code → redirect to Claude.ai.
    """
    if not settings.google_client_id:
        return HTMLResponse("<h2>Google OAuth not configured.</h2>", status_code=503)

    error = request.query_params.get("error")
    if error:
        return HTMLResponse(f"<h2>Google login failed: {error}</h2>", status_code=400)

    google_code    = request.query_params.get("code")
    internal_state = request.query_params.get("state", "")

    if not google_code:
        return HTMLResponse("<h2>Missing authorization code from Google.</h2>", status_code=400)

    # Retrieve the pending session
    pending = _pending.pop(internal_state, None)
    if not pending or pending["expires_at"] < time.time():
        return HTMLResponse("<h2>Session expired or invalid state. Please try again.</h2>", status_code=400)

    # Exchange Google code for user info
    try:
        token_data = await google_oauth.exchange_code(
            settings.google_client_id,
            settings.google_client_secret,
            google_code,
            _google_callback_uri(),
        )
        userinfo = await google_oauth.get_userinfo(token_data["access_token"])
    except Exception as exc:
        return HTMLResponse(f"<h2>OAuth error: {exc}</h2>", status_code=500)

    email        = userinfo.get("email", "")
    display_name = userinfo.get("name") or email.split("@")[0]
    user = _find_or_create_user(email, display_name)

    # Issue a short-lived authorization code for Claude.ai to exchange
    auth_code = secrets.token_urlsafe(32)
    _codes[auth_code] = {
        "user_id":               user["id"],
        "code_challenge":        pending["code_challenge"],
        "code_challenge_method": pending["code_challenge_method"],
        "expires_at":            time.time() + _CODE_TTL,
    }

    # Redirect to Claude.ai's redirect_uri with the code
    client_redirect = pending["redirect_uri"]
    client_state    = pending["client_state"]

    if client_redirect:
        sep = "&" if "?" in client_redirect else "?"
        return RedirectResponse(
            f"{client_redirect}{sep}code={auth_code}&state={client_state}",
            status_code=302,
        )

    # Fallback: no redirect_uri (e.g. manual testing) — show success page
    jwt_token = jwt_utils.issue_token(user["id"])
    return HTMLResponse(_success_page(display_name, jwt_token, client_state))


async def token_endpoint(request: Request) -> JSONResponse:
    """
    Step 5 — Claude.ai POSTs {code, code_verifier, grant_type} here.
    Verify PKCE, return JWT as access_token.
    """
    try:
        body = await request.form()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    grant_type    = body.get("grant_type")
    code          = body.get("code", "")
    code_verifier = body.get("code_verifier", "")

    if grant_type != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    issued = _codes.pop(code, None)
    if not issued or issued["expires_at"] < time.time():
        return JSONResponse({"error": "invalid_grant", "error_description": "Code expired or not found"}, status_code=400)

    # Verify PKCE (S256)
    challenge = issued.get("code_challenge", "")
    if challenge:
        computed = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()
        if computed != challenge:
            return JSONResponse({"error": "invalid_grant", "error_description": "PKCE verification failed"}, status_code=400)

    jwt_token = jwt_utils.issue_token(issued["user_id"])
    return JSONResponse({
        "access_token": jwt_token,
        "token_type":   "bearer",
        "expires_in":   settings.jwt_expire_days * 86400,
    })


async def register_client(request: Request) -> JSONResponse:
    """RFC 7591 Dynamic Client Registration — accepts any client."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    redirect_uris = body.get("redirect_uris", [])
    seed      = (redirect_uris[0] if redirect_uris else "default").encode()
    client_id = "mcp-" + hashlib.sha256(seed).hexdigest()[:16]

    return JSONResponse({
        "client_id":                  client_id,
        "client_id_issued_at":        0,
        "redirect_uris":              redirect_uris,
        "grant_types":                ["authorization_code"],
        "response_types":             ["code"],
        "token_endpoint_auth_method": "none",
    }, status_code=201)


async def me(request: Request) -> JSONResponse:
    """Debug: return the user behind the current Bearer token."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"error": "No Bearer token"}, status_code=401)
    try:
        user_id = jwt_utils.validate_token(auth[7:])
        user = users_dal.get_user(user_id)
        return JSONResponse(user or {"error": "user not found"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_or_create_user(email: str, display_name: str) -> dict:
    db_users = users_dal.list_users()
    for u in db_users:
        if u.get("email") == email:
            return u
    return users_dal.create_user(display_name=display_name, email=email)


def _success_page(name: str, token: str, state: str) -> str:
    """Fallback page when no redirect_uri is present (e.g. manual testing)."""
    import json
    payload = json.dumps({"access_token": token, "token_type": "bearer", "state": state})
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Health Connector — Login successful</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px">
  <h2>✓ Logged in as {name}</h2>
  <p>You can close this window.</p>
  <script>
    if (window.opener) {{
      window.opener.postMessage({payload}, "*");
      setTimeout(() => window.close(), 1500);
    }}
  </script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Route list
# ─────────────────────────────────────────────────────────────────────────────

AUTH_ROUTES = [
    Route("/.well-known/oauth-authorization-server", oauth_metadata),
    Route("/.well-known/oauth-protected-resource",   protected_resource_metadata),
    Route("/.well-known/openid-configuration",       openid_configuration),
    Route("/authorize",                               authorize),
    Route("/callback",                                callback),
    Route("/token",                                   token_endpoint, methods=["POST"]),
    Route("/register",                                register_client, methods=["POST"]),
    Route("/me",                                      me),
]

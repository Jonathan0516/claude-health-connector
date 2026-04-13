"""
OAuth 2.0 authorization server endpoints.

Mounted on the FastMCP ASGI app at startup.

Endpoints
─────────
GET  /.well-known/oauth-authorization-server  → OAuth metadata (MCP discovery)
GET  /authorize                               → redirect to Google login
GET  /callback                                → handle Google callback, issue JWT
GET  /me                                      → return current user info (debug)

After successful login the browser receives a page that delivers the JWT
back to Claude.ai via the standard OAuth authorization_code flow.
"""

from __future__ import annotations

import json
import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, HTMLResponse
from starlette.routing import Route

from app.config import settings
from app.auth import google as google_oauth
from app.auth import jwt_utils
from app.dal import users as users_dal


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _redirect_uri() -> str:
    return f"{settings.base_url.rstrip('/')}/callback"


def _oauth_not_configured() -> JSONResponse:
    return JSONResponse(
        {"error": "Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env"},
        status_code=503,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint handlers
# ─────────────────────────────────────────────────────────────────────────────

async def oauth_metadata(request: Request) -> JSONResponse:
    """
    MCP OAuth discovery endpoint.
    Claude.ai reads this to know where to send users for authorization.
    """
    base = settings.base_url.rstrip("/")
    return JSONResponse({
        "issuer":                                base,
        "authorization_endpoint":                f"{base}/authorize",
        "token_endpoint":                        f"{base}/token",
        "response_types_supported":              ["code"],
        "grant_types_supported":                 ["authorization_code"],
        "code_challenge_methods_supported":      ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


async def authorize(request: Request) -> RedirectResponse:
    """
    Start Google OAuth flow.
    Preserves the original OAuth state param from Claude.ai so it can be
    threaded through the callback intact.
    """
    if not settings.google_client_id:
        return HTMLResponse("<h2>OAuth not configured on this server.</h2>", status_code=503)

    # Pass Claude.ai's state through so it can match the response
    upstream_state = request.query_params.get("state", secrets.token_urlsafe(16))

    url = google_oauth.get_auth_url(
        client_id=settings.google_client_id,
        redirect_uri=_redirect_uri(),
        state=upstream_state,
    )
    return RedirectResponse(url)


async def callback(request: Request) -> HTMLResponse:
    """
    Google redirects here after login.

    1. Exchange auth code → Google access token
    2. Fetch user email + name from Google
    3. Look up user in Supabase (by email), create if new
    4. Issue a JWT
    5. Deliver the JWT back to Claude.ai via the OAuth code exchange page
    """
    if not settings.google_client_id:
        return _oauth_not_configured()

    error = request.query_params.get("error")
    if error:
        return HTMLResponse(f"<h2>Google login failed: {error}</h2>", status_code=400)

    code  = request.query_params.get("code")
    state = request.query_params.get("state", "")
    if not code:
        return HTMLResponse("<h2>Missing authorization code.</h2>", status_code=400)

    try:
        token_data   = await google_oauth.exchange_code(
            settings.google_client_id,
            settings.google_client_secret,
            code,
            _redirect_uri(),
        )
        userinfo = await google_oauth.get_userinfo(token_data["access_token"])
    except Exception as exc:
        return HTMLResponse(f"<h2>OAuth error: {exc}</h2>", status_code=500)

    email        = userinfo.get("email", "")
    display_name = userinfo.get("name") or email.split("@")[0]

    # Find or create user by email
    user = _find_or_create_user(email, display_name)
    jwt_token = jwt_utils.issue_token(user["id"])

    # Return a page that delivers the token back to Claude.ai
    # Claude.ai expects the standard OAuth implicit / code flow response.
    return HTMLResponse(_success_page(display_name, jwt_token, state))


async def token_endpoint(request: Request) -> JSONResponse:
    """
    OAuth token endpoint — Claude.ai may POST here to exchange a code.
    We use implicit delivery via the callback page, but expose this
    endpoint for spec compliance.
    """
    body = await request.form()
    grant_type = body.get("grant_type")
    if grant_type != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    # In our flow the JWT is delivered directly on the callback page.
    # This endpoint is a no-op stub for spec compliance.
    return JSONResponse({"error": "use_callback_flow"}, status_code=400)


async def me(request: Request) -> JSONResponse:
    """Debug: return the user behind the current Bearer token."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"error": "No Bearer token"}, status_code=401)
    try:
        import jwt as pyjwt
        user_id = jwt_utils.validate_token(auth[7:])
        user = users_dal.get_user(user_id)
        return JSONResponse(user or {"error": "user not found"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_or_create_user(email: str, display_name: str) -> dict:
    """Look up user by email; create if this is their first login."""
    db_users = users_dal.list_users()
    for u in db_users:
        if u.get("email") == email:
            return u
    return users_dal.create_user(display_name=display_name, email=email)


def _success_page(name: str, token: str, state: str) -> str:
    """
    HTML page shown after successful login.
    Delivers the JWT as an access_token to the opener (Claude.ai tab)
    via postMessage, then closes itself.
    """
    payload = json.dumps({
        "access_token": token,
        "token_type":   "bearer",
        "state":        state,
    })
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Health Connector — Login successful</title></head>
<body style="font-family:sans-serif;text-align:center;padding:60px">
  <h2>✓ Logged in as {name}</h2>
  <p>You can close this window.</p>
  <script>
    // Deliver token back to the Claude.ai opener
    if (window.opener) {{
      window.opener.postMessage({payload}, "*");
      setTimeout(() => window.close(), 1500);
    }}
  </script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Route list — imported by mcp_server._make_http_app()
# ─────────────────────────────────────────────────────────────────────────────

AUTH_ROUTES = [
    Route("/.well-known/oauth-authorization-server", oauth_metadata),
    Route("/authorize",                               authorize),
    Route("/callback",                                callback),
    Route("/token",                                   token_endpoint, methods=["POST"]),
    Route("/me",                                      me),
]

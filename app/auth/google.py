"""
Google OAuth 2.0 client (minimal, no heavy SDK).

Flow:
  1. get_auth_url()      → redirect user to Google login page
  2. exchange_code()     → swap Google auth code for access token
  3. get_userinfo()      → fetch user's email + name + google_id
"""

from __future__ import annotations
from urllib.parse import urlencode
import httpx

GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
SCOPES = "openid email profile"


def get_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Build the Google OAuth authorization URL to redirect the user to."""
    params = {
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         SCOPES,
        "state":         state,
        "access_type":   "online",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict:
    """
    Exchange an authorization code for an access token.
    Returns the token response JSON from Google.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     client_id,
                "client_secret": client_secret,
                "redirect_uri":  redirect_uri,
                "grant_type":    "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_userinfo(access_token: str) -> dict:
    """
    Fetch the authenticated user's profile from Google.

    Returns dict with: id, email, name, picture, verified_email
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()

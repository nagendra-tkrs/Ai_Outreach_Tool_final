import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.auth.security import verify_request_auth

logger = logging.getLogger("ai_outreach.auth")

# Paths that are public and require no authentication
EXACT_PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# Prefix paths that are public and accessed externally by email clients or OAuth redirects
PUBLIC_PREFIXES = (
    "/api/track/open/",
    "/api/track/click/",
    "/api/track/unsubscribe/",
    "/api/settings/gmail/oauth/callback",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Allow all CORS preflight OPTIONS requests to proceed unimpeded
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path.rstrip("/")
        # Re-add root slash if empty
        if not path:
            path = "/"

        # 2. Allow requests outside /api (e.g. root docs or static files if any)
        if not path.startswith("/api"):
            return await call_next(request)

        # 3. Check exact public allowlist
        if path in EXACT_PUBLIC_PATHS:
            return await call_next(request)

        # 4. Check public path prefixes (tracking, OAuth callback)
        for prefix in PUBLIC_PREFIXES:
            if request.url.path.startswith(prefix):
                return await call_next(request)

        # 5. Protected endpoint: verify credentials
        auth_header = request.headers.get("authorization")
        api_key_header = request.headers.get("x-api-key")

        is_valid, user = verify_request_auth(
            auth_header=auth_header,
            api_key_header=api_key_header,
        )

        if not is_valid:
            logger.warning(
                f"Unauthorized access attempt to {request.method} {request.url.path} from {request.client.host if request.client else 'unknown'}"
            )
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "message": "Authentication required. Please provide a valid Bearer token or API key.",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Attach authenticated user identity to request state
        request.state.user = user
        return await call_next(request)

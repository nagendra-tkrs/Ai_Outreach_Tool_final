import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

# Security: Defaults to 127.0.0.1 (localhost) to prevent accidental unencrypted
# exposure on local area networks (LAN/Wi-Fi). If deploying for remote access with
# HOST=0.0.0.0, the backend must be guarded behind a reverse proxy (e.g. Nginx, Caddy,
# or Cloudflare Tunnel) terminating TLS/HTTPS and enforcing network access controls.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000


def get_server_config():
    """Return runtime host and port configuration."""
    port = int(os.getenv("PORT", DEFAULT_PORT))
    host = os.getenv("HOST", DEFAULT_HOST)
    return host, port


if __name__ == "__main__":
    host, port = get_server_config()
    uvicorn.run("app.main:app", host=host, port=port, reload=True)


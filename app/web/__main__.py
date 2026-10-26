"""Run with python -m app.web; TLS is terminated by a configured reverse proxy."""
import uvicorn
from app.web.config import get_web_settings


if __name__ == '__main__':
    settings = get_web_settings()
    uvicorn.run(
        'app.web.app:app', host=settings.host, port=settings.port, proxy_headers=True,
        forwarded_allow_ips=settings.trusted_proxies,
        access_log=False,
    )

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from arbitrageve.config.settings import settings


class ESIClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.esi_user_agent,
                "X-Compatibility-Date": "2025-09-30",
            }
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=8))
    def get(self, endpoint, params=None):
        response = self.session.get(
            settings.esi_base_url.rstrip("/") + "/" + endpoint.lstrip("/"),
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=8))
    def post(self, endpoint, json=None, params=None):
        response = self.session.post(
            settings.esi_base_url.rstrip("/") + "/" + endpoint.lstrip("/"),
            params=params,
            json=json,
            timeout=30,
        )
        response.raise_for_status()
        return response

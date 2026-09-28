import time

import requests

from arbitrageve.config.settings import settings


class ESIRequestError(requests.HTTPError):
    """HTTP error from ESI with the response body preserved for diagnostics."""


class ESIClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.esi_user_agent,
                "X-Compatibility-Date": "2025-09-30",
            }
        )

    def _request(self, method, endpoint, params=None, json=None):
        url = settings.esi_base_url.rstrip("/") + "/" + endpoint.lstrip("/")
        last_error = None

        for attempt in range(3):
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    timeout=30,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= 2:
                    raise
                time.sleep(2**attempt)
                continue

            if 200 <= response.status_code < 300:
                return response

            # ESI explicitly uses 429 for rate limiting and 5xx for server
            # failures. These are the only HTTP statuses we retry.
            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_error = ESIRequestError(
                    f"ESI returned HTTP {response.status_code}: "
                    f"{response.text[:1000]}"
                )
                if attempt >= 2:
                    raise last_error
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = min(float(retry_after), 30.0) if retry_after else 2**attempt
                except ValueError:
                    delay = 2**attempt
                time.sleep(delay)
                continue

            raise ESIRequestError(
                f"ESI returned HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )

        raise last_error or RuntimeError("ESI request failed")

    def get(self, endpoint, params=None):
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint, json=None, params=None):
        return self._request("POST", endpoint, params=params, json=json)

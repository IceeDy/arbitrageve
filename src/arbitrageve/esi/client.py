import time

import requests

from arbitrageve.config.settings import settings


class ESIRequestError(requests.HTTPError):
    """HTTP error from ESI with structured rate-limit metadata."""

    def __init__(self, message, *, status_code=None, retry_after=None, rate_limit_headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.rate_limit_headers = rate_limit_headers or {}


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

            # A 429 is an explicit rate-limit signal. Do not immediately
            # retry it: repeated retries only create more pressure and can
            # prolong the rate-limited period. The caller can decide whether
            # to stop the current scan and try again later.
            if response.status_code == 429:
                rate_limit_headers = {
                    key: response.headers.get(key)
                    for key in (
                        "X-Ratelimit-Group",
                        "X-Ratelimit-Limit",
                        "X-Ratelimit-Remaining",
                        "X-Ratelimit-Used",
                    )
                    if response.headers.get(key) is not None
                }
                raise ESIRequestError(
                    f"ESI returned HTTP 429: {response.text[:1000]}",
                    status_code=429,
                    retry_after=response.headers.get("Retry-After"),
                    rate_limit_headers=rate_limit_headers,
                )
                raise error

            # Retry transient server failures, but not client-side errors.
            if 500 <= response.status_code < 600:
                last_error = ESIRequestError(
                    f"ESI returned HTTP {response.status_code}: "
                    f"{response.text[:1000]}",
                    status_code=response.status_code,
                )
                if attempt >= 2:
                    raise last_error
                time.sleep(2**attempt)
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

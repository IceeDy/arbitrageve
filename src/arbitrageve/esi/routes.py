from arbitrageve.esi.client import ESIClient


class RouteClient:
    def __init__(self, client=None):
        self.client = client or ESIClient()

    def route(self, origin, destination, preference="Shorter", security_penalty=50):
        """Return the ESI route as a normalized list of solar-system IDs."""
        response = self.client.post(
            f"route/{origin}/{destination}",
            json={
                "preference": preference,
                "security_penalty": security_penalty,
            },
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"Unexpected ESI route response: {type(payload).__name__}")
        try:
            return [int(system_id) for system_id in payload]
        except (TypeError, ValueError) as exc:
            raise ValueError("ESI route response contains a non-numeric system ID") from exc

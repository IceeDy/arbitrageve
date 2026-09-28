from arbitrageve.esi.client import ESIClient


class RouteClient:
    def __init__(self, client=None):
        self.client = client or ESIClient()

    def route(self, origin, destination, preference="Shorter", security_penalty=50):
        """Return the ESI route as a list of solar-system IDs."""
        response = self.client.post(
            f"route/{origin}/{destination}/",
            json={
                "preference": preference,
                "security_penalty": security_penalty,
            },
        )
        return response.json()

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

        # ESI's route representation may be wrapped in an object depending
        # on the compatibility schema. Accept the common wrapper keys while
        # keeping the public client contract as list[int].
        if isinstance(payload, dict):
            for key in ("route", "systems", "system_ids"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    payload = candidate
                    break

        if not isinstance(payload, list):
            raise ValueError(
                f"Unexpected ESI route response: {type(payload).__name__}: "
                f"{payload!r}"
            )

        try:
            return [int(system_id) for system_id in payload]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "ESI route response contains a non-numeric system ID"
            ) from exc

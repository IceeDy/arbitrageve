from arbitrageve.esi.client import ESIClient


class UniverseClient:
    def __init__(self, client=None):
        self.client = client or ESIClient()

    def get_system(self, system_id: int) -> dict:
        return self.client.get(f"universe/systems/{system_id}/").json()

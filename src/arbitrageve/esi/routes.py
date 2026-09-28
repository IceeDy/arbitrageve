from arbitrageve.esi.client import ESIClient

class RouteClient:
    def __init__(self, client=None): self.client=client or ESIClient()
    def route(self, origin, destination, flag='shortest'):
        return self.client.get(f'route/{origin}/{destination}/', {'flag':flag}).json()

from arbitrageve.esi.client import ESIClient

class MarketClient:
    def __init__(self, client=None): self.client=client or ESIClient()
    def get_orders(self, region_id, order_type='all', page=1):
        r=self.client.get(f'markets/{region_id}/orders/', {'order_type':order_type,'page':page})
        return r.json(), int(r.headers.get('X-Pages','1'))

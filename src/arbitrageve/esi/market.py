from arbitrageve.esi.client import ESIClient


class MarketClient:
    def __init__(self, client=None):
        self.client = client or ESIClient()

    def get_orders(
        self,
        region_id: int,
        order_type: str = "all",
        page: int = 1,
    ) -> tuple[list[dict], int]:
        response = self.client.get(
            f"markets/{region_id}/orders/",
            params={"order_type": order_type, "page": page},
        )
        pages = max(1, int(response.headers.get("X-Pages", "1")))
        return response.json(), pages

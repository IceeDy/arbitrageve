from datetime import datetime, timezone
from arbitrageve.db.models import MarketOrder
from arbitrageve.esi.market import MarketClient

def collect_region(session, region_id, client=None):
    client=client or MarketClient(); stamp=datetime.now(timezone.utc).replace(tzinfo=None); total=0
    _,pages=client.get_orders(region_id,page=1)
    for page in range(1,pages+1):
        orders,_=client.get_orders(region_id,page=page)
        for d in orders:
            session.merge(MarketOrder(order_id=d['order_id'],region_id=region_id,system_id=d['system_id'],location_id=d['location_id'],type_id=d['type_id'],price=d['price'],volume_remain=d['volume_remain'],volume_total=d['volume_total'],is_buy_order=d['is_buy_order'],collected_at=stamp)); total+=1
        session.commit()
    return total

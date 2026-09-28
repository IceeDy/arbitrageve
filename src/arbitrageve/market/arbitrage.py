from dataclasses import dataclass

@dataclass(frozen=True)
class Opportunity:
    type_id:int; buy_price:float; sell_price:float; quantity:int; gross_profit:float; net_profit:float; roi:float; volume_m3:float

def calculate_opportunity(type_id,buy_price,sell_price,quantity,volume_m3,costs=0):
    gross=(sell_price-buy_price)*quantity; net=gross-costs; invested=buy_price*quantity
    return Opportunity(type_id,buy_price,sell_price,quantity,gross,net,net/invested if invested else 0,volume_m3*quantity)

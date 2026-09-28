from __future__ import annotations

import heapq
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbitrageve.db.models import SolarSystem, Stargate


class LocalRouteClient:
    """Calculate EVE stargate routes locally from the SDE graph.

    The weighting follows CCP's documented route-calculation model:
    Shorter minimizes jumps; Safer and LessSecure apply security-dependent
    edge costs controlled by security_penalty.
    """

    def __init__(self, session: Session):
        self.session = session
        self._graph = None
        self._security = None

    def _load_graph(self) -> None:
        if self._graph is not None:
            return

        self._graph = {}
        self._security = {
            row.system_id: float(row.security_status)
            for row in self.session.scalars(select(SolarSystem))
        }
        for gate in self.session.scalars(select(Stargate)):
            self._graph.setdefault(gate.system_id, set()).add(
                gate.destination_system_id
            )

    @staticmethod
    def _edge_cost(security_status: float, preference: str, security_penalty: int) -> float:
        security_penalty = max(0, min(100, int(security_penalty)))
        penalty = math.exp(0.15 * security_penalty)

        if preference == "Shorter":
            return 1.0
        if preference == "Safer":
            if security_status <= 0.0:
                return 2.0 * penalty
            if security_status < 0.45:
                return penalty
            return 0.90
        if preference == "LessSecure":
            if security_status <= 0.0:
                return 2.0 * penalty
            if security_status < 0.45:
                return 0.90
            return penalty
        raise ValueError(
            "preference must be Shorter, Safer, or LessSecure"
        )

    def route(
        self,
        origin: int,
        destination: int,
        preference: str = "Shorter",
        security_penalty: int = 50,
    ) -> list[int]:
        self._load_graph()

        origin = int(origin)
        destination = int(destination)
        if origin == destination:
            return [origin]
        if origin not in self._security or destination not in self._security:
            raise ValueError(
                f"Unknown solar system: {origin if origin not in self._security else destination}"
            )

        queue = [(0.0, origin)]
        distances = {origin: 0.0}
        previous = {}
        visited = set()

        while queue:
            cost, current = heapq.heappop(queue)
            if current in visited:
                continue
            visited.add(current)

            if current == destination:
                break

            for neighbor in self._graph.get(current, ()):
                if neighbor not in self._security:
                    continue
                next_cost = cost + self._edge_cost(
                    self._security[neighbor],
                    preference,
                    security_penalty,
                )
                if next_cost < distances.get(neighbor, float("inf")):
                    distances[neighbor] = next_cost
                    previous[neighbor] = current
                    heapq.heappush(queue, (next_cost, neighbor))

        if destination not in distances:
            return []

        path = [destination]
        while path[-1] != origin:
            path.append(previous[path[-1]])
        path.reverse()
        return path

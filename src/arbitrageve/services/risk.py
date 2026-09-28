from collections.abc import Iterable
from dataclasses import dataclass

from arbitrageve.db.models import SolarSystem


@dataclass(frozen=True)
class RiskProfile:
    """Route filters for hauling decisions.

    Security class is descriptive: it does not guarantee a risk-free route.
    """

    allow_highsec: bool = True
    allow_lowsec: bool = True
    allow_nullsec: bool = True
    max_jumps: int | None = None

    def validate(self) -> None:
        if self.max_jumps is not None and self.max_jumps < 0:
            raise ValueError("max_jumps cannot be negative")
        if not any((self.allow_highsec, self.allow_lowsec, self.allow_nullsec)):
            raise ValueError("at least one security class must be allowed")


def analyze_route(systems: Iterable[SolarSystem], jumps: int) -> dict[str, float | int | str]:
    """Summarize security characteristics of a route."""
    systems = list(systems)
    if not systems:
        return {
            "route_class": "unknown",
            "highsec_systems": 0,
            "lowsec_systems": 0,
            "nullsec_systems": 0,
            "min_security_status": 0.0,
            "risk_score": 0.0,
            "route_known": False,
        }

    highsec = sum(system.security_class == "highsec" for system in systems)
    lowsec = sum(system.security_class == "lowsec" for system in systems)
    nullsec = sum(system.security_class == "nullsec" for system in systems)
    min_security = min(system.security_status for system in systems)

    if nullsec:
        route_class = "nullsec"
    elif lowsec:
        route_class = "lowsec"
    else:
        route_class = "highsec"

    traversed_jumps = max(1, jumps)
    risk_score = (lowsec + (nullsec * 3)) / traversed_jumps

    return {
        "route_class": route_class,
        "highsec_systems": highsec,
        "lowsec_systems": lowsec,
        "nullsec_systems": nullsec,
        "min_security_status": min_security,
        "risk_score": risk_score,
        "route_known": True,
    }


def route_allowed(profile: RiskProfile, analysis: dict) -> bool:
    """Return whether a route passes the configured filters."""
    profile.validate()
    if not analysis.get("route_known", False) and not (
        profile.allow_highsec and profile.allow_lowsec and profile.allow_nullsec
    ):
        return False
    if profile.max_jumps is not None and int(analysis.get("jumps", 0)) > profile.max_jumps:
        return False
    if analysis.get("lowsec_systems", 0) and not profile.allow_lowsec:
        return False
    if analysis.get("nullsec_systems", 0) and not profile.allow_nullsec:
        return False
    return not (
        analysis.get("highsec_systems", 0) and not profile.allow_highsec
    )

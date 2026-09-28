from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionProfile:
    """Simple configurable hauling-time model."""

    fixed_minutes: float = 10.0
    minutes_per_jump: float = 2.0
    return_trip: bool = False

    def validate(self) -> None:
        if self.fixed_minutes < 0 or self.minutes_per_jump < 0:
            raise ValueError("execution times cannot be negative")


def estimate_minutes(jumps: int, profile: ExecutionProfile) -> float:
    profile.validate()
    trip_factor = 2 if profile.return_trip else 1
    return (profile.fixed_minutes + max(0, jumps) * profile.minutes_per_jump) * trip_factor


def estimate_isk_per_hour(net_profit: float, jumps: int, profile: ExecutionProfile) -> float:
    minutes = estimate_minutes(jumps, profile)
    return net_profit / minutes * 60 if minutes > 0 else 0.0

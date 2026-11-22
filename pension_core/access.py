"""Declared potential affiliation and first-pillar payment-access paths."""
from dataclasses import dataclass

AFFILIATIONS = frozenset(("worker","resident","none"))


@dataclass(frozen=True)
class Access:
    affiliation: str
    can_post: bool = True

    def __post_init__(self):
        if self.affiliation not in AFFILIATIONS or type(self.can_post) is not bool:
            raise ValueError("invalid affiliation or payment-access indicator")
        if self.affiliation=="none" and self.can_post:
            raise ValueError("a person outside both regimes has no posting access")


def validate_path(path, months):
    if len(path)!=months or any(not isinstance(a,Access) for a in path):
        raise ValueError("provide one declared first-pillar access state per simulated month")


def experimental_path(n, t0, width, to_resident, interruption):
    """Fixed employment; optionally route to residents and impose a separate interruption."""
    if t0 < 0 or width <= 0:
        raise ValueError("positive path width and nonnegative band start required")
    if t0+width>n or (interruption and not set(interruption)<=set(range(t0,t0+width))):
        raise ValueError("path interval lies outside comparison support")
    return tuple(Access("resident" if to_resident and t0<=i<t0+width else "worker",
                        i not in interruption) for i in range(n))

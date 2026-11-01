"""UI-independent domain state. All money is integer credits."""
from dataclasses import dataclass, field

MAX_VALUE = 10**15  # portable safe range, below SQLite signed int64


class GameError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def integer(value, minimum=0, maximum=MAX_VALUE):
    if type(value) is not int or not minimum <= value <= maximum:
        raise GameError("INVALID_NUMBER")
    return value


@dataclass
class Player:
    id: str
    handle: str
    cash: int
    ship_id: str
    planet_id: str
    cargo: dict[str, int] = field(default_factory=dict)
    destination_id: str | None = None
    arrival_at: int | None = None


@dataclass
class Market:
    price: int
    stock: int
    shock: int = 0
    production_rate: int | None = None
    capacity: int | None = None


@dataclass
class World:
    season_id: int
    game_time: int
    players: dict[str, Player]
    markets: dict[tuple[str, str], Market]
    routes: dict[str, dict]

    economy_time: int | None = None

    developments: dict[tuple[str, str], int] = field(default_factory=dict)

    event_anchor: int = 0
    event_slot: int = 0
    active_events: list = field(default_factory=list)
    pending_events: list = field(default_factory=list)
    phase3_state: dict = field(default_factory=dict)
    exploration_events: list = field(default_factory=list)

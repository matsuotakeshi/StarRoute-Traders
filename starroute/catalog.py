"""Validated data definitions, independent of persistence and presentation."""
import json
import re
from pathlib import Path
from .model import GameError, integer
from .ships import build_ship_models
from .navigation import navigation_plans
from .economy import policy
from .development import policy as development_policy
from .production import policy as production_policy
from .regional import policy as regional_policy, anchors
from .events import policy as events_policy


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
        raise GameError("INVALID_ID")
    return value


def display_name(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 64
            or any(not char.isprintable() for char in value)):
        raise GameError("INVALID_NAME")
    return value


class Catalog:
    def __init__(self, data: dict):
        try:
            self._validate(data)
            # Own a detached snapshot; caller mutation must not change live rules.
            self.data = json.loads(json.dumps(data, ensure_ascii=False))
            self.planets = {v["id"]: v for v in self.data["planets"]}
            self.goods = {v["id"]: v for v in self.data["goods"]}
            self.ships = {v["id"]: v for v in self.data["ships"]}
            self.ship_grades, self.ship_profiles = build_ship_models(self.data, identifier)
            self.navigation_plans, self.navigation_status = navigation_plans(self.data, self.ship_profiles)
            self.economy = policy(self.data)
            self.economy_markets = {(r["planet_id"],r["goods_id"]):r for r in self.economy.get("markets",[])}
            self.development = development_policy(self.data, identifier)
            self.development_planets = {r["planet_id"]:r for r in self.development.get("planets",[])}
            self.production = production_policy(self.data, identifier)
            self.production_sources = {(r["planet_id"],r["goods_id"]):r for r in self.production.get("sources",[])}
            self.production_imports = {(r["planet_id"],r["goods_id"]):r["units_per_tick"] for r in self.production.get("imports",[])}
            self.regional_prices = regional_policy(self.data,self.production,identifier)
            self.regional_anchors = anchors(self.data,self.production,self.regional_prices)
            self.market_events = events_policy(self.data,identifier)
            from .industry_effects import policy as effects_policy
            self.industry_effects = effects_policy(self)
            self.industry_effect_planets = {r['planet_id']:r for r in self.industry_effects.get('planets',[])}
            from .phase3_policy import policy as phase3_policy
            self.phase3 = phase3_policy(self.data,self.ship_profiles,self.ship_grades)
            from .universe import validate
            validate(self)
        except (KeyError, TypeError, ValueError, GameError) as exc:
            raise GameError("INVALID_CONFIG") from exc

    @classmethod
    def load(cls, path=None):
        path = Path(path) if path else Path(__file__).parent / "config" / "game.json"
        try:
            def unique(pairs):
                result={}
                for key,value in pairs:
                    if key in result: raise ValueError("duplicate key")
                    result[key]=value
                return result
            return cls(json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique))
        except (OSError, ValueError) as exc:
            raise GameError("INVALID_CONFIG") from exc

    @staticmethod
    def _validate(data):
        if type(data["format_version"]) is not int or data["format_version"] not in (1,2):
            raise ValueError("format_version")
        for group in ("planets", "goods", "ships", "routes"):
            rows = data[group]
            if not isinstance(rows, list) or not rows:
                raise ValueError(group)
            ids = [identifier(row["id"]) for row in rows]
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate id")
        planets = {row["id"] for row in data["planets"]}
        goods = {row["id"] for row in data["goods"]}
        ships = {row["id"] for row in data["ships"]}
        for group in ("planets", "goods", "ships"):
            for row in data[group]:
                display_name(row["name"])
        for row in data["goods"]:
            integer(row["base_price"], 1)
            integer(row["volume"], 1)
            integer(row["production"])
            integer(row["volatility_bps"], 0, 10000)
        for row in data["ships"]:
            for key in ("capacity", "max_distance", "speed"):
                integer(row[key], 1)
        pairs = set()
        for row in data["routes"]:
            if row["from"] not in planets or row["to"] not in planets or row["from"] == row["to"]:
                raise ValueError("route endpoint")
            pair = tuple(sorted((row["from"], row["to"])))
            if pair in pairs:
                raise ValueError("parallel route")
            pairs.add(pair)
            integer(row["distance"], 1)
            integer(row["seconds"], 1)
            integer(row["fee"])
            if type(row["is_open"]) is not bool:
                raise ValueError("is_open")
        markets = set()
        for row in data["markets"]:
            if row["planet_id"] not in planets or row["goods_id"] not in goods:
                raise ValueError("market reference")
            integer(row["price"], 1)
            integer(row["stock"])
            key = row["planet_id"], row["goods_id"]
            if key in markets:
                raise ValueError("duplicate market")
            markets.add(key)
        if markets != {(p, g) for p in planets for g in goods}:
            raise ValueError("incomplete markets")
        start = data["starting"]
        integer(start["cash"])
        if start["planet_id"] not in planets or start["ship_id"] not in ships:
            raise ValueError("start reference")

    def effective_rules(self):
        from .rules import effective_rules
        return effective_rules(self)

    def canonical(self):
        return json.dumps(self.data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

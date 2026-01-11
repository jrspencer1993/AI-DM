"""
Pure Python Game State Container.

This module defines the game state structure used by the simulation,
independent of Streamlit.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
import copy
import json


@dataclass
class Position:
    """Grid position."""
    x: int = 0
    y: int = 0
    
    def to_dict(self) -> Dict:
        return {"x": self.x, "y": self.y}
    
    @classmethod
    def from_dict(cls, d: Dict) -> "Position":
        return cls(x=d.get("x", 0), y=d.get("y", 0))


@dataclass
class Actor:
    """Base actor (party member or enemy)."""
    name: str = "Actor"
    hp: int = 10
    max_hp: int = 10
    ac: int = 10
    speed_ft: int = 30
    pos: Position = field(default_factory=Position)
    abilities: Dict[str, int] = field(default_factory=lambda: {
        "STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10
    })
    attacks: List[Dict] = field(default_factory=list)
    spells: List[Dict] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    traits: str = ""
    special_abilities: List[Dict] = field(default_factory=list)  # Breath weapons, etc.
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "ac": self.ac,
            "speed_ft": self.speed_ft,
            "pos": self.pos.to_dict(),
            "abilities": self.abilities.copy(),
            "attacks": copy.deepcopy(self.attacks),
            "spells": copy.deepcopy(self.spells),
            "conditions": self.conditions.copy(),
            "traits": self.traits,
            "special_abilities": copy.deepcopy(self.special_abilities),
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> "Actor":
        pos = Position.from_dict(d.get("pos", {}))
        return cls(
            name=d.get("name", "Actor"),
            hp=int(d.get("hp", 10)),
            max_hp=int(d.get("max_hp", d.get("hp", 10))),
            ac=int(d.get("ac", 10)),
            speed_ft=int(d.get("speed_ft", 30)),
            pos=pos,
            abilities=d.get("abilities", {}).copy(),
            attacks=copy.deepcopy(d.get("attacks", [])),
            spells=copy.deepcopy(d.get("spells", [])),
            conditions=d.get("conditions", []).copy() if isinstance(d.get("conditions"), list) else [],
            traits=d.get("traits", ""),
            special_abilities=copy.deepcopy(d.get("special_abilities", [])),
        )


@dataclass
class GridCell:
    """Single grid cell."""
    tile: str = "open"
    hazard: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {"tile": self.tile, "hazard": self.hazard}
    
    @classmethod
    def from_dict(cls, d: Dict) -> "GridCell":
        if isinstance(d, dict):
            return cls(tile=d.get("tile", "open"), hazard=d.get("hazard"))
        return cls()


@dataclass
class Grid:
    """Combat grid."""
    width: int = 20
    height: int = 20
    square_size_ft: int = 5
    cells: List[List[GridCell]] = field(default_factory=list)
    biome: str = "Forest"
    
    def __post_init__(self):
        if not self.cells:
            self.cells = [
                [GridCell() for _ in range(self.width)]
                for _ in range(self.height)
            ]
    
    def to_dict(self) -> Dict:
        return {
            "width": self.width,
            "height": self.height,
            "square_size_ft": self.square_size_ft,
            "biome": self.biome,
            "cells": [[c.to_dict() for c in row] for row in self.cells],
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> "Grid":
        grid = cls(
            width=d.get("width", 20),
            height=d.get("height", 20),
            square_size_ft=d.get("square_size_ft", 5),
            biome=d.get("biome", "Forest"),
        )
        
        cells_data = d.get("cells", [])
        if cells_data:
            grid.cells = [
                [GridCell.from_dict(c) for c in row]
                for row in cells_data
            ]
        
        return grid


@dataclass
class ActionEconomy:
    """Action economy for a turn."""
    standard: bool = True
    move: bool = True
    bonus: bool = False
    reaction: bool = True
    
    def to_dict(self) -> Dict:
        return {
            "standard": self.standard,
            "move": self.move,
            "bonus": self.bonus,
            "reaction": self.reaction,
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> "ActionEconomy":
        return cls(
            standard=d.get("standard", True),
            move=d.get("move", True),
            bonus=d.get("bonus", False),
            reaction=d.get("reaction", True),
        )
    
    def reset(self):
        """Reset for new turn."""
        self.standard = True
        self.move = True
        self.bonus = False
        self.reaction = True


@dataclass
class GameState:
    """Complete game state for simulation."""
    grid: Grid = field(default_factory=Grid)
    party: List[Actor] = field(default_factory=list)
    enemies: List[Actor] = field(default_factory=list)
    initiative_order: List[Dict] = field(default_factory=list)
    turn_index: int = 0
    round: int = 1
    in_combat: bool = True
    action_economy: ActionEconomy = field(default_factory=ActionEconomy)
    
    def to_dict(self) -> Dict:
        return {
            "grid": self.grid.to_dict(),
            "party": [p.to_dict() for p in self.party],
            "enemies": [e.to_dict() for e in self.enemies],
            "initiative_order": copy.deepcopy(self.initiative_order),
            "turn_index": self.turn_index,
            "round": self.round,
            "in_combat": self.in_combat,
            "action_economy": self.action_economy.to_dict(),
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> "GameState":
        return cls(
            grid=Grid.from_dict(d.get("grid", {})),
            party=[Actor.from_dict(p) for p in d.get("party", [])],
            enemies=[Actor.from_dict(e) for e in d.get("enemies", [])],
            initiative_order=copy.deepcopy(d.get("initiative_order", [])),
            turn_index=d.get("turn_index", 0),
            round=d.get("round", 1),
            in_combat=d.get("in_combat", True),
            action_economy=ActionEconomy.from_dict(d.get("action_economy", {})),
        )
    
    def copy(self) -> "GameState":
        """Create a deep copy of the state."""
        return GameState.from_dict(self.to_dict())
    
    def get_current_actor(self) -> Optional[Dict]:
        """Get the current actor in initiative."""
        if not self.initiative_order or self.turn_index >= len(self.initiative_order):
            return None
        return self.initiative_order[self.turn_index]
    
    def advance_turn(self):
        """Advance to next turn in initiative."""
        self.turn_index += 1
        if self.turn_index >= len(self.initiative_order):
            self.turn_index = 0
            self.round += 1
        self.action_economy.reset()
    
    def is_combat_over(self) -> bool:
        """Check if combat has ended."""
        party_alive = any(p.hp > 0 for p in self.party)
        enemies_alive = any(e.hp > 0 for e in self.enemies)
        return not party_alive or not enemies_alive
    
    def get_winner(self) -> Optional[str]:
        """Get combat winner. Returns 'party', 'enemies', or None."""
        if not self.is_combat_over():
            return None
        
        party_alive = any(p.hp > 0 for p in self.party)
        if party_alive:
            return "party"
        return "enemies"


def create_simple_scenario(
    num_party: int = 2,
    num_enemies: int = 2,
    grid_width: int = 15,
    grid_height: int = 15
) -> GameState:
    """
    Create a simple combat scenario for testing.
    
    Party starts on left, enemies on right.
    """
    state = GameState()
    state.grid = Grid(width=grid_width, height=grid_height)
    
    # Create party members
    for i in range(num_party):
        party_member = Actor(
            name=f"Hero {i+1}",
            hp=30,
            max_hp=30,
            ac=15,
            speed_ft=30,
            pos=Position(x=2, y=grid_height // 2 - num_party // 2 + i),
            attacks=[{
                "name": "Longsword",
                "to_hit": 5,
                "damage": "1d8+3",
                "range": 5,
                "attack_type": "melee"
            }],
        )
        state.party.append(party_member)
    
    # Create enemies
    for i in range(num_enemies):
        enemy = Actor(
            name=f"Goblin {i+1}",
            hp=7,
            max_hp=7,
            ac=15,
            speed_ft=30,
            pos=Position(x=grid_width - 3, y=grid_height // 2 - num_enemies // 2 + i),
            attacks=[
                {
                    "name": "Scimitar",
                    "to_hit": 4,
                    "damage": "1d6+2",
                    "range": 5,
                    "attack_type": "melee"
                },
                {
                    "name": "Shortbow",
                    "to_hit": 4,
                    "damage": "1d6+2",
                    "range": 80,
                    "attack_type": "ranged"
                }
            ],
        )
        state.enemies.append(enemy)
    
    # Create initiative order (alternating for simplicity)
    for i in range(max(num_party, num_enemies)):
        if i < num_enemies:
            state.initiative_order.append({"kind": "enemy", "idx": i})
        if i < num_party:
            state.initiative_order.append({"kind": "party", "idx": i})
    
    return state


def state_to_ai_dict(state: GameState) -> Dict:
    """Convert GameState to dict format expected by AI modules."""
    return {
        "grid": state.grid.to_dict(),
        "party": [p.to_dict() for p in state.party],
        "enemies": [e.to_dict() for e in state.enemies],
        "initiative_order": state.initiative_order,
        "turn_index": state.turn_index,
        "round": state.round,
        "in_combat": state.in_combat,
        "action_economy": state.action_economy.to_dict(),
    }

import os
import sys
import json
import random
import re
import time
from datetime import datetime
from typing import Tuple, Dict, Any, List

import streamlit as st

import tracemalloc
tracemalloc.start()

# Add project root to path for ai/sim module imports
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Try to import AI logging module (optional - UI works without it)
try:
    from ai.logger import get_ui_logger, set_ui_logging_enabled
    AI_LOGGING_AVAILABLE = True
except ImportError:
    AI_LOGGING_AVAILABLE = False
    def get_ui_logger():
        return None
    def set_ui_logging_enabled(enabled):
        pass

# ==============
# PERFORMANCE UTILITIES
# ==============

_perf_timings = {}

def perf_timer(name: str):
    """Context manager for timing code blocks when performance debug is enabled."""
    class Timer:
        def __enter__(self):
            self.start = time.perf_counter()
            return self
        def __exit__(self, *args):
            elapsed = (time.perf_counter() - self.start) * 1000  # ms
            if st.session_state.get("perf_debug", False):
                _perf_timings[name] = elapsed
    return Timer()

def get_perf_timings() -> dict:
    """Return collected performance timings."""
    return _perf_timings.copy()

def clear_perf_timings():
    """Clear performance timings for new render."""
    global _perf_timings
    _perf_timings = {}

# ==============
# CACHED SRD LOADERS
# ==============
# These use st.cache_data to avoid re-parsing JSON files on every Streamlit rerun.
# The cached functions return pure data; session_state is updated by wrapper functions.

@st.cache_data(show_spinner=False)
def _cached_load_json(file_path: str) -> tuple:
    """
    Cached JSON file loader. Returns (data, path) tuple.
    Cache key is the file path - data is reloaded if file changes.
    """
    if not file_path or not os.path.exists(file_path):
        return None, file_path
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            return json.load(f), file_path
    except Exception:
        return None, file_path

def _find_data_file(candidates: list) -> str | None:
    """Find first existing file from candidates list."""
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

# ==============
# ACTION SCHEMA 
# ==============
# Every action in the system MUST follow this schema so the UI can reason about it deterministically
#
# ACTION_SCHEMA = {
#     "name": str,
#     "type": "attack | save | utility | spell",
#     "action_type": "move | standard | quick | immediate",
#     "to_hit": int | None,         # for attacks
#     "dc": int | None,             # for saves
#     "save": "STR|DEX|CON|INT|WIS|CHA" | None,
#     "damage": "1d6+3" | None,
#     "damage_type": "slashing|fire|etc" | None,
#     "condition": "prone|stunned|etc" | None,
#     "range": int | None,
#     "description": str,
# }

# =========================
# EXAMPLE ACTIONS (SRD)
# =========================

MELEE_WEAPON_ATTACK = {
    "name": "Longsword",
    "type": "attack",
    "action_type": "standard",
    "to_hit": 5,
    "dc": None,
    "save": None,
    "damage": "1d8+3",
    "damage_type": "slashing",
    "condition": None,
    "range": 5,
    "description": "A melee weapon attack with a longsword.",
}

DODGE_ACTION = {
    "name": "Dodge",
    "type": "utility",
    "action_type": "standard",
    "to_hit": None,
    "dc": None,
    "save": None,
    "damage": None,
    "damage_type": None,
    "condition": None,
    "range": None,
    "description": "Until the start of your next turn, you gain +2 AC against attacks you can see.",
}

FIRE_BOLT = {
    "name": "Fire Bolt",
    "type": "spell",
    "action_type": "standard",
    "to_hit": 6,
    "dc": None,
    "save": None,
    "damage": "1d10",
    "damage_type": "fire",
    "condition": None,
    "range": 120,
    "description": "A mote of fire that deals fire damage on hit.",
}

# ==============
# TACTICAL GRID SYSTEM
# ==============
# D&D-style square grid map with terrain, movement, and positioning
# All terrain data is loaded from JSON files in data/terrain/

# Default fallback tiles if JSON fails to load
_DEFAULT_TILES = {
    "open":      {"id": "open", "name": "Open Ground", "move_cost": 1, "blocked": False, "blocks_los": False, "color": "#e8e8e8", "label": ""},
    "wall":      {"id": "wall", "name": "Wall", "move_cost": 999, "blocked": True, "blocks_los": True, "color": "#3a3a3a", "label": "█"},
    "difficult": {"id": "difficult", "name": "Difficult Terrain", "move_cost": 2, "blocked": False, "blocks_los": False, "color": "#a0a060", "label": "~"},
}

# Cached terrain data
_TILES_CACHE = None
_BIOMES_CACHE = None
_HAZARDS_CACHE = None

def _get_terrain_data_path(filename: str) -> str:
    """Get path to terrain data file."""
    base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, "..", "data", "terrain", filename)

def load_tiles() -> dict:
    """Load tile definitions from tiles.json. Returns dict keyed by tile id."""
    global _TILES_CACHE
    if _TILES_CACHE is not None:
        return _TILES_CACHE
    
    path = _get_terrain_data_path("tiles.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            tiles_list = data.get("tiles", [])
            _TILES_CACHE = {t["id"]: t for t in tiles_list if "id" in t}
            return _TILES_CACHE
    except Exception as e:
        # Fallback to defaults
        _TILES_CACHE = _DEFAULT_TILES
        return _TILES_CACHE

def load_biomes() -> list:
    """Load biome definitions from biomes.json. Returns list of biome dicts."""
    global _BIOMES_CACHE
    if _BIOMES_CACHE is not None:
        return _BIOMES_CACHE
    
    path = _get_terrain_data_path("biomes.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            _BIOMES_CACHE = data.get("biomes", [])
            return _BIOMES_CACHE
    except Exception:
        # Fallback to minimal default
        _BIOMES_CACHE = [{"id": "default", "name": "Default", "description": "Basic terrain", 
                          "tile_weights": {"open": 80, "wall": 10, "difficult": 10},
                          "densities": {"wall": 0.1, "difficult": 0.1, "water": 0},
                          "hazards": [], "hazard_chance": 0,
                          "cluster_style": {"walkers": 4, "steps_per_walker": 30}}]
        return _BIOMES_CACHE

def load_hazards() -> dict:
    """Load hazard definitions from hazards.json. Returns dict keyed by hazard id."""
    global _HAZARDS_CACHE
    if _HAZARDS_CACHE is not None:
        return _HAZARDS_CACHE
    
    path = _get_terrain_data_path("hazards.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            hazards_list = data.get("hazards", [])
            _HAZARDS_CACHE = {h["id"]: h for h in hazards_list if "id" in h}
            return _HAZARDS_CACHE
    except Exception:
        _HAZARDS_CACHE = {}
        return _HAZARDS_CACHE

def get_tile(tile_id: str) -> dict:
    """Get tile definition by id."""
    tiles = load_tiles()
    return tiles.get(tile_id, tiles.get("open", _DEFAULT_TILES["open"]))

def get_tile_ids() -> list:
    """Get ordered list of tile IDs for cycling in edit mode."""
    tiles = load_tiles()
    # Prefer a specific order: open, wall, difficult, water, then others
    preferred_order = ["open", "wall", "difficult", "water"]
    ordered = [tid for tid in preferred_order if tid in tiles]
    # Add any other tiles not in preferred order
    for tid in tiles:
        if tid not in ordered:
            ordered.append(tid)
    return ordered

def get_biome_names() -> list:
    """Get list of available biome names."""
    biomes = load_biomes()
    return [b.get("name", "Unknown") for b in biomes]

def get_biome_config(name: str) -> dict:
    """Get biome config by name."""
    biomes = load_biomes()
    for b in biomes:
        if b.get("name") == name:
            return b
    return biomes[0] if biomes else {}

def get_biome_config_by_id(biome_id: str) -> dict:
    """Get biome config by id."""
    biomes = load_biomes()
    for b in biomes:
        if b.get("id") == biome_id:
            return b
    return biomes[0] if biomes else {}

def get_hazard(hazard_id: str) -> dict:
    """Get hazard definition by id."""
    hazards = load_hazards()
    return hazards.get(hazard_id, {})

def get_hazard_names_for_biome(biome_name: str) -> list:
    """Get list of hazard names available for a biome."""
    biome = get_biome_config(biome_name)
    hazard_ids = biome.get("hazards", [])
    hazards = load_hazards()
    return [hazards[hid].get("name", hid) for hid in hazard_ids if hid in hazards]

def get_hazard_id_by_name(name: str) -> str | None:
    """Get hazard id by its display name."""
    hazards = load_hazards()
    for hid, h in hazards.items():
        if h.get("name") == name:
            return hid
    return None

# Compatibility alias for existing code
def get_terrain_names() -> list:
    """Get list of available terrain/biome names (alias for get_biome_names)."""
    return get_biome_names()

def get_terrain_config(name: str) -> dict:
    """Get terrain config by name (alias for get_biome_config)."""
    return get_biome_config(name)

def init_grid(width: int = 20, height: int = 20, square_size_ft: int = 5) -> dict:
    """Initialize an empty grid."""
    cells = [[{"tile": "open", "hazard": None} for _ in range(width)] for _ in range(height)]
    return {
        "width": width,
        "height": height,
        "square_size_ft": square_size_ft,
        "cells": cells,
        "biome": None,
        "seed": None,
    }

def ensure_grid():
    """Ensure grid exists in session state."""
    if "grid" not in st.session_state or st.session_state.grid is None:
        st.session_state.grid = init_grid()
    return st.session_state.grid

def ensure_actor_pos(actor: dict, default_x: int, default_y: int):
    """Ensure actor has a position, setting default if missing."""
    if "pos" not in actor or actor["pos"] is None:
        actor["pos"] = {"x": default_x, "y": default_y}
    if "speed_ft" not in actor:
        actor["speed_ft"] = 30
    if "size" not in actor:
        actor["size"] = 1
    return actor

def auto_place_actors():
    """Auto-place actors without positions on the grid."""
    grid = ensure_grid()
    width = grid["width"]
    height = grid["height"]
    
    # Place party on left edge (column 0-1)
    party_y = 1
    for i, actor in enumerate(st.session_state.get("party", [])):
        if "pos" not in actor or actor["pos"] is None:
            x = i % 2  # Columns 0-1
            y = party_y + (i // 2)
            if y >= height - 1:
                y = height - 2
            ensure_actor_pos(actor, x, y)
    
    # Place enemies on right edge (columns width-2 to width-1)
    enemy_y = 1
    for i, actor in enumerate(st.session_state.get("enemies", [])):
        if "pos" not in actor or actor["pos"] is None:
            x = width - 1 - (i % 2)  # Columns width-1 to width-2
            y = enemy_y + (i // 2)
            if y >= height - 1:
                y = height - 2
            ensure_actor_pos(actor, x, y)

def get_cell(grid: dict, x: int, y: int) -> dict:
    """Get cell at position, or None if out of bounds."""
    if x < 0 or y < 0 or y >= grid["height"] or x >= grid["width"]:
        return None
    return grid["cells"][y][x]

def set_cell_tile(grid: dict, x: int, y: int, tile: str):
    """Set tile type at position."""
    if 0 <= x < grid["width"] and 0 <= y < grid["height"]:
        grid["cells"][y][x]["tile"] = tile

def set_cell_hazard(grid: dict, x: int, y: int, hazard: str | None):
    """Set hazard at position."""
    if 0 <= x < grid["width"] and 0 <= y < grid["height"]:
        grid["cells"][y][x]["hazard"] = hazard

def is_cell_blocked(grid: dict, x: int, y: int) -> bool:
    """Check if cell is blocked (wall, water, or out of bounds)."""
    cell = get_cell(grid, x, y)
    if cell is None:
        return True
    tile_id = cell.get("tile", "open")
    tile = get_tile(tile_id)
    return tile.get("blocked", False)

def get_move_cost(grid: dict, x: int, y: int) -> int:
    """Get movement cost for a cell."""
    cell = get_cell(grid, x, y)
    if cell is None:
        return 999
    tile_id = cell.get("tile", "open")
    tile = get_tile(tile_id)
    return tile.get("move_cost", 1)

def is_cell_occupied(x: int, y: int, exclude_actor: dict = None) -> bool:
    """Check if cell is occupied by any actor."""
    for actor in st.session_state.get("party", []):
        if actor is exclude_actor:
            continue
        pos = actor.get("pos")
        if pos and pos.get("x") == x and pos.get("y") == y:
            return True
    for actor in st.session_state.get("enemies", []):
        if actor is exclude_actor:
            continue
        pos = actor.get("pos")
        if pos and pos.get("x") == x and pos.get("y") == y:
            return True
    return False

def get_actor_at(x: int, y: int) -> tuple:
    """Get actor at position. Returns (kind, idx, actor) or (None, None, None)."""
    for i, actor in enumerate(st.session_state.get("party", [])):
        pos = actor.get("pos")
        if pos and pos.get("x") == x and pos.get("y") == y:
            return ("party", i, actor)
    for i, actor in enumerate(st.session_state.get("enemies", [])):
        pos = actor.get("pos")
        if pos and pos.get("x") == x and pos.get("y") == y:
            return ("enemy", i, actor)
    return (None, None, None)

def dijkstra_reachable(grid: dict, start_x: int, start_y: int, max_cost: int, exclude_actor: dict = None) -> dict:
    """
    Find all reachable cells from start position within max_cost.
    Returns dict of {(x,y): cost} for reachable cells.
    Uses Dijkstra's algorithm with terrain costs.
    """
    import heapq
    
    width = grid["width"]
    height = grid["height"]
    
    # Priority queue: (cost, x, y)
    pq = [(0, start_x, start_y)]
    visited = {}
    
    # 8-directional movement (including diagonals)
    directions = [
        (-1, 0), (1, 0), (0, -1), (0, 1),  # Cardinal
        (-1, -1), (-1, 1), (1, -1), (1, 1)  # Diagonal
    ]
    
    while pq:
        cost, x, y = heapq.heappop(pq)
        
        if (x, y) in visited:
            continue
        visited[(x, y)] = cost
        
        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            if (nx, ny) in visited:
                continue
            if is_cell_blocked(grid, nx, ny):
                continue
            
            # Diagonal movement uses destination tile cost
            move_cost = get_move_cost(grid, nx, ny)
            new_cost = cost + move_cost
            
            if new_cost <= max_cost:
                # Can only end on unoccupied squares (except start)
                if not is_cell_occupied(nx, ny, exclude_actor) or (nx == start_x and ny == start_y):
                    heapq.heappush(pq, (new_cost, nx, ny))
    
    return visited

def find_path(grid: dict, start_x: int, start_y: int, end_x: int, end_y: int, max_cost: int, exclude_actor: dict = None) -> list | None:
    """
    Find shortest path from start to end within max_cost.
    Returns list of (x, y) tuples or None if no valid path.
    Uses A* algorithm.
    """
    import heapq
    
    width = grid["width"]
    height = grid["height"]
    
    def heuristic(x, y):
        return max(abs(x - end_x), abs(y - end_y))  # Chebyshev distance
    
    # Priority queue: (f_score, g_score, x, y, path)
    start_h = heuristic(start_x, start_y)
    pq = [(start_h, 0, start_x, start_y, [(start_x, start_y)])]
    visited = set()
    
    directions = [
        (-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (-1, 1), (1, -1), (1, 1)
    ]
    
    while pq:
        f, g, x, y, path = heapq.heappop(pq)
        
        if x == end_x and y == end_y:
            return path
        
        if (x, y) in visited:
            continue
        visited.add((x, y))
        
        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            if (nx, ny) in visited:
                continue
            if is_cell_blocked(grid, nx, ny):
                continue
            
            move_cost = get_move_cost(grid, nx, ny)
            new_g = g + move_cost
            
            if new_g > max_cost:
                continue
            
            # Cannot end on occupied square (unless it's the destination and empty)
            if nx == end_x and ny == end_y:
                if is_cell_occupied(nx, ny, exclude_actor):
                    continue
            
            new_f = new_g + heuristic(nx, ny)
            new_path = path + [(nx, ny)]
            heapq.heappush(pq, (new_f, new_g, nx, ny, new_path))
    
    return None

def generate_map(width: int, height: int, biome_name: str, seed: int) -> dict:
    """
    Generate a procedural map based on biome configuration from biomes.json.
    Uses random walkers for cluster generation with cluster_style settings.
    """
    import random as rng
    rng.seed(seed)
    
    # Initialize grid
    grid = init_grid(width, height)
    grid["biome"] = biome_name
    grid["seed"] = seed
    
    # Get biome config from JSON
    biome = get_biome_config(biome_name)
    if not biome:
        return grid
    
    # Get densities from biome config
    densities = biome.get("densities", {})
    wall_density = densities.get("wall", 0.1)
    difficult_density = densities.get("difficult", 0.15)
    water_density = densities.get("water", 0.0)
    hazard_chance = biome.get("hazard_chance", 0.05)
    hazard_ids = biome.get("hazards", [])
    
    # Get cluster style from biome
    cluster_style = biome.get("cluster_style", {"walkers": 5, "steps_per_walker": 35})
    num_walkers = cluster_style.get("walkers", 5)
    steps_per_walker = cluster_style.get("steps_per_walker", 35)
    
    # Calculate target counts
    total_cells = width * height
    target_walls = int(total_cells * wall_density)
    target_difficult = int(total_cells * difficult_density)
    target_water = int(total_cells * water_density)
    
    # Spawn safety zones (keep clear)
    spawn_cols_left = 2
    spawn_cols_right = 2
    
    def is_spawn_zone(x, y):
        return x < spawn_cols_left or x >= width - spawn_cols_right
    
    def is_tile_blocked(tile_id: str) -> bool:
        """Check if tile type is blocked using tiles.json data."""
        tile = get_tile(tile_id)
        return tile.get("blocked", False)
    
    def random_walker(tile_type: str, target_count: int):
        """Place tiles using random walker algorithm for natural clusters."""
        placed = 0
        attempts = 0
        max_attempts = target_count * 10
        
        # Cluster size range based on biome cluster_style
        min_cluster = max(2, steps_per_walker // 10)
        max_cluster = max(min_cluster + 2, steps_per_walker // 5)
        
        while placed < target_count and attempts < max_attempts:
            attempts += 1
            
            # Random starting point (avoid spawn zones for blocked tiles)
            if is_tile_blocked(tile_type):
                if width - spawn_cols_right - spawn_cols_left <= 0:
                    break
                start_x = rng.randint(spawn_cols_left, width - spawn_cols_right - 1)
            else:
                start_x = rng.randint(0, width - 1)
            start_y = rng.randint(0, height - 1)
            
            if is_spawn_zone(start_x, start_y) and is_tile_blocked(tile_type):
                continue
            
            # Random walk to create cluster
            cluster_size = rng.randint(min_cluster, max_cluster)
            x, y = start_x, start_y
            
            for _ in range(cluster_size):
                if placed >= target_count:
                    break
                
                if 0 <= x < width and 0 <= y < height:
                    cell = grid["cells"][y][x]
                    if cell["tile"] == "open" and not is_spawn_zone(x, y):
                        cell["tile"] = tile_type
                        placed += 1
                
                # Random walk direction
                dx = rng.choice([-1, 0, 1])
                dy = rng.choice([-1, 0, 1])
                x = max(0, min(width - 1, x + dx))
                y = max(0, min(height - 1, y + dy))
    
    # Generate terrain clusters
    if target_walls > 0:
        random_walker("wall", target_walls)
    if target_water > 0:
        random_walker("water", target_water)
    if target_difficult > 0:
        random_walker("difficult", target_difficult)
    
    # Sprinkle hazards on non-blocked tiles
    if hazard_ids and hazard_chance > 0:
        for y in range(height):
            for x in range(width):
                if is_spawn_zone(x, y):
                    continue
                cell = grid["cells"][y][x]
                tile = get_tile(cell["tile"])
                if not tile.get("blocked", False):
                    if rng.random() < hazard_chance:
                        cell["hazard"] = rng.choice(hazard_ids)
    
    # Ensure spawn zones are clear
    for y in range(height):
        for x in range(spawn_cols_left):
            grid["cells"][y][x] = {"tile": "open", "hazard": None}
        for x in range(width - spawn_cols_right, width):
            grid["cells"][y][x] = {"tile": "open", "hazard": None}
    
    return grid

def render_grid_html(grid: dict, selected_actor: dict | None, reachable: dict | None, 
                     show_coords: bool, edit_mode: bool) -> str:
    """
    Render grid as HTML canvas with JavaScript for interaction.
    Returns HTML string to be rendered via st.components.v1.html.
    """
    width = grid["width"]
    height = grid["height"]
    cell_size = 28  # pixels per cell
    canvas_width = width * cell_size + 2
    canvas_height = height * cell_size + 2
    
    # Build cell data as JSON using tiles.json
    cells_data = []
    for y in range(height):
        row = []
        for x in range(width):
            cell = grid["cells"][y][x]
            tile_id = cell.get("tile", "open")
            hazard = cell.get("hazard")
            tile = get_tile(tile_id)
            color = tile.get("color", "#e8e8e8")
            blocked = tile.get("blocked", False)
            row.append({
                "tile": tile_id,
                "color": color,
                "hazard": hazard,
                "blocked": blocked
            })
        cells_data.append(row)
    
    # Build actor data
    actors_data = []
    for i, actor in enumerate(st.session_state.get("party", [])):
        pos = actor.get("pos")
        if pos:
            actors_data.append({
                "kind": "party",
                "idx": i,
                "x": pos["x"],
                "y": pos["y"],
                "name": actor.get("name", f"PC{i+1}")[:6],
                "color": "#2060c0"
            })
    for i, actor in enumerate(st.session_state.get("enemies", [])):
        pos = actor.get("pos")
        if pos:
            actors_data.append({
                "kind": "enemy",
                "idx": i,
                "x": pos["x"],
                "y": pos["y"],
                "name": actor.get("name", f"E{i+1}")[:6],
                "color": "#c02020"
            })
    
    # Selected actor info
    sel_x, sel_y = -1, -1
    if selected_actor:
        kind = selected_actor.get("kind")
        idx = selected_actor.get("idx")
        if kind == "party" and idx < len(st.session_state.get("party", [])):
            pos = st.session_state.party[idx].get("pos")
            if pos:
                sel_x, sel_y = pos["x"], pos["y"]
        elif kind == "enemy" and idx < len(st.session_state.get("enemies", [])):
            pos = st.session_state.enemies[idx].get("pos")
            if pos:
                sel_x, sel_y = pos["x"], pos["y"]
    
    # Reachable cells
    reachable_set = list(reachable.keys()) if reachable else []
    
    html = f'''
<!DOCTYPE html>
<html>
<head>
<style>
body {{ margin: 0; padding: 0; font-family: Arial, sans-serif; }}
canvas {{ border: 1px solid #333; cursor: pointer; }}
#info {{ font-size: 11px; color: #666; margin-top: 4px; }}
</style>
</head>
<body>
<canvas id="grid" width="{canvas_width}" height="{canvas_height}"></canvas>
<div id="info">Click to select/move</div>
<script>
const CELL_SIZE = {cell_size};
const WIDTH = {width};
const HEIGHT = {height};
const cells = {json.dumps(cells_data)};
const actors = {json.dumps(actors_data)};
const selX = {sel_x};
const selY = {sel_y};
const reachable = new Set({json.dumps([[r[0], r[1]] for r in reachable_set])}.map(p => p[0] + "," + p[1]));
const showCoords = {str(show_coords).lower()};
const editMode = {str(edit_mode).lower()};

const canvas = document.getElementById("grid");
const ctx = canvas.getContext("2d");

function draw() {{
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    // Draw cells
    for (let y = 0; y < HEIGHT; y++) {{
        for (let x = 0; x < WIDTH; x++) {{
            const cell = cells[y][x];
            const px = x * CELL_SIZE + 1;
            const py = y * CELL_SIZE + 1;
            
            // Base color
            ctx.fillStyle = cell.color;
            ctx.fillRect(px, py, CELL_SIZE - 1, CELL_SIZE - 1);
            
            // Reachable highlight
            if (reachable.has(x + "," + y) && !cell.blocked) {{
                ctx.fillStyle = "rgba(100, 200, 100, 0.3)";
                ctx.fillRect(px, py, CELL_SIZE - 1, CELL_SIZE - 1);
            }}
            
            // Hazard indicator
            if (cell.hazard) {{
                ctx.fillStyle = "rgba(255, 100, 0, 0.4)";
                ctx.beginPath();
                ctx.arc(px + CELL_SIZE/2, py + CELL_SIZE/2, 4, 0, Math.PI * 2);
                ctx.fill();
            }}
            
            // Grid lines
            ctx.strokeStyle = "#999";
            ctx.lineWidth = 0.5;
            ctx.strokeRect(px, py, CELL_SIZE - 1, CELL_SIZE - 1);
            
            // Coordinates
            if (showCoords) {{
                ctx.fillStyle = "#666";
                ctx.font = "7px Arial";
                ctx.fillText(x + "," + y, px + 1, py + 8);
            }}
        }}
    }}
    
    // Draw selected cell highlight
    if (selX >= 0 && selY >= 0) {{
        const px = selX * CELL_SIZE + 1;
        const py = selY * CELL_SIZE + 1;
        ctx.strokeStyle = "#ffcc00";
        ctx.lineWidth = 3;
        ctx.strokeRect(px + 1, py + 1, CELL_SIZE - 3, CELL_SIZE - 3);
    }}
    
    // Draw actors
    for (const actor of actors) {{
        const px = actor.x * CELL_SIZE + 1;
        const py = actor.y * CELL_SIZE + 1;
        
        // Actor background
        ctx.fillStyle = actor.color;
        ctx.fillRect(px + 2, py + 2, CELL_SIZE - 5, CELL_SIZE - 5);
        
        // Actor name
        ctx.fillStyle = "#fff";
        ctx.font = "bold 8px Arial";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(actor.name, px + CELL_SIZE/2, py + CELL_SIZE/2);
    }}
}}

canvas.addEventListener("click", function(e) {{
    const rect = canvas.getBoundingClientRect();
    const x = Math.floor((e.clientX - rect.left - 1) / CELL_SIZE);
    const y = Math.floor((e.clientY - rect.top - 1) / CELL_SIZE);
    
    if (x >= 0 && x < WIDTH && y >= 0 && y < HEIGHT) {{
        // Send click to Streamlit via query params
        const url = new URL(window.parent.location);
        url.searchParams.set("grid_click_x", x);
        url.searchParams.set("grid_click_y", y);
        url.searchParams.set("grid_click_t", Date.now());
        window.parent.history.replaceState({{}}, "", url);
        
        // Also update info
        const cell = cells[y][x];
        document.getElementById("info").textContent = 
            "Clicked: (" + x + "," + y + ") - " + cell.tile + 
            (cell.hazard ? " [" + cell.hazard + "]" : "");
    }}
}});

draw();
</script>
</body>
</html>
'''
    return html

# ==============
# ATTACK HELPERS
# ==============
# Unified helpers to read attack fields consistently across the codebase.
# Standardized fields: name, to_hit (int), damage (str), damage_type (str optional), reach (opt), range (opt), source (opt)

def get_attack_to_hit(a: dict) -> int:
    """
    Extract to_hit bonus from an attack dict.
    Supports both 'to_hit' and legacy 'attack_bonus' fields.
    Returns 0 if missing or invalid.
    """
    if not isinstance(a, dict):
        return 0
    val = a.get("to_hit")
    if val is None:
        val = a.get("attack_bonus")
    if val is None:
        val = a.get("bonus")
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        s = val.strip()
        if s.startswith(("+", "-")) and s[1:].isdigit():
            return int(s)
        if s.isdigit():
            return int(s)
    return 0


def get_attack_damage(a: dict) -> str:
    """
    Extract damage string from an attack dict.
    Returns "—" if missing or invalid.
    """
    if not isinstance(a, dict):
        return "—"
    val = a.get("damage")
    if val is None:
        val = a.get("damage_dice")
    if val is None:
        return "—"
    if isinstance(val, str) and val.strip():
        return val.strip()
    return "—"


def get_attack_damage_type(a: dict) -> str:
    """
    Extract damage type string from an attack dict.
    Returns empty string if missing.
    """
    if not isinstance(a, dict):
        return ""
    val = a.get("damage_type") or a.get("damage_type_name") or ""
    return str(val).strip()


def normalize_attack(a: dict) -> dict:
    """
    Normalize an attack dict to ensure it has all standard fields.
    This creates a new dict with consistent field names.
    """
    if not isinstance(a, dict):
        return {"name": "Attack", "to_hit": 0, "damage": "—", "damage_type": "", "source": "unknown"}
    return {
        "name": a.get("name", "Attack"),
        "to_hit": get_attack_to_hit(a),
        "damage": get_attack_damage(a),
        "damage_type": get_attack_damage_type(a),
        "reach": a.get("reach"),
        "range": a.get("range"),
        "source": a.get("source", ""),
    }


# ==============
# STATE VALIDATION
# ==============

def debug_validate_state() -> list:
    """
    Validate session state for schema consistency.
    Returns a list of warning messages (empty if all valid).
    """
    warnings = []
    
    # Validate initiative_order entries
    for i, ent in enumerate(st.session_state.get("initiative_order", [])):
        kind = ent.get("kind")
        if kind not in {"party", "enemy"}:
            warnings.append(f"Initiative entry {i} has invalid kind '{kind}' (expected 'party' or 'enemy')")
    
    # Validate party attacks
    for pi, char in enumerate(st.session_state.get("party", [])):
        char_name = char.get("name", f"Party member {pi}")
        for ai, atk in enumerate(char.get("attacks", [])):
            if not isinstance(atk, dict):
                warnings.append(f"{char_name} attack {ai}: not a dict")
                continue
            if not atk.get("name"):
                warnings.append(f"{char_name} attack {ai}: missing 'name'")
            to_hit = atk.get("to_hit", atk.get("attack_bonus"))
            if to_hit is not None and not isinstance(to_hit, (int, float)):
                warnings.append(f"{char_name} attack '{atk.get('name', ai)}': to_hit is not an int")
            dmg = atk.get("damage")
            if dmg is not None and not isinstance(dmg, str):
                warnings.append(f"{char_name} attack '{atk.get('name', ai)}': damage is not a string")
    
    # Validate enemy attacks
    for ei, enemy in enumerate(st.session_state.get("enemies", [])):
        enemy_name = enemy.get("name", f"Enemy {ei}")
        for ai, atk in enumerate(enemy.get("attacks", [])):
            if not isinstance(atk, dict):
                warnings.append(f"{enemy_name} attack {ai}: not a dict")
                continue
            if not atk.get("name"):
                warnings.append(f"{enemy_name} attack {ai}: missing 'name'")
            to_hit = atk.get("to_hit", atk.get("attack_bonus"))
            if to_hit is not None and not isinstance(to_hit, (int, float)):
                warnings.append(f"{enemy_name} attack '{atk.get('name', ai)}': to_hit is not an int")
            dmg = atk.get("damage")
            if dmg is not None and not isinstance(dmg, str):
                warnings.append(f"{enemy_name} attack '{atk.get('name', ai)}': damage is not a string")
    
    return warnings


# ---------------- Page Config ----------------
st.set_page_config(page_title="Virtual DM – Session Manager", layout="wide")

# ---------------- Sidebar: Navigation + Settings ----------------
with st.sidebar:
    st.markdown("# 🎲 Virtual DM")
    st.caption("Solo & Assisted Play")
    
    st.markdown("---")
    
    # Navigation
    st.markdown("### 📍 Navigation")
    
    # Determine current page based on boot_mode
    boot_mode = st.session_state.get("boot_mode")
    
    # Navigation buttons
    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("🏠", help="Session", use_container_width=True):
            st.session_state.boot_mode = None
            st.rerun()
    with nav_col2:
        if st.button("⚙️", help="Setup", use_container_width=True):
            st.session_state.boot_mode = "new"
            st.rerun()
    with nav_col3:
        is_running = boot_mode == "running"
        if st.button("⚔️", help="Running", use_container_width=True, disabled=not is_running):
            pass  # Already on running if enabled
    
    # Show current page indicator
    if boot_mode is None:
        st.info("📍 **Session** - Choose how to begin")
    elif boot_mode == "load":
        st.info("📍 **Loading** - Upload a session")
    elif boot_mode == "new":
        st.info("📍 **Setup** - Configure party & enemies")
    elif boot_mode == "running":
        st.success("📍 **Running** - Session active")
    
    st.markdown("---")
    
    # Quick Stats (when running)
    if boot_mode == "running":
        st.markdown("### Quick Stats")
        party_count = len(st.session_state.get("party", []))
        enemy_count = len(st.session_state.get("enemies", []))
        in_combat = st.session_state.get("in_combat", False)
        combat_round = st.session_state.get("combat_round", 0)
        
        stat_col1, stat_col2 = st.columns(2)
        with stat_col1:
            st.metric("Party", party_count)
        with stat_col2:
            st.metric("Enemies", enemy_count)
        
        if in_combat:
            st.metric("Combat Round", combat_round)
            # current_turn() defined later, check if available
            try:
                ent = current_turn()
                if ent:
                    st.caption(f"Turn: **{ent.get('name', 'Unknown')}**")
            except NameError:
                pass
        else:
            st.caption("Not in combat")
        
        st.markdown("---")
    
    # Session Actions
    st.markdown("### 💾 Session")
    
    if boot_mode == "running":
        # Export session - serialize_state() defined later
        try:
            data = serialize_state()
            st.download_button(
                "📥 Download Session",
                data=json.dumps(data, indent=2),
                file_name=f"virtualdm_session_{st.session_state.get('session_id', 'unknown')}.json",
                mime="application/json",
                use_container_width=True
            )
        except NameError:
            st.caption("Session export available after full load")
    
    # New/Load buttons
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("🆕 New", use_container_width=True):
            st.session_state.boot_mode = "new"
            st.rerun()
    with btn_col2:
        if st.button("📂 Load", use_container_width=True):
            st.session_state.boot_mode = "load"
            st.rerun()
    
    st.markdown("---")
    
    # Settings Section
    with st.expander("⚙️ Settings", expanded=False):
        # Performance Debug Toggle
        perf_debug = st.toggle("🔍 Performance Debug", value=st.session_state.get("perf_debug", False), key="perf_debug_toggle")
        st.session_state["perf_debug"] = perf_debug
        
        if perf_debug:
            st.markdown("---")
            st.markdown("#### 📊 Performance Stats")
            
            # Clear timings at start of each render
            clear_perf_timings()
            
            # Memory stats from tracemalloc
            current, peak = tracemalloc.get_traced_memory()
            st.metric("Current Memory", f"{current / 1024 / 1024:.2f} MB")
            st.metric("Peak Memory", f"{peak / 1024 / 1024:.2f} MB")
            
            # Top memory allocations
            with st.expander("Top Memory Allocations", expanded=False):
                snapshot = tracemalloc.take_snapshot()
                top_stats = snapshot.statistics('lineno')[:10]
                for stat in top_stats:
                    st.caption(f"{stat.size / 1024:.1f} KB - {stat.traceback}")
            
            # Session state size estimate
            try:
                import sys
                state_size = sum(sys.getsizeof(v) for v in st.session_state.values())
                st.metric("Session State (shallow)", f"{state_size / 1024:.1f} KB")
            except:
                pass
            
            # Timing display placeholder - will be populated after render
            st.markdown("#### ⏱️ Function Timings")
            timing_placeholder = st.empty()
            
            # Store placeholder for later update
            st.session_state["_perf_timing_placeholder"] = timing_placeholder
    
    st.markdown("---")
    st.caption("Virtual DM v0.4")

# ---------------- SRD Database ----------------
# reminder: keep the SRD file at ../data/SRD_Monsters.json relative to this UI file.
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "data"))
SRD_CANDIDATES = ["SRD_Monsters.json", "SRD_Monsters.txt"]  # accepts either

def _read_json_file(path: str):
    """
    Small helper so all JSON loading uses the same encoding and error handling.
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)

def _resolve_srd_path():
    for name in SRD_CANDIDATES:
        p = os.path.join(DATA_DIR, name)
        if os.path.exists(p):
            st.session_state["srd_path_resolved"] = p
            return p
    st.session_state["srd_path_resolved"] = None
    return None

# --- Normalizers so any 5e-style JSON maps to our simple fields ---
def _norm_action(a: dict) -> dict:
    """Normalize an SRD-style action or attack into {name,to_hit,damage,...}."""
    name = a.get("name", "Action")

    # to-hit: support several common field names
    to_hit = (
        a.get("to_hit")
        or a.get("attack_bonus")
        or a.get("bonus")
        or 0
    )
    if isinstance(to_hit, str):
        s = to_hit.strip()
        if s.startswith(("+", "-")) and s[1:].isdigit():
            to_hit = int(s)
        elif s.isdigit():
            to_hit = int(s)
        else:
            to_hit = 0

    # damage: support "damage", "damage_dice", or first entry of a damage list
    damage = a.get("damage") or a.get("damage_dice") or "1d6"
    if isinstance(damage, list) and damage:
        part = damage[0]
        if isinstance(part, dict):
            damage = part.get("dice") or part.get("damage_dice") or part.get("damage") or "1d6"
        else:
            damage = str(part)

    if not isinstance(damage, str):
        damage = "1d6"

    out = {
        "name": name,
        "to_hit": int(to_hit) if isinstance(to_hit, int) else 0,
        "damage": damage,
    }

    # optional reach / range if present
    if "reach" in a:
        out["reach"] = a["reach"]
    if "range" in a:
        out["range"] = a["range"]

    return out

def _norm_monster(m: dict) -> dict:
    # Top-level keys vary wildly between sources; normalize to the fields our UI expects.
    name = m.get("name", "Unknown")

    # AC / HP: prefer our simple keys, else map common SRD keys
    ac = m.get("ac", m.get("armor_class"))
    if isinstance(ac, list):  # sometimes armor_class is a list of dicts
        # pick first numeric or value
        if ac and isinstance(ac[0], dict):
            ac = ac[0].get("value") or ac[0].get("ac") or 10
    if not isinstance(ac, (int, float)):
        try: ac = int(ac)
        except: ac = 10

    hp = m.get("hp", m.get("hit_points", 10))
    try: hp = int(hp)
    except: hp = 10

    # Speed: some sources store as dict {"walk":"30 ft.", "fly":"60 ft."}
    speed = m.get("speed", "")
    if isinstance(speed, dict):
        # make a compact string like "30 ft. walk, 60 ft. fly"
        parts = []
        for k, v in speed.items():
            parts.append(f"{v} {k}")
        speed = ", ".join(parts) if parts else ""

    # Ability scores: accept "abilities" or {"strength": 10,...} or {"STR":10,...}
    abilities = m.get("abilities") or {}
    if not abilities:
        cand = {}
        for key_map in [
            ("STR", ["STR", "str", "strength"]),
            ("DEX", ["DEX", "dex", "dexterity"]),
            ("CON", ["CON", "con", "constitution"]),
            ("INT", ["INT", "int", "intelligence"]),
            ("WIS", ["WIS", "wis", "wisdom"]),
            ("CHA", ["CHA", "cha", "charisma"]),
        ]:
            out_key, aliases = key_map
            val = None
            for a in aliases:
                if a in m: val = m[a]; break
                if "ability_scores" in m and a in m["ability_scores"]: val = m["ability_scores"][a]; break
                if "stats" in m and a in m["stats"]: val = m["stats"][a]; break
            if val is not None:
                try: cand[out_key] = int(val)
                except: cand[out_key] = val
        abilities = cand or {"STR":10,"DEX":10,"CON":10,"INT":10,"WIS":10,"CHA":10}

    # Traits usually arrays of dicts; keep tolerant
    traits = m.get("traits") or m.get("special_abilities") or []
    traits_norm = []
    for t in traits:
        if isinstance(t, dict):
            tname = t.get("name", "Trait")
            ttxt = t.get("text") or t.get("desc") or ""
            traits_norm.append({"name": tname, "text": ttxt})
        elif isinstance(t, str):
            traits_norm.append({"name": "Trait", "text": t})

    # Actions
    actions_raw = m.get("actions", [])
    if isinstance(actions_raw, dict):  # some sources use dict keyed by action name
        actions_raw = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in actions_raw.items()]
    actions = [_norm_action(a) for a in actions_raw if isinstance(a, (dict,))]

    # Secondary fields (tolerant)
    size = m.get("size", m.get("monster_size", "—"))
    typ = m.get("type", "—")
    alignment = m.get("alignment", "—")
    hit_dice = m.get("hit_dice", m.get("hit_die", "—"))
    saves = m.get("saves", {}) or m.get("saving_throws", {})
    skills = m.get("skills", {})
    senses = m.get("senses", m.get("sense", "—"))
    languages = m.get("languages", "—")
    cr = m.get("cr", m.get("challenge_rating", "—"))

    return {
        "name": name,
        "size": size,
        "type": typ,
        "alignment": alignment,
        "ac": ac,
        "hp": hp,
        "hit_dice": hit_dice,
        "speed": speed,
        "abilities": abilities,
        "saves": saves,
        "skills": skills,
        "senses": senses,
        "languages": languages,
        "cr": cr,
        "traits": traits_norm,
        "actions": actions
    }

@st.cache_data(show_spinner=False)
def _cached_normalize_monsters(raw_json_tuple: tuple, _version: int = 3) -> list:
    """
    Cached monster normalization. Pure function - no session state access.
    Accepts tuple of JSON strings for hashability.
    Returns list of normalized monster dicts.
    _version param forces cache invalidation when code changes.
    """
    # Parse JSON strings back to dicts
    raw_data = [json.loads(s) for s in raw_json_tuple]
    
    if not isinstance(raw_data, list):
        return []

    def _first_int(val, default=0):
        if val is None:
            return default
        if isinstance(val, int):
            return val
        if isinstance(val, float):
            return int(val)
        s = str(val)
        m = re.search(r"-?\d+", s)
        return int(m.group(0)) if m else default

    def _extract_ac(mon: dict) -> int:
        ac = mon.get("ac", mon.get("armor_class", mon.get("armorClass")))
        if isinstance(ac, int):
            return ac
        if isinstance(ac, list) and ac:
            if isinstance(ac[0], dict):
                return _first_int(ac[0].get("value") or ac[0].get("ac"), 10)
            return _first_int(ac[0], 10)
        if isinstance(ac, dict):
            return _first_int(ac.get("value") or ac.get("ac"), 10)

        return _first_int(mon.get("Armor Class"), 10)

    def _extract_hp(mon: dict) -> int:
        if "hp" in mon:
            return _first_int(mon.get("hp"), 10)
        if "hit_points" in mon:
            return _first_int(mon.get("hit_points"), 10)
        return _first_int(mon.get("Hit Points"), 10)

    def _extract_abilities(mon: dict) -> dict:
        # accepts: {"abilities": {"STR":10...}} OR {"STR":10...} OR {"strength":10...}
        abil = mon.get("abilities") or mon.get("ability_scores") or {}
        out = {}

        def grab(key, aliases):
            if isinstance(abil, dict):
                for a in aliases:
                    if a in abil:
                        return abil[a]
            for a in aliases:
                if a in mon:
                    return mon[a]
            return None

        mapping = {
            "STR": ["STR", "str", "strength"],
            "DEX": ["DEX", "dex", "dexterity"],
            "CON": ["CON", "con", "constitution"],
            "INT": ["INT", "int", "intelligence"],
            "WIS": ["WIS", "wis", "wisdom"],
            "CHA": ["CHA", "cha", "charisma"],
        }

        for k, aliases in mapping.items():
            v = grab(k, aliases)
            out[k] = _first_int(v, 10) if v is not None else 10

        return out

    def _parse_skills_to_dict(skills_val) -> dict:
        """
        Accepts:
          - dict already (keep)
          - string like "Perception +2, Stealth +4"
        Returns dict of skill -> bonus int.
        """
        if isinstance(skills_val, dict):
            cleaned = {}
            for k, v in skills_val.items():
                cleaned[str(k)] = _first_int(v, 0)
            return cleaned

        if not skills_val:
            return {}

        s = str(skills_val)
        # split on commas
        parts = [p.strip() for p in s.split(",") if p.strip()]
        out = {}
        for p in parts:
            # match "Perception +2" or "Stealth +4"
            m = re.match(r"^(.+?)\s*([+\-]\d+)\s*$", p)
            if m:
                out[m.group(1).strip()] = int(m.group(2))
        return out

    def _parse_actions_text(actions_text: str) -> list[dict]:
        """
        Best-effort parse of SRD 'Actions' string into list of {name,to_hit,damage,range,attack_type}.
        Handles patterns like:
        'Scimitar. Melee Weapon Attack: +4 to hit, reach 5 ft... Hit: 5 (1d6 + 2) slashing damage.'
        'Shortbow. Ranged Weapon Attack: +4 to hit, range 80/320 ft... Hit: 5 (1d6 + 2) piercing damage.'
        """
        if not actions_text:
            return []

        txt = re.sub(r"<[^>]+>", " ", str(actions_text))
        txt = re.sub(r"\s+", " ", txt).strip()

        chunks = re.split(r"(?<=\.)\s(?=[A-Z][A-Za-z0-9''\- ]+\.)", txt)
        parsed = []

        for ch in chunks:
            mname = re.match(r"^([A-Z][A-Za-z0-9''\- ]+)\.", ch)
            if not mname:
                continue
            name = mname.group(1).strip()

            mto = re.search(r"([+\-]\d+)\s*to hit", ch, re.IGNORECASE)
            to_hit = int(mto.group(1)) if mto else 0

            mdmg = re.search(r"\((\d+d\d+\s*(?:[+\-]\s*\d+)?)\)", ch)
            dmg = mdmg.group(1).replace(" ", "") if mdmg else ""
            
            # Determine attack type (melee vs ranged)
            attack_type = "melee"
            if re.search(r"ranged\s+(weapon\s+)?attack", ch, re.IGNORECASE):
                attack_type = "ranged"
            elif re.search(r"melee\s+or\s+ranged", ch, re.IGNORECASE):
                attack_type = "both"
            
            # Extract range - look for "range X/Y ft" or "reach X ft"
            range_ft = 5  # default melee reach
            
            # Check for ranged attack range (e.g., "range 80/320 ft")
            range_match = re.search(r"range\s+(\d+)(?:/\d+)?\s*ft", ch, re.IGNORECASE)
            if range_match:
                range_ft = int(range_match.group(1))
            else:
                # Check for reach (e.g., "reach 10 ft")
                reach_match = re.search(r"reach\s+(\d+)\s*ft", ch, re.IGNORECASE)
                if reach_match:
                    range_ft = int(reach_match.group(1))

            parsed.append({
                "name": name, 
                "to_hit": to_hit, 
                "damage": dmg or "1d6",
                "range": range_ft,
                "attack_type": attack_type
            })
        return parsed

    def _extract_actions(mon: dict) -> list[dict]:
        # 5e API-ish: actions list of dicts
        actions = mon.get("actions")
        if isinstance(actions, list):
            out = []
            for a in actions:
                if not isinstance(a, dict):
                    continue
                name = a.get("name", "Action")

                # to-hit
                to_hit = a.get("to_hit")
                if to_hit is None:
                    to_hit = a.get("attack_bonus", a.get("bonus", 0))
                to_hit = _first_int(to_hit, 0)

                # damage
                dd = a.get("damage_dice") or ""
                db = a.get("damage_bonus", 0)
                if dd:
                    dbi = _first_int(db, 0)
                    if dbi != 0:
                        sign = "+" if dbi > 0 else "-"
                        dmg = f"{dd}{sign}{abs(dbi)}"
                    else:
                        dmg = str(dd)
                else:
                    dmg = a.get("damage") or a.get("damage_dice") or ""
                    if isinstance(dmg, dict):
                        dd2 = dmg.get("damage_dice") or dmg.get("dice") or ""
                        db2 = _first_int(dmg.get("damage_bonus") or dmg.get("bonus"), 0)
                        if dd2:
                            sign = "+" if db2 > 0 else "-"
                            dmg = f"{dd2}{sign}{abs(db2)}" if db2 else dd2
                        else:
                            dmg = ""
                    dmg = str(dmg) if dmg else ""

                # Extract range from action
                range_ft = a.get("range") or a.get("reach") or 5
                if isinstance(range_ft, str):
                    rm = re.search(r"(\d+)", range_ft)
                    range_ft = int(rm.group(1)) if rm else 5
                
                # Determine attack type
                attack_type = a.get("attack_type", "melee")
                desc = a.get("desc", a.get("description", ""))
                if "ranged" in str(desc).lower() or "ranged" in name.lower():
                    attack_type = "ranged"

                out.append({
                    "name": name,
                    "to_hit": int(to_hit),
                    "damage": (dmg or "1d6"),
                    "damage_type": a.get("damage_type") or a.get("damage_type_name") or "",
                    "range": int(range_ft),
                    "attack_type": attack_type,
                })
            return out

        # Text-ish SRD field
        return _parse_actions_text(mon.get("Actions", ""))

    normalized = []
    for mon in raw_data:
        if not isinstance(mon, dict):
            continue

        nm = mon.get("name") or mon.get("Name") or "Monster"

        ac = int(_extract_ac(mon))
        hp = int(_extract_hp(mon))
        abilities = _extract_abilities(mon)

        # skills & senses
        skills_raw = mon.get("skills") or mon.get("Skills") or {}
        skills = _parse_skills_to_dict(skills_raw)
        senses = mon.get("senses") or mon.get("Senses") or mon.get("sense") or ""

        actions = _extract_actions(mon)

        # attacks are derived from actions (for now: anything with a to_hit or damage)
        attacks = []
        for a in actions:
            if not isinstance(a, dict):
                continue
            if "name" not in a:
                continue
            attacks.append({
                "name": a.get("name", "Attack"),
                "to_hit": _first_int(a.get("to_hit"), _first_int(a.get("attack_bonus"), 0)),
                "damage": a.get("damage") or a.get("damage_dice") or "1d6",
                "damage_type": a.get("damage_type", "") or "",
            })

        normalized.append({
            "name": nm,
            "ac": ac,
            "hp": hp,
            "max_hp": hp,
            "abilities": abilities,
            "skills": skills,
            "senses": str(senses) if senses is not None else "",
            "actions": actions,
            "attacks": attacks,
            # keep src copy for debugging / future parsing
            "_raw": mon,
        })

    return normalized

def load_srd_monsters():
    """
    Load SRD monsters from JSON and normalize into ONE consistent schema our app uses.
    Uses caching to avoid re-parsing on every Streamlit rerun.
    """
    with perf_timer("load_srd_monsters"):
        if "srd_enemies" in st.session_state and st.session_state.srd_enemies:
            return st.session_state.srd_enemies
        
        base_dir = os.path.dirname(__file__)
        candidates = [
            os.path.join(base_dir, "..", "data", "SRD_Monsters.json"),
            os.path.join(base_dir, "..", "data", "SRD_Monsters.txt"),
            os.path.join(base_dir, "SRD_Monsters.json"),
            os.path.join(base_dir, "SRD_Monsters.txt"),
        ]
        
        path = _find_data_file(candidates)
        st.session_state.srd_enemies_path = path or ""
        
        if not path:
            st.session_state.srd_enemies = []
            return []
        
        # Use cached JSON loader
        raw, _ = _cached_load_json(path)
        if raw is None:
            st.session_state.srd_enemies = []
            return []
        
        # Handle wrapped data
        if isinstance(raw, dict):
            raw = raw.get("monsters") or raw.get("data") or raw.get("results") or list(raw.values())
        
        if not isinstance(raw, list):
            st.session_state.srd_enemies = []
            return []
        
        # Use cached normalization (convert to tuple for hashability)
        # _version=3: Added range and attack_type to action parsing
        normalized = _cached_normalize_monsters(tuple(json.dumps(m) for m in raw), _version=3)
        
        st.session_state.srd_enemies = normalized
        return normalized

@st.cache_data(show_spinner=False)
def _cached_normalize_conditions(data_json: str) -> dict:
    """Cached condition normalization. Pure function."""
    data = json.loads(data_json)
    
    # supports multiple formats:
    # 1. {"conditions": [...]} - list under "conditions" key
    # 2. [...] - just a list
    # 3. {"prone": {...}, "stunned": {...}} - dict keyed by condition name
    
    if isinstance(data, dict) and "conditions" in data:
        conditions = data["conditions"]
    elif isinstance(data, list):
        conditions = data
    elif isinstance(data, dict):
        # Dict keyed by condition name - convert to list format
        conditions = list(data.values())
    else:
        conditions = []

    # normalize into a dict keyed by condition name
    out = {}
    for c in conditions or []:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        out[name] = c
    return out

def load_srd_conditions():
    """
    Load SRD conditions from JSON. Uses caching.
    """
    with perf_timer("load_srd_conditions"):
        if "srd_conditions" in st.session_state and st.session_state["srd_conditions"]:
            return st.session_state["srd_conditions"]
        
        base_dir = os.path.dirname(__file__)
        candidates = [
            os.path.join(base_dir, "SRD_Conditions.json"),
            os.path.join(base_dir, "..", "data", "SRD_Conditions.json"),
        ]

        path = _find_data_file(candidates)
        
        if not path:
            st.session_state["srd_conditions"] = {}
            st.session_state["srd_conditions_path"] = None
            return {}

        data, _ = _cached_load_json(path)
        if data is None:
            st.session_state["srd_conditions"] = {}
            st.session_state["srd_conditions_path"] = path
            return {}

        out = _cached_normalize_conditions(json.dumps(data))
        st.session_state["srd_conditions"] = out
        st.session_state["srd_conditions_path"] = path
        return out

# ---------------- SRD Spells Loader ----------------

def _parse_spell_damage_from_description(desc: str) -> tuple:
    """
    Extract damage dice and type from spell description.
    Returns (damage_dice, damage_type) or (None, None) if not found.
    """
    if not desc:
        return None, None
    
    # Pattern: "takes XdY damage_type damage" or "XdY damage_type damage"
    damage_pattern = r'(\d+d\d+(?:\s*\+\s*\d+)?)\s+(\w+)\s+damage'
    match = re.search(damage_pattern, desc, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2).capitalize()
    
    # Simpler pattern: just "XdY damage"
    simple_pattern = r'(\d+d\d+(?:\s*\+\s*\d+)?)\s+damage'
    match = re.search(simple_pattern, desc, re.IGNORECASE)
    if match:
        return match.group(1), None
    
    return None, None

def _parse_spell_save_from_description(desc: str) -> str | None:
    """
    Extract save type from spell description.
    Returns ability abbreviation (STR, DEX, etc.) or None.
    """
    if not desc:
        return None
    
    # Pattern: "Strength saving throw", "Dexterity save", etc.
    save_pattern = r'(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s+sav'
    match = re.search(save_pattern, desc, re.IGNORECASE)
    if match:
        ability_map = {
            "strength": "STR",
            "dexterity": "DEX", 
            "constitution": "CON",
            "intelligence": "INT",
            "wisdom": "WIS",
            "charisma": "CHA"
        }
        return ability_map.get(match.group(1).lower())
    return None

def _is_spell_attack(desc: str) -> bool:
    """Check if spell description indicates a spell attack roll."""
    if not desc:
        return False
    desc_lower = desc.lower()
    return "spell attack" in desc_lower or "make a ranged spell attack" in desc_lower or "make a melee spell attack" in desc_lower

def _parse_range_feet(range_str: str) -> int | None:
    """Extract numeric range in feet from range string."""
    if not range_str:
        return None
    match = re.search(r'(\d+)\s*(?:feet|ft)', range_str, re.IGNORECASE)
    if match:
        return int(match.group(1))
    if "touch" in range_str.lower():
        return 5
    if "self" in range_str.lower():
        return 0
    return None

def normalize_spell(raw: dict) -> dict:
    """
    Normalize a raw SRD spell into our standard action schema.
    Schema: {name, level, school, casting_time, range, components, duration, 
             save, dc, to_hit, damage, damage_type, description, type, action_type}
    """
    desc = raw.get("description", "")
    
    # Parse damage from description
    damage, damage_type = _parse_spell_damage_from_description(desc)
    
    # Parse save type from description
    save = _parse_spell_save_from_description(desc)
    
    # Determine if it's a spell attack
    is_attack = _is_spell_attack(desc)
    
    # Map actionType to our action_type
    action_type_map = {
        "action": "standard",
        "bonusAction": "quick",
        "bonus action": "quick",
        "reaction": "immediate",
        "1 minute": "standard",  # ritual/long cast times default to standard
    }
    raw_action = raw.get("actionType", "action")
    action_type = action_type_map.get(raw_action, "standard")
    
    # Determine spell type
    if is_attack:
        spell_type = "spell_attack"
    elif save:
        spell_type = "spell_save"
    else:
        spell_type = "spell_utility"
    
    # Parse range
    range_feet = _parse_range_feet(raw.get("range", ""))
    
    # Components as string
    components = raw.get("components", [])
    if isinstance(components, list):
        components = ", ".join(c.upper() for c in components)
    
    return {
        "name": raw.get("name", "Unknown Spell"),
        "level": raw.get("level", 0),
        "school": raw.get("school", "").capitalize(),
        "casting_time": raw.get("castingTime") or raw.get("actionType", "action"),
        "range": raw.get("range", "Self"),
        "range_feet": range_feet,
        "components": components,
        "material": raw.get("material"),
        "duration": raw.get("duration", "Instantaneous"),
        "concentration": raw.get("concentration", False),
        "ritual": raw.get("ritual", False),
        "save": save,
        "dc": None,  # DC is computed from caster's spellcasting ability + proficiency
        "to_hit": None,  # to_hit is computed from caster's spellcasting ability + proficiency
        "damage": damage,
        "damage_type": damage_type,
        "description": desc,
        "classes": raw.get("classes", []),
        "type": spell_type,
        "action_type": action_type,
        # For cantrips with scaling
        "cantrip_upgrade": raw.get("cantripUpgrade"),
        "higher_level": raw.get("higherLevelSlot"),
    }

@st.cache_data(show_spinner=False)
def _cached_normalize_spells(spells_json_tuple: tuple) -> list:
    """Cached spell normalization. Pure function."""
    return [normalize_spell(json.loads(s)) for s in spells_json_tuple]

def load_srd_spells() -> list:
    """
    Load SRD spells from JSON and normalize into our spell schema.
    Uses caching for performance.
    """
    with perf_timer("load_srd_spells"):
        if "srd_spells" in st.session_state:
            return st.session_state["srd_spells"]
        
        data, path = _load_json_from_candidates(DATA_DIR, ["SRD_Spells.json"])
        st.session_state["srd_spells_path"] = path
        
        if not isinstance(data, list):
            st.session_state["srd_spells"] = []
            return []
        
        # Use cached normalization
        normalized = _cached_normalize_spells(tuple(json.dumps(s) for s in data))
        st.session_state["srd_spells"] = normalized
        return normalized

def get_spells_for_class(class_name: str, max_level: int = 1) -> tuple:
    """
    Get cantrips and leveled spells available to a class.
    Returns (cantrips, level_1_spells).
    """
    spells = load_srd_spells()
    class_lower = class_name.lower()
    
    cantrips = [s for s in spells if s["level"] == 0 and class_lower in [c.lower() for c in s.get("classes", [])]]
    level_1 = [s for s in spells if s["level"] == 1 and class_lower in [c.lower() for c in s.get("classes", [])]]
    
    return cantrips, level_1

def spell_to_action(spell: dict, caster: dict) -> dict:
    """
    Convert a normalized spell into an action that can be added to char['actions'].
    Computes to_hit and DC based on caster's spellcasting ability.
    """
    # Get spellcasting ability modifier
    spell_ability = caster.get("spellcasting_ability", "INT")
    ability_score = caster.get("abilities", {}).get(spell_ability, 10)
    ability_mod = (ability_score - 10) // 2
    
    # Proficiency bonus (assume +2 at level 1)
    prof_bonus = caster.get("proficiency_bonus", 2)
    
    # Compute to_hit for spell attacks
    to_hit = None
    if spell.get("type") == "spell_attack":
        to_hit = ability_mod + prof_bonus
    
    # Compute DC for spell saves
    dc = None
    if spell.get("save"):
        dc = 8 + ability_mod + prof_bonus
    
    return {
        "name": spell["name"],
        "type": spell["type"],
        "action_type": spell["action_type"],
        "to_hit": to_hit,
        "dc": dc,
        "save": spell.get("save"),
        "damage": spell.get("damage"),
        "damage_type": spell.get("damage_type"),
        "range": spell.get("range_feet") or 60,  # default 60ft for spells
        "description": spell.get("description", ""),
        "spell_level": spell.get("level", 0),
        "concentration": spell.get("concentration", False),
        "components": spell.get("components", ""),
    }

# ---------------- Combat State + Initiative System ----------------

def init_combat_state():
    ss = st.session_state
    ss.setdefault("in_combat", False)
    ss.setdefault("combat_round", 0)
    ss.setdefault("initiative_order", [])
    ss.setdefault("turn_index", 0)

init_combat_state()

def _dex_mod_from_char(c):
    abil = c.get("abilities", {})
    try:
        return (int(abil.get("DEX", 10)) - 10) // 2
    except:
        return 0

def _dex_mod_from_enemy(e):
    dex = e.get("dex") or e.get("dexterity") or e.get("abilities", {}).get("DEX", 10)
    try:
        return (int(dex) - 10) // 2
    except:
        return 0

def roll_initiative_party():
    out = []
    for i, ch in enumerate(st.session_state.party):
        dm = _dex_mod_from_char(ch)
        roll = random.randint(1,20) + dm
        out.append({
            "name": ch.get("name","PC"),
            "kind": "party",
            "idx": i,
            "init": roll,
            "dex_mod": dm
        })
    return out

def roll_initiative_enemies():
    out = []
    for i, en in enumerate(st.session_state.enemies):
        dm = _dex_mod_from_enemy(en)
        roll = random.randint(1,20) + dm
        out.append({
            "name": en.get("name","Enemy"),
            "kind": "enemy",
            "idx": i,
            "init": roll,
            "dex_mod": dm
        })
    return out

def start_combat():
    pcs = roll_initiative_party()
    foes = roll_initiative_enemies()
    full = pcs + foes
    full.sort(key=lambda x: (x["init"], x["dex_mod"]), reverse=True)
    st.session_state.initiative_order = full
    st.session_state.in_combat = True
    st.session_state.combat_round = 1
    st.session_state.turn_index = 0
    reset_actions_for_new_turn()

def current_turn():
    order = st.session_state.initiative_order
    idx = st.session_state.turn_index
    if not order: 
        return None
    if idx < 0 or idx >= len(order):
        return None
    return order[idx]

def next_turn():
    if not st.session_state.in_combat:
        return
    order_len = len(st.session_state.initiative_order)
    if order_len == 0:
        return
    
    # Before advancing, tick conditions on the current actor
    ent = current_turn()
    if ent:
        kind = ent.get("kind")
        idx = ent.get("idx")
        actor = None
        actor_name = ent.get("name", "Unknown")
        
        if kind == "party" and idx is not None and 0 <= idx < len(st.session_state.party):
            actor = st.session_state.party[idx]
        elif kind == "enemy" and idx is not None and 0 <= idx < len(st.session_state.enemies):
            actor = st.session_state.enemies[idx]
        
        if actor:
            messages = tick_end_of_turn(actor, actor_name)
            for msg in messages:
                st.session_state.chat_log.append(("System", msg))
    
    # Advance to next turn
    st.session_state.turn_index += 1
    if st.session_state.turn_index >= order_len:
        st.session_state.turn_index = 0
        st.session_state.combat_round += 1
    reset_actions_for_new_turn()

def end_combat():
    st.session_state.in_combat = False
    st.session_state.initiative_order = []
    st.session_state.combat_round = 0
    st.session_state.turn_index = 0

def reset_actions_for_new_turn():
    """
    Reset the current actor's action availability at the start of each turn.
    """
    st.session_state["current_actions"] = {
        "move": True,
        "standard": True,
        "quick": True,
        "immediate": True,
    }

def ensure_action_state():
    """
    Make sure current_actions exists; called by any logic that spends actions.
    """
    if "current_actions" not in st.session_state:
        reset_actions_for_new_turn()


def can_spend(action_type: str) -> bool:
    """
    Check if the given action type is still available this turn.
    Valid action_type values: "move", "standard", "quick", "immediate"
    Returns True if available, False if already spent.
    """
    ensure_action_state()
    action_type = action_type.lower().strip()
    return st.session_state["current_actions"].get(action_type, False)


def spend(action_type: str) -> None:
    """
    Mark the given action type as spent for this turn.
    Valid action_type values: "move", "standard", "quick", "immediate"
    """
    ensure_action_state()
    action_type = action_type.lower().strip()
    if action_type in st.session_state["current_actions"]:
        st.session_state["current_actions"][action_type] = False


def explain_action_state() -> str:
    """
    Returns a human-readable string showing available actions.
    Example: "Move: ✅ Standard: ❌ Quick: ✅ Immediate: ✅"
    """
    ensure_action_state()
    ca = st.session_state["current_actions"]
    parts = []
    for action_type in ["move", "standard", "quick", "immediate"]:
        available = ca.get(action_type, False)
        icon = "✅" if available else "❌"
        label = action_type.capitalize()
        parts.append(f"{label}: {icon}")
    return " | ".join(parts)


def get_action_type_for_attack(action_obj: dict | None) -> str:
    """
    Determine what action type an attack/action requires.
    Checks the action_type field from ACTION_SCHEMA, defaults to "standard".
    """
    if not action_obj or not isinstance(action_obj, dict):
        return "standard"
    action_type = action_obj.get("action_type", "standard")
    if isinstance(action_type, str) and action_type.lower() in {"move", "standard", "quick", "immediate"}:
        return action_type.lower()
    return "standard"


# ==============
# CONDITIONS SYSTEM
# ==============
# Each actor has conditions: List[{"name": str, "duration_rounds": int|None, "source": str|None}]
# duration_rounds counts down at end of that actor's turn. None = indefinite.

def ensure_conditions(actor: dict) -> list:
    """
    Ensure the actor has a conditions list. Returns the list.
    """
    if "conditions" not in actor or not isinstance(actor.get("conditions"), list):
        actor["conditions"] = []
    return actor["conditions"]


def add_condition(actor: dict, name: str, duration_rounds: int | None = None, source: str | None = None) -> None:
    """
    Add a condition to an actor. If the condition already exists, update its duration.
    """
    conditions = ensure_conditions(actor)
    
    # Check if condition already exists
    for cond in conditions:
        if cond.get("name", "").lower() == name.lower():
            # Update existing condition
            cond["duration_rounds"] = duration_rounds
            cond["source"] = source
            return
    
    # Add new condition
    conditions.append({
        "name": name,
        "duration_rounds": duration_rounds,
        "source": source,
    })


def remove_condition(actor: dict, name: str) -> bool:
    """
    Remove a condition from an actor by name.
    Returns True if removed, False if not found.
    """
    conditions = ensure_conditions(actor)
    for i, cond in enumerate(conditions):
        if cond.get("name", "").lower() == name.lower():
            conditions.pop(i)
            return True
    return False


def actor_has_condition(actor: dict, name: str) -> bool:
    """
    Check if an actor has a specific condition.
    """
    conditions = ensure_conditions(actor)
    for cond in conditions:
        if cond.get("name", "").lower() == name.lower():
            return True
    return False


def get_condition_display(cond: dict) -> str:
    """
    Return a display string for a condition.
    Example: "Prone (2 rounds)" or "Poisoned (indefinite)"
    """
    name = cond.get("name", "Unknown")
    duration = cond.get("duration_rounds")
    source = cond.get("source")
    
    if duration is None:
        dur_str = "indefinite"
    elif duration == 1:
        dur_str = "1 round"
    else:
        dur_str = f"{duration} rounds"
    
    result = f"{name} ({dur_str})"
    if source:
        result += f" [from {source}]"
    return result


def tick_end_of_turn(actor: dict, actor_name: str) -> list:
    """
    Called at the end of an actor's turn to tick down condition durations.
    Returns a list of log messages for expired conditions.
    """
    conditions = ensure_conditions(actor)
    messages = []
    expired = []
    
    for cond in conditions:
        duration = cond.get("duration_rounds")
        if duration is not None:
            # Decrement duration
            new_duration = duration - 1
            if new_duration <= 0:
                # Condition expired
                expired.append(cond)
                messages.append(f"{actor_name}'s **{cond.get('name', 'condition')}** has expired.")
            else:
                cond["duration_rounds"] = new_duration
    
    # Remove expired conditions
    for exp in expired:
        conditions.remove(exp)
    
    return messages


def get_srd_condition_names() -> list:
    """
    Return a list of condition names from loaded SRD conditions.
    """
    srd_conds = st.session_state.get("srd_conditions", {})
    if isinstance(srd_conds, dict):
        return sorted(srd_conds.keys())
    return []


# ==============
# RANGE BAND POSITIONING
# ==============
# Lightweight positioning using range bands: engaged, near, far
# - engaged: melee range (<=5 ft)
# - near: close range (<=30 ft)
# - far: long range (>30 ft)

POSITION_BANDS = ["engaged", "near", "far"]
BAND_ORDER = {"engaged": 0, "near": 1, "far": 2}


def ensure_position_band(actor: dict) -> str:
    """
    Ensure the actor has a valid position_band. Returns the band.
    Default is "near".
    """
    band = actor.get("position_band", "near")
    if band not in POSITION_BANDS:
        band = "near"
        actor["position_band"] = band
    return band


def get_position_band(actor: dict) -> str:
    """
    Get the actor's current position band.
    """
    return ensure_position_band(actor)


def set_position_band(actor: dict, band: str) -> None:
    """
    Set the actor's position band.
    """
    if band in POSITION_BANDS:
        actor["position_band"] = band


def get_attack_max_band(attack: dict) -> str:
    """
    Determine the maximum range band an attack can reach based on its range.
    - range <= 5 (or None/melee): engaged only
    - range <= 30: near
    - range > 30: far
    """
    range_val = attack.get("range")
    reach_val = attack.get("reach")
    
    # Use reach if range not specified (melee weapons)
    if range_val is None:
        range_val = reach_val
    
    # Parse range if it's a string like "120 ft."
    if isinstance(range_val, str):
        import re
        m = re.search(r"(\d+)", range_val)
        range_val = int(m.group(1)) if m else None
    
    # Convert to int if possible
    if range_val is not None:
        try:
            range_val = int(range_val)
        except (ValueError, TypeError):
            range_val = None
    
    # Determine max band
    if range_val is None or range_val <= 5:
        return "engaged"  # melee range
    elif range_val <= 30:
        return "near"
    else:
        return "far"


def can_attack_at_band(attack: dict, target_band: str) -> bool:
    """
    Check if an attack can reach a target at the given band.
    """
    max_band = get_attack_max_band(attack)
    max_band_idx = BAND_ORDER.get(max_band, 0)
    target_band_idx = BAND_ORDER.get(target_band, 1)
    return target_band_idx <= max_band_idx


def get_relative_band(attacker: dict, target: dict) -> str:
    """
    Get the relative position band between attacker and target.
    For simplicity, we use the target's band as the relative distance.
    (In a more complex system, you'd track actual positions)
    """
    return get_position_band(target)


def explain_band_requirement(attack: dict) -> str:
    """
    Return a human-readable string explaining the attack's range requirement.
    """
    max_band = get_attack_max_band(attack)
    range_val = attack.get("range") or attack.get("reach")
    
    if max_band == "engaged":
        return "Melee (engaged only)"
    elif max_band == "near":
        return f"Range {range_val} (engaged or near)"
    else:
        return f"Range {range_val} (any band)"


def move_band(actor: dict, direction: str) -> tuple[bool, str]:
    """
    Move an actor one band in the given direction.
    direction: "closer" (toward engaged) or "away" (toward far)
    Returns (success, message).
    """
    current = get_position_band(actor)
    current_idx = BAND_ORDER.get(current, 1)
    
    if direction == "closer":
        if current_idx == 0:
            return False, "Already at engaged range, cannot move closer."
        new_idx = current_idx - 1
    elif direction == "away":
        if current_idx == 2:
            return False, "Already at far range, cannot move further away."
        new_idx = current_idx + 1
    else:
        return False, f"Invalid direction: {direction}"
    
    new_band = POSITION_BANDS[new_idx]
    actor["position_band"] = new_band
    return True, f"Moved from {current} to {new_band}."


def get_band_display(band: str) -> str:
    """
    Return a display string for a position band with icon.
    """
    icons = {"engaged": "⚔️", "near": "🏹", "far": "🔭"}
    return f"{icons.get(band, '•')} {band.capitalize()}"


# ==============
# ENEMY AI-LITE (Grid-Aware)
# ==============
# Simple enemy turn behavior using tactical grid.
# - Choose target: prefer closest reachable, then lowest HP party member
# - Move toward target if out of attack range
# - Choose attack: use first in-range attack

def get_grid_distance(pos1: dict, pos2: dict) -> int:
    """Calculate Chebyshev distance (diagonal movement allowed) between two positions."""
    if not pos1 or not pos2:
        return 999
    dx = abs(pos1.get("x", 0) - pos2.get("x", 0))
    dy = abs(pos1.get("y", 0) - pos2.get("y", 0))
    return max(dx, dy)

def get_attack_range_squares(attack: dict) -> int:
    """Get attack range in grid squares (assuming 5ft per square)."""
    grid = st.session_state.get("grid", {})
    square_size = grid.get("square_size_ft", 5)
    
    # Get range from attack - check multiple fields
    range_ft = attack.get("range") or attack.get("reach") or 5
    if isinstance(range_ft, str):
        # Parse "5 ft." or "30 ft."
        import re
        m = re.search(r"(\d+)", str(range_ft))
        range_ft = int(m.group(1)) if m else 5
    
    return max(1, int(range_ft) // square_size)

def is_target_in_attack_range(attacker: dict, target: dict, attack: dict) -> bool:
    """Check if target is within attack range on the grid."""
    attacker_pos = attacker.get("pos")
    target_pos = target.get("pos")
    
    if not attacker_pos or not target_pos:
        # Fall back to old band system if no grid positions
        target_band = get_position_band(target)
        return can_attack_at_band(attack, target_band)
    
    distance = get_grid_distance(attacker_pos, target_pos)
    attack_range = get_attack_range_squares(attack)
    
    return distance <= attack_range

def ai_choose_target(enemy: dict) -> tuple[int | None, dict | None]:
    """
    Choose a target for the enemy to attack.
    Prefers closest reachable target, then lowest current HP.
    Returns (target_idx, target_dict) or (None, None) if no valid targets.
    """
    party = st.session_state.get("party", [])
    if not party:
        return None, None
    
    # Filter to alive party members (HP > 0)
    alive = [(i, p) for i, p in enumerate(party) if int(p.get("hp", 0)) > 0]
    if not alive:
        return None, None
    
    enemy_pos = enemy.get("pos")
    
    if enemy_pos:
        # Sort by distance first, then HP
        def target_priority(item):
            idx, target = item
            target_pos = target.get("pos")
            distance = get_grid_distance(enemy_pos, target_pos) if target_pos else 999
            hp = int(target.get("hp", 0))
            return (distance, hp)
        
        alive.sort(key=target_priority)
    else:
        # Fall back to HP-based targeting
        random.shuffle(alive)
        alive.sort(key=lambda x: int(x[1].get("hp", 0)))
    
    return alive[0]


def estimate_attack_damage(attack: dict) -> float:
    """Estimate average damage from an attack's damage dice string."""
    dmg_str = attack.get("damage", "1d6")
    if not dmg_str:
        return 3.5  # default 1d6 average
    
    # Parse dice like "2d6+3" or "1d8+2"
    match = re.match(r"(\d+)d(\d+)(?:([+\-])(\d+))?", str(dmg_str).replace(" ", ""))
    if match:
        num_dice = int(match.group(1))
        die_size = int(match.group(2))
        modifier = 0
        if match.group(3) and match.group(4):
            modifier = int(match.group(4))
            if match.group(3) == "-":
                modifier = -modifier
        avg = num_dice * (die_size + 1) / 2 + modifier
        return avg
    return 3.5

def ai_choose_attack(enemy: dict, target: dict) -> tuple[dict | None, bool]:
    """
    Choose the best attack for the enemy to use against the target.
    Returns (attack_dict, needs_move) where needs_move indicates if enemy should move first.
    
    Logic:
    1. Evaluate ALL attacks (not just first one)
    2. Prefer in-range attacks over out-of-range
    3. Among in-range attacks, prefer highest damage
    4. If no attack in range, pick the one that would do most damage after moving
    """
    attacks = enemy.get("attacks", [])
    if not attacks:
        return None, False
    
    enemy_pos = enemy.get("pos")
    target_pos = target.get("pos")
    
    if enemy_pos and target_pos:
        distance = get_grid_distance(enemy_pos, target_pos)
        grid = st.session_state.get("grid", {})
        square_size = grid.get("square_size_ft", 5)
        distance_ft = distance * square_size
        
        # Categorize attacks by whether they're in range
        in_range_attacks = []
        out_of_range_attacks = []
        
        for atk in attacks:
            atk_range = atk.get("range", 5)
            atk_range_squares = max(1, atk_range // square_size)
            avg_damage = estimate_attack_damage(atk)
            
            if distance <= atk_range_squares:
                in_range_attacks.append((atk, avg_damage))
            else:
                out_of_range_attacks.append((atk, avg_damage, atk_range))
        
        # If we have in-range attacks, pick the highest damage one
        if in_range_attacks:
            in_range_attacks.sort(key=lambda x: x[1], reverse=True)
            best_attack = in_range_attacks[0][0]
            return best_attack, False
        
        # No in-range attacks - need to move
        # Pick the attack that would be best after moving
        # Prefer ranged attacks if target is far, melee if we can get close
        
        speed_ft = enemy.get("speed_ft", 30)
        max_move_squares = speed_ft // square_size
        
        # Can we get in melee range this turn?
        can_reach_melee = (distance - max_move_squares) <= 1
        
        best_attack = None
        best_score = -1
        
        for atk, avg_damage, atk_range in out_of_range_attacks:
            atk_range_squares = max(1, atk_range // square_size)
            
            # Can we get in range of this attack after moving?
            can_reach = (distance - max_move_squares) <= atk_range_squares
            
            # Score: prefer attacks we can reach, then by damage
            if can_reach:
                score = 1000 + avg_damage  # High base score for reachable attacks
            else:
                # Still might want ranged even if can't reach - closer is better
                score = avg_damage
            
            # Slight preference for ranged attacks when far away
            attack_type = atk.get("attack_type", "melee")
            if attack_type == "ranged" and distance > 2:
                score += 5
            
            if score > best_score:
                best_score = score
                best_attack = atk
        
        if best_attack:
            return best_attack, True
        
        # Fallback to first attack
        return attacks[0], True
    
    # Fall back to old band system (no grid positions)
    target_band = get_position_band(target)
    
    # Evaluate all attacks for band system
    in_range_attacks = []
    out_of_range_attacks = []
    
    for atk in attacks:
        avg_damage = estimate_attack_damage(atk)
        if can_attack_at_band(atk, target_band):
            in_range_attacks.append((atk, avg_damage))
        else:
            out_of_range_attacks.append((atk, avg_damage))
    
    if in_range_attacks:
        in_range_attacks.sort(key=lambda x: x[1], reverse=True)
        return in_range_attacks[0][0], False
    
    if out_of_range_attacks:
        out_of_range_attacks.sort(key=lambda x: x[1], reverse=True)
        return out_of_range_attacks[0][0], True
    
    return attacks[0], True


def ai_execute_move_closer(enemy: dict, enemy_name: str, target: dict = None) -> list[str]:
    """
    Execute a move action to get closer to target on the grid.
    Uses pathfinding to find best position within movement range.
    Returns list of log messages.
    """
    messages = []
    
    if not can_spend("move"):
        messages.append(f"{enemy_name} has no Move action available.")
        return messages
    
    enemy_pos = enemy.get("pos")
    grid = st.session_state.get("grid")
    
    # If no grid or position, fall back to band movement
    if not grid or not enemy_pos:
        success, msg = move_band(enemy, "closer")
        if success:
            spend("move")
            new_band = get_position_band(enemy)
            messages.append(f"{enemy_name} moves closer. {msg} (now at {new_band})")
        else:
            messages.append(f"{enemy_name} cannot move closer: {msg}")
        return messages
    
    # Get movement budget
    speed_ft = enemy.get("speed_ft", 30)
    square_size = grid.get("square_size_ft", 5)
    max_move = speed_ft // square_size
    
    # Find target position
    target_pos = target.get("pos") if target else None
    if not target_pos:
        # Find closest party member
        party = st.session_state.get("party", [])
        closest_dist = 999
        for p in party:
            p_pos = p.get("pos")
            if p_pos and int(p.get("hp", 0)) > 0:
                dist = get_grid_distance(enemy_pos, p_pos)
                if dist < closest_dist:
                    closest_dist = dist
                    target_pos = p_pos
    
    if not target_pos:
        messages.append(f"{enemy_name} has no target to move toward.")
        return messages
    
    # Find best position to move to (closest to target within movement range)
    start_x, start_y = enemy_pos["x"], enemy_pos["y"]
    target_x, target_y = target_pos["x"], target_pos["y"]
    
    # Get all reachable squares
    reachable = dijkstra_reachable(grid, start_x, start_y, max_move, enemy)
    
    if not reachable:
        messages.append(f"{enemy_name} cannot find a path to move.")
        return messages
    
    # Find the reachable square closest to target
    best_pos = None
    best_dist = get_grid_distance(enemy_pos, target_pos)
    
    for (rx, ry), cost in reachable.items():
        if rx == start_x and ry == start_y:
            continue  # Skip current position
        if is_cell_occupied(rx, ry, enemy):
            continue  # Skip occupied squares
        
        dist_to_target = get_grid_distance({"x": rx, "y": ry}, target_pos)
        if dist_to_target < best_dist:
            best_dist = dist_to_target
            best_pos = (rx, ry)
    
    if best_pos is None:
        messages.append(f"{enemy_name} is already as close as possible.")
        return messages
    
    # Execute the move
    old_x, old_y = start_x, start_y
    new_x, new_y = best_pos
    
    enemy["pos"] = {"x": new_x, "y": new_y}
    spend("move")
    
    distance_moved = get_grid_distance({"x": old_x, "y": old_y}, {"x": new_x, "y": new_y})
    messages.append(f"{enemy_name} moves from ({old_x},{old_y}) to ({new_x},{new_y}) [{distance_moved * square_size} ft]")
    
    return messages


def ai_execute_attack(enemy: dict, enemy_name: str, attack: dict, target_idx: int, target: dict) -> list[str]:
    """
    Execute an attack against the target.
    Returns list of log messages.
    """
    messages = []
    
    # Check action economy
    action_type = get_action_type_for_attack(attack)
    if not can_spend(action_type):
        messages.append(f"{enemy_name} has no {action_type.capitalize()} action available.")
        return messages
    
    # Validate range using grid if available
    if not is_target_in_attack_range(enemy, target, attack):
        enemy_pos = enemy.get("pos")
        target_pos = target.get("pos")
        if enemy_pos and target_pos:
            distance = get_grid_distance(enemy_pos, target_pos)
            attack_range = get_attack_range_squares(attack)
            grid = st.session_state.get("grid", {})
            square_size = grid.get("square_size_ft", 5)
            messages.append(f"{enemy_name} cannot reach {target.get('name', 'target')} with {attack.get('name', 'attack')} (distance: {distance * square_size} ft, range: {attack_range * square_size} ft).")
        else:
            # Fall back to band system
            target_band = get_position_band(target)
            max_band = get_attack_max_band(attack)
            messages.append(f"{enemy_name} cannot reach {target.get('name', 'target')} with {attack.get('name', 'attack')} (target at {target_band}, attack reaches {max_band}).")
        return messages
    
    # Spend the action
    spend(action_type)
    
    # Roll attack
    att_name = attack.get("name", "attack")
    to_hit = get_attack_to_hit(attack)
    target_ac = int(target.get("ac", 10))
    
    d20 = random.randint(1, 20)
    total = d20 + to_hit
    
    messages.append(f"{enemy_name} attacks {target.get('name', 'target')} with {att_name}!")
    messages.append(f"Attack roll: d20({d20}) + {to_hit} = **{total}** vs AC {target_ac}")
    
    # Critical miss
    if d20 == 1:
        messages.append("Critical miss (natural 1)!")
        return messages
    
    # Check hit
    if total >= target_ac:
        # Roll damage
        d_expr = get_attack_damage(attack)
        if d_expr == "—" or not d_expr:
            d_expr = "1d6"
        
        dmg_total, breakdown = roll_dice(d_expr)
        dmg_type = get_attack_damage_type(attack)
        
        # Apply damage
        before_hp = int(target.get("hp", 0))
        after_hp = max(0, before_hp - dmg_total)
        st.session_state.party[target_idx]["hp"] = after_hp
        
        hit_msg = f"**HIT!** {target.get('name', 'Target')} takes **{dmg_total}** damage ({breakdown})"
        if dmg_type:
            hit_msg += f" [{dmg_type}]"
        hit_msg += f". HP: {before_hp} → {after_hp}"
        messages.append(hit_msg)
        
        if after_hp == 0:
            messages.append(f"💀 {target.get('name', 'Target')} is down!")
    else:
        messages.append("**MISS!**")
    
    return messages


def ai_resolve_enemy_turn() -> list[str]:
    """
    Resolve the current enemy's turn using AI-lite logic.
    Returns list of log messages.
    """
    messages = []
    
    # Get current actor
    ent = current_turn()
    if not ent or ent.get("kind") != "enemy":
        messages.append("Not an enemy's turn.")
        return messages
    
    idx = ent.get("idx")
    if idx is None or idx >= len(st.session_state.enemies):
        messages.append("Enemy not found.")
        return messages
    
    enemy = st.session_state.enemies[idx]
    enemy_name = enemy.get("name", "Enemy")
    
    enemy_pos = enemy.get("pos")
    pos_str = f" at ({enemy_pos['x']},{enemy_pos['y']})" if enemy_pos else ""
    messages.append(f"--- {enemy_name}'s Turn (AI){pos_str} ---")
    
    # Choose target
    target_idx, target = ai_choose_target(enemy)
    if target is None:
        messages.append(f"{enemy_name} has no valid targets.")
        return messages
    
    target_pos = target.get("pos")
    target_pos_str = f" at ({target_pos['x']},{target_pos['y']})" if target_pos else ""
    distance_str = ""
    if enemy_pos and target_pos:
        dist = get_grid_distance(enemy_pos, target_pos)
        grid = st.session_state.get("grid", {})
        sq_size = grid.get("square_size_ft", 5)
        distance_str = f", distance: {dist * sq_size} ft"
    messages.append(f"Target: {target.get('name', 'Unknown')}{target_pos_str} (HP: {target.get('hp', '?')}{distance_str})")
    
    # Choose attack - AI evaluates all available attacks
    attack, needs_move = ai_choose_attack(enemy, target)
    
    if attack is None:
        messages.append(f"{enemy_name} has no attacks defined.")
        return messages
    
    # Log attack choice with range info
    atk_name = attack.get("name", "attack")
    atk_range = attack.get("range", 5)
    atk_type = attack.get("attack_type", "melee")
    avg_dmg = estimate_attack_damage(attack)
    
    if needs_move:
        messages.append(f"Choosing {atk_name} ({atk_type}, range {atk_range} ft, ~{avg_dmg:.1f} avg dmg) - needs to move closer")
    else:
        messages.append(f"Choosing {atk_name} ({atk_type}, range {atk_range} ft, ~{avg_dmg:.1f} avg dmg) - in range!")
    
    # If needs move, try to move closer first
    if needs_move:
        move_msgs = ai_execute_move_closer(enemy, enemy_name, target)
        messages.extend(move_msgs)
        
        # Re-check if attack is now in range using grid
        if not is_target_in_attack_range(enemy, target, attack):
            enemy_pos = enemy.get("pos")
            target_pos = target.get("pos")
            if enemy_pos and target_pos:
                distance = get_grid_distance(enemy_pos, target_pos)
                attack_range = get_attack_range_squares(attack)
                messages.append(f"{enemy_name} is still out of range for {attack.get('name', 'attack')} (distance: {distance} squares, range: {attack_range} squares).")
            else:
                messages.append(f"{enemy_name} is still out of range for {attack.get('name', 'attack')}.")
            return messages
    
    # Execute attack
    attack_msgs = ai_execute_attack(enemy, enemy_name, attack, target_idx, target)
    messages.extend(attack_msgs)
    
    return messages

def get_current_actor():
    """
    Return (kind, idx, actor_dict) for whoever's turn it is,
    or (None, None, None) if there is no valid current actor.
    kind is "party" or "enemy".
    """
    ent = current_turn()
    if not ent:
        return None, None, None

    kind = ent.get("kind")
    idx = ent.get("idx")

    if kind == "party":
        if 0 <= idx < len(st.session_state.party):
            return kind, idx, st.session_state.party[idx]
    elif kind == "enemy":
        if 0 <= idx < len(st.session_state.enemies):
            return kind, idx, st.session_state.enemies[idx]

    return None, None, None


def parse_player_command(text: str, party: list, enemies: list) -> dict:
    """
    Very simple parser to detect high-level action type and target from free text.
    Example: 'I swing my longsword at goblin 1'
    """
    t = text.lower()

    # Detect action type
    if any(w in t for w in ["attack", "hit", "swing", "strike", "stab", "shoot", "fire at"]):
        action_type = "attack"
    elif any(w in t for w in ["grapple", "grab", "tackle"]):
        action_type = "grapple"
    elif any(w in t for w in ["jump", "leap"]):
        action_type = "jump"
    elif any(w in t for w in ["climb"]):
        action_type = "climb"
    elif any(w in t for w in ["hide", "sneak"]):
        action_type = "stealth"
    else:
        action_type = "other"

    # Try to find a target among enemies by name substring match
    target_idx = None
    target_name = None
    for i, e in enumerate(enemies):
        name = e.get("name", "")
        if not name:
            continue
        if name.lower() in t:
            target_idx = i
            target_name = name
            break

    # Weapon hint from simple keywords (can expand later)
    weapon_name = None
    for keyword in ["longsword", "sword", "bow", "dagger", "axe", "mace", "staff"]:
        if keyword in t:
            weapon_name = keyword
            break

    return {
        "type": action_type,
        "target_idx": target_idx,
        "target_name": target_name,
        "weapon_hint": weapon_name,
        "raw": text,
    }


def roll_d20() -> int:
    """Quick helper for a single d20 roll."""
    return random.randint(1, 20)


def roll_damage_expr(dice_expr: str) -> tuple[int, str]:
    """
    Uses the existing roll_dice() helper to roll a damage expression like '1d8+3'.
    Returns (total, breakdown_str).
    """
    total, breakdown = roll_dice(dice_expr)
    return total, breakdown


def resolve_attack(text: str) -> str | None:
    """
    Attempt to resolve an attack based on the current actor's stats and the text command.
    Returns a descriptive string if handled, or None if this is not an attack action.
    """
    kind, idx, actor = get_current_actor()
    if not actor:
        return None  # no active combatant (e.g., combat not started)

    info = parse_player_command(text, st.session_state.party, st.session_state.enemies)
    if info["type"] != "attack":
        return None  # not an attack; caller can fall back to other logic

    # Enforce action economy using helpers
    if not can_spend("standard"):
        return f"{actor.get('name','The attacker')} has already used a Standard action this turn."

    # find target
    ti = info["target_idx"]
    if ti is None or ti < 0 or ti >= len(st.session_state.enemies):
        return f"{actor.get('name','The attacker')} tries to attack, but I can't find that target among the enemies."

    target = st.session_state.enemies[ti]

    # pick an attack from actor
    attacks = actor.get("attacks", [])
    if not attacks:
        return f"{actor.get('name','The attacker')} has no attacks defined."

    chosen = None
    if info["weapon_hint"]:
        for a in attacks:
            if info["weapon_hint"] in a.get("name", "").lower():
                chosen = a
                break
    if not chosen:
        # default to the primary / first attack
        idx_attack = actor.get("default_attack_index", 0)
        if 0 <= idx_attack < len(attacks):
            chosen = attacks[idx_attack]
        else:
            chosen = attacks[0]

    # Validate range band
    target_band = get_position_band(target)
    if not can_attack_at_band(chosen, target_band):
        max_band = get_attack_max_band(chosen)
        return (f"{actor.get('name','The attacker')} cannot attack {target.get('name','the target')} with {chosen.get('name','that attack')}! "
                f"Target is at **{target_band}** range, but this attack only reaches **{max_band}** range. "
                f"Use a Move action to get closer, or choose a different attack.")

    # Spend the action after all validation passes
    spend("standard")

    att_name = chosen.get("name", "attack")
    to_hit = get_attack_to_hit(chosen)
    d_expr = get_attack_damage(chosen)
    if d_expr == "—":
        d_expr = "1d6"  # fallback for missing damage

    d20 = roll_d20()
    total = d20 + to_hit
    ac = int(target.get("ac", 10))

    lines = []
    lines.append(f"{actor.get('name','The attacker')} attacks {target.get('name','the target')} with {att_name}!")
    lines.append(f"Attack roll: d20 ({d20}) + {to_hit} = **{total}** vs AC {ac}.")

    if d20 == 1:
        lines.append("Critical miss (natural 1).")
        return "\n".join(lines)

    if total >= ac:
        dmg_total, breakdown = roll_damage_expr(d_expr)
        try:
            target["hp"] = max(0, int(target.get("hp", 0)) - int(dmg_total))
        except Exception:
            # reminder: if HP is missing or non-numeric, just report damage and move on
            pass
        lines.append(f"Hit! {target.get('name','The target')} takes **{dmg_total}** damage ({breakdown}).")
        if isinstance(target.get("hp"), int):
            lines.append(f"{target.get('name','The target')} is now at **{target['hp']} HP**.")
    else:
        lines.append("Miss.")

    return "\n".join(lines)

# ---- Hybrid system skill list + ability mapping ----
SKILL_NAMES = [
    "Acrobatics",
    "Animal Handling",
    "Arcana",
    "Athletics",
    "Deception",
    "History",
    "Insight",
    "Intimidation",
    "Medicine",
    "Nature",
    "Perception",
    "Performance",
    "Persuasion",
    "Religion",
    "Sleight of Hand",
    "Stealth",
    "Survival",
    "Tinker",
    "Honor",
    "Tactics",
]

SKILL_TO_ABILITY: dict[str, str] = {
    "Acrobatics": "DEX",
    "Animal Handling": "WIS",
    "Arcana": "INT",
    "Athletics": "STR",
    "Deception": "CHA",
    "History": "INT",
    "Insight": "WIS",
    "Intimidation": "CHA",
    "Medicine": "WIS",
    "Nature": "INT",
    "Perception": "WIS",
    "Performance": "CHA",
    "Persuasion": "CHA",
    "Religion": "INT",
    "Sleight of Hand": "DEX",
    "Stealth": "DEX",
    "Survival": "WIS",
    "Tinker": "INT",
    "Honor": "CHA",
    "Tactics": "INT",
}

def _get_skill_mod(actor: dict, skill_name: str) -> int:
    """
    Compute the modifier for a given skill using the actor's abilities,
    explicit skill bonuses when present, and proficiency.
    """
    # quick mapping; we can extend this later once we have a full skill JSON

    abilities = actor.get("abilities", {})

    prof_bonus = int(actor.get("proficiency_bonus", 2))

    # if actor already has an explicit skill bonus, prefer that
    skills_blob = actor.get("skills", {})
    if isinstance(skills_blob, dict) and skill_name in skills_blob:
        try:
            return int(skills_blob[skill_name])
        except Exception:
            pass  # fall back to ability+prof below

    abil_key = SKILL_TO_ABILITY.get(skill_name)
    base = _ability_mod(abilities.get(abil_key, 10)) if abil_key else 0

    # see if they are proficient in that skill
    profs = actor.get("profs", {})
    prof_skills = []
    if isinstance(profs, dict):
        ps = profs.get("skills", [])
        if isinstance(ps, dict):
            prof_skills = list(ps.keys())
        elif isinstance(ps, list):
            prof_skills = ps

    if skill_name in prof_skills:
        return base + prof_bonus
    return base

def find_actor_from_message(msg: str):
    """Return (kind, index, blob) where kind is 'party' or 'enemy'."""
    low = msg.lower()

    # search enemies first if name is in text
    for idx, e in enumerate(st.session_state.get("enemies", [])):
        nm = str(e.get("name", "")).lower()
        if nm and nm in low:
            return "enemy", idx, e

    # then party
    for idx, c in enumerate(st.session_state.get("party", [])):
        nm = str(c.get("name", "")).lower()
        if nm and nm in low:
            return "party", idx, c

    # fall back to active turn entity
    ent = current_turn()
    if ent:
        if ent.get("kind") == "party":
            idx = ent.get("idx", 0)
            if 0 <= idx < len(st.session_state.get("party", [])):
                return "party", idx, st.session_state.party[idx]
        elif ent.get("kind") == "enemy":
            idx = ent.get("idx", 0)
            if 0 <= idx < len(st.session_state.get("enemies", [])):
                return "enemy", idx, st.session_state.enemies[idx]

    # final fallback: first party member
    if st.session_state.get("party"):
        return "party", 0, st.session_state.party[0]

    return None, None, None

def resolve_move_action(text: str) -> str | None:
    """
    Consume Move action when the current actor declares movement in chat.
    Supports range band movement: "move closer", "move away", "engage", "disengage"
    """
    kind, idx, actor = get_current_actor()
    if not actor:
        return None

    intent, ent = detect_intent(text)
    if intent != "move":
        return None

    # Enforce action economy using helpers
    if not can_spend("move"):
        return f"{actor.get('name','The character')} has already used a Move action this turn."
    
    # Determine movement direction from text
    t = text.lower()
    direction = None
    
    if any(word in t for word in ["closer", "advance", "engage", "close", "approach", "charge"]):
        direction = "closer"
    elif any(word in t for word in ["away", "retreat", "back", "disengage", "withdraw", "flee"]):
        direction = "away"
    
    actor_name = actor.get('name', 'The character')
    current_band = get_position_band(actor)
    
    if direction:
        # Attempt to move one band
        success, msg = move_band(actor, direction)
        if success:
            spend("move")
            new_band = get_position_band(actor)
            return f"{actor_name} uses a Move action: {msg} (now at **{get_band_display(new_band)}**)"
        else:
            # Don't spend the action if movement failed
            return f"{actor_name} cannot move: {msg}"
    else:
        # Generic movement without band change
        spend("move")
        where = ent.get("where") or "a new position"
        return f"{actor_name} uses a Move action to move to **{where}** (remains at **{get_band_display(current_band)}**)."

def resolve_skill_check(text: str) -> str | None:
    """
    Parse a chat message for a skill name and roll a skill check
    for the appropriate actor (PC or enemy). Consumes a Standard
    action for that actor's turn.
    """
    msg = text.strip()
    lower = msg.lower()

    # 1) detect which skill we're rolling
    skill = None
    for sk in SKILL_NAMES:
        if sk.lower() in lower:
            skill = sk
            break
    if not skill:
        return None  # not a skill check request

    # reminder: only the active combatant can roll during combat
    kind, idx, actor = get_current_actor()
    if not actor:
        return "No valid creature found to make that check."

    # 3) enforce Standard action economy using helpers
    if not can_spend("standard"):
        return f"{actor.get('name','The character')} has already used a Standard action this turn."

    # 4) choose a DC band (very rough heuristic for now)
    DC_BANDS = {
        "very_easy": 5,
        "easy": 10,
        "medium": 15,
        "hard": 20,
        "very_hard": 25,
        "nearly_impossible": 30,
    }
    base_dc = DC_BANDS["medium"]
    dc_jitter = random.choice([-2, 0, 0, 2])
    dc = max(5, base_dc + dc_jitter)

    # 5) compute modifier and roll
    mod = _get_skill_mod(actor, skill)
    d20 = roll_d20()
    total = d20 + mod

    # spend the Standard action
    spend("standard")

    actor_name = actor.get("name", "The character")
    lines = []
    lines.append(f"{actor_name} attempts a **{skill}** check (DC {dc}).")
    lines.append(f"Roll: d20 ({d20}) + {mod} = **{total}**.")

    if total >= dc:
        lines.append("Result: **Success**.")
    else:
        lines.append("Result: **Failure**.")

    return "\n".join(lines)

# ==== SRD mini-loaders for Builder (accept .json or .txt) ====
# These use the cached JSON loader for performance.

def _load_json_from_candidates(dir_path, names):
    """Load JSON from first existing file in candidates. Uses caching."""
    for nm in names:
        p = os.path.join(dir_path, nm)
        if os.path.exists(p):
            data, _ = _cached_load_json(p)
            if data is not None:
                return data, p
            return [], p
    return [], None

def load_srd_races():
    with perf_timer("load_srd_races"):
        if "srd_races" in st.session_state:
            return st.session_state["srd_races"]
        data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Races.json", "SRD_Races.txt"])
        st.session_state["srd_races_path"] = p
        result = data if isinstance(data, list) else []
        st.session_state["srd_races"] = result
        return result

def load_srd_backgrounds():
    with perf_timer("load_srd_backgrounds"):
        if "srd_backgrounds" in st.session_state:
            return st.session_state["srd_backgrounds"]
        data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Backgrounds.json", "SRD_Backgrounds.txt"])
        st.session_state["srd_backgrounds_path"] = p
        result = data if isinstance(data, list) else []
        st.session_state["srd_backgrounds"] = result
        return result

def load_srd_classes():
    with perf_timer("load_srd_classes"):
        if "srd_classes" in st.session_state:
            return st.session_state["srd_classes"]
        data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Classes.json", "SRD_Classes.txt"])
        st.session_state["srd_classes_path"] = p
        
        if isinstance(data, dict) and "classes" in data:
            data = data["classes"]

        result = data if isinstance(data, list) else []
        st.session_state["srd_classes"] = result
        return result

def load_srd_feats():
    with perf_timer("load_srd_feats"):
        if "srd_feats" in st.session_state:
            return st.session_state["srd_feats"]
        data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Feats.json", "SRD_Feats.txt"])
        st.session_state["srd_feats_path"] = p
        result = data if isinstance(data, list) else []
        st.session_state["srd_feats"] = result
        return result

def load_srd_equipment():
    with perf_timer("load_srd_equipment"):
        if "srd_equipment" in st.session_state:
            return st.session_state["srd_equipment"]
        data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Equipment.json", "SRD_Equipment.txt"])
        st.session_state["srd_equipment_path"] = p

        if isinstance(data, list):
            st.session_state["srd_equipment"] = data
            return data
        else:
            st.session_state["srd_equipment"] = []
            return []
    
# ==== Character Builder ====

def _ability_mod(score: int) -> int:
    try:
        return (int(score) - 10) // 2
    except:
        return 0


def get_total_save(char: dict, save_stat: str) -> int:
    """
    Calculate total saving throw bonus for a stat.
    Total = ability modifier + class save bonus
    """
    abilities = char.get("abilities", {})
    ability_mod = _ability_mod(abilities.get(save_stat, 10))
    
    save_bonuses = char.get("save_bonuses", {})
    class_bonus = save_bonuses.get(save_stat, 0)
    
    return ability_mod + class_bonus


def format_save_display(char: dict) -> str:
    """Format saves for display, highlighting primary saves."""
    primary = char.get("primary_saves", [])
    parts = []
    for stat in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]:
        total = get_total_save(char, stat)
        sign = "+" if total >= 0 else ""
        if stat in primary:
            parts.append(f"**{stat}** {sign}{total}")
        else:
            parts.append(f"{stat} {sign}{total}")
    return " | ".join(parts)
    
def roll_ability_scores_4d6_drop_lowest():
    """Roll 4d6 drop lowest, six times. Returns a list of six scores."""
    scores = []
    for _ in range(6):
        dice = sorted([random.randint(1, 6) for _ in range(4)])
        # drop the lowest die, sum the highest three
        scores.append(sum(dice[1:]))
    return scores

def compute_hp_level1(char: dict, class_blob: dict) -> int:
    # reminder: some class JSON uses strings like "d6 per Bard level" — extract the number safely.
    raw = class_blob.get("hit_die", 8)
    if isinstance(raw, int):
        hit_die = raw
    else:
        m = re.search(r"(\d+)", str(raw))
        hit_die = int(m.group(1)) if m else 8  # fallback d8

    con_mod = _ability_mod(char.get("abilities", {}).get("CON", 10))
    return max(1, hit_die + con_mod)

def compute_ac_from_equipment(char: dict) -> int:
    # reminder: simple AC rules good enough for Week 3 demo; expand later
    armor_list = [x.lower() for x in (char.get("equipment") or []) if isinstance(x, str)]
    armor = ", ".join(armor_list)
    dex_mod = _ability_mod(char.get("abilities", {}).get("DEX", 10))
    ac = 10 + dex_mod  # default
    if "chain mail" in armor: ac = 16               # no DEX
    elif "scale mail" in armor: ac = 14 + min(dex_mod, 2)
    elif "studded leather" in armor: ac = 12 + dex_mod
    elif "leather armor" in armor or "leather" in armor: ac = 11 + dex_mod
    if "shield" in armor: ac += 2
    return ac

WEAPON_ABILITY_DEFAULT = {
    "melee": "STR",
    "ranged": "DEX"
}

def _find_equipment_by_name(name: str) -> dict | None:
    """
    Look up an equipment item by name from the loaded SRD equipment.
    """
    eq_list = st.session_state.get("srd_equipment") or []
    name_lower = (name or "").lower()
    for item in eq_list:
        if (item.get("name") or "").lower() == name_lower:
            return item
    return None

def _is_weapon_item(item: dict) -> bool:
    """
    Basic check if an equipment item is a weapon.
    Adjust this if your SRD_Equipment format differs.
    """
    if not isinstance(item, dict):
        return False
    cat = (item.get("equipment_category") or "").lower()
    wcat = (item.get("weapon_category") or "").lower()
    return "weapon" in cat or bool(wcat)

def _choose_weapon_ability(char: dict, weapon: dict) -> str:
    """
    Decide whether this weapon should use STR or DEX.
    If it has finesse or is ranged, prefer DEX; otherwise STR.
    """
    props = [ (p.get("name") or "").lower() if isinstance(p, dict) else str(p).lower()
              for p in (weapon.get("properties") or []) ]
    rng = (weapon.get("weapon_range") or "").lower()

    if "finesse" in props or "ranged" in rng:
        return "DEX"
    return "STR"

def build_attack_from_weapon(char: dict, weapon: dict) -> dict:
    """
    Build a simple attack dict from a weapon and character stats.
    Uses BAB (Base Attack Bonus) for attack rolls.
    """
    name = weapon.get("name", "Weapon")
    ability_key = _choose_weapon_ability(char, weapon)

    abilities = char.get("abilities") or {}
    ability_score = int(abilities.get(ability_key, 10))
    ability_bonus = _ability_mod(ability_score)

    # Use BAB instead of proficiency bonus
    bab = int(char.get("bab", 0))
    
    # Check weapon proficiency - if not proficient, -4 penalty (3.5e style)
    profs = (char.get("profs") or {}).get("weapons") or []
    wcat = (weapon.get("weapon_category") or "").lower()
    wname = name.lower()
    
    # Check if proficient with this weapon type or specific weapon
    is_proficient = False
    for p in profs:
        p_lower = p.lower()
        if p_lower in wcat or p_lower in wname or wcat in p_lower:
            is_proficient = True
            break
        # Handle "simple weapons" and "martial weapons"
        if "simple" in p_lower and "simple" in wcat:
            is_proficient = True
            break
        if "martial" in p_lower and "martial" in wcat:
            is_proficient = True
            break

    # BAB + ability mod, -4 if not proficient
    nonprof_penalty = 0 if is_proficient else -4
    to_hit = bab + ability_bonus + nonprof_penalty

    dmg = weapon.get("damage") or {}
    dice_count = int(dmg.get("dice_count", 1))
    dice_value = int(dmg.get("dice_value", 6))
    damage_type = (dmg.get("damage_type", {}) or {}).get("name") or dmg.get("damage_type", "") or "bludgeoning"

    # simple "XdY+mod" string
    dmg_str = f"{dice_count}d{dice_value}"
    if ability_bonus != 0:
        sign = "+" if ability_bonus > 0 else "-"
        dmg_str += f"{sign}{abs(ability_bonus)}"

    return {
        "name": name,
        "ability": ability_key,
        "to_hit": to_hit,
        "damage": dmg_str,
        "damage_type": damage_type.lower(),
        "source": "weapon"
    }

def refresh_attacks_from_equipment(char: dict):
    """
    Rebuild char['attacks'] from weapon-type equipment items.
    Keeps any non-weapon attacks if you already added them elsewhere.
    """
    eq_names = char.get("equipment") or []
    if isinstance(eq_names, str):
        eq_names = [eq_names]

    # keep non-weapon attacks so we don't wipe things like natural claws, spells-as-attacks, etc.
    existing = char.get("attacks") or []
    non_weapon_attacks = [a for a in existing if a.get("source") != "weapon"]

    weapon_attacks: list[dict] = []
    for ename in eq_names:
        item = _find_equipment_by_name(ename)
        if not item or not _is_weapon_item(item):
            continue
        weapon_attacks.append(build_attack_from_weapon(char, item))

    char["attacks"] = non_weapon_attacks + weapon_attacks

def set_default_attack_from_kit(char: dict, kit: dict|None):
    if not kit:
        return
    attacks_in = kit.get("attacks", [])
    norm = []
    for a in attacks_in:
        nm = a.get("name", "Attack")
        to_hit = a.get("to_hit")
        if isinstance(to_hit, str) and to_hit.startswith("+") and to_hit[1:].isdigit():
            to_hit = int(to_hit)
        if not isinstance(to_hit, int):
            # fallback: PB + STR for martial by default
            to_hit = _ability_mod(char.get("abilities", {}).get("STR", 10)) + int(char.get("proficiency_bonus", 2))
        dmg = a.get("damage", "1d6")
        norm.append({"name": nm, "to_hit": int(to_hit), "damage": dmg, "reach": a.get("reach"), "range": a.get("range")})
    if norm:
        char["attacks"] = norm
        char["default_attack_index"] = 0  # reminder: used by auto-actions later

def sync_attacks_from_equipment(char: dict):
    """
    Look at char['equipment'], cross-reference against the loaded SRD equipment,
    and add weapon attacks into char['attacks'].

    This assumes st.session_state['srd_equipment'] is a list of items loaded
    from SRD_Equipment.json at startup.
    """
    eq_names = char.get("equipment") or []
    if isinstance(eq_names, str):
        eq_names = [eq_names]

    equip_db = st.session_state.get("srd_equipment") or []

    # Keep existing non-weapon attacks (natural attacks, spells, etc.)
    existing = char.get("attacks") or []
    non_weapon_attacks = [a for a in existing if a.get("source") != "weapon"]

    weapon_attacks = []

    # small helper for ability mod
    def _mod(score: int) -> int:
        return (int(score) - 10) // 2

    for eq_name in eq_names:
        name_lower = str(eq_name).strip().lower()
        item = None

        # FIRST: try exact match
        for e in equip_db:
            if str(e.get("name", "")).strip().lower() == name_lower:
                item = e
                break

        # SECOND: try contains-match (covers “long sword” → “Longsword”)
        if not item:
            for e in equip_db:
                if name_lower.replace(" ", "") in str(e.get("name", "")).replace(" ", "").lower():
                    item = e
                    break

        if not item:
            continue

        # detect if it's a weapon
        cat = str(item.get("equipment_category", "")).lower()
        wcat = str(item.get("weapon_category", "")).lower()
        if "weapon" not in cat and not wcat:
            continue  # not a weapon, skip

        # decide STR or DEX (simple finesse/ranged heuristic)
        props = []
        for p in (item.get("properties") or []):
            if isinstance(p, dict):
                props.append(str(p.get("name", "")).lower())
            else:
                props.append(str(p).lower())
        rng = str(item.get("weapon_range", "")).lower()

        if "finesse" in props or "ranged" in rng:
            ability_key = "DEX"
        else:
            ability_key = "STR"

        abilities = char.get("abilities") or {}
        ability_score = int(abilities.get(ability_key, 10))
        ability_bonus = _mod(ability_score)

        prof_bonus = int(char.get("proficiency_bonus", 2))
        # crude proficiency check: look for weapon category words in prof strings
        profs = (char.get("profs") or {}).get("weapons") or []
        weapon_prof = False
        if wcat:
            wcat_lower = wcat.lower()
            for p in profs:
                if str(p).lower() in wcat_lower:
                    weapon_prof = True
                    break

        to_hit = ability_bonus + (prof_bonus if weapon_prof else 0)

        dmg = item.get("damage") or {}
        dice_count = int(dmg.get("dice_count", 1))
        dice_value = int(dmg.get("dice_value", 6))
        dtype = ""
        dt_field = dmg.get("damage_type")
        if isinstance(dt_field, dict):
            dtype = dt_field.get("name") or ""
        elif isinstance(dt_field, str):
            dtype = dt_field
        if not dtype:
            dtype = "bludgeoning"

        dmg_str = f"{dice_count}d{dice_value}"
        if ability_bonus != 0:
            sign = "+" if ability_bonus > 0 else "-"
            dmg_str += f"{sign}{abs(ability_bonus)}"

        weapon_attacks.append({
            "name": item.get("name", "Weapon"),
            "ability": ability_key,
            "to_hit": to_hit,
            "damage": dmg_str,
            "damage_type": dtype.lower(),
            "source": "weapon"
        })

    char["attacks"] = non_weapon_attacks + weapon_attacks

def apply_race(char: dict, race: dict):
    char["race"] = race.get("name", "")

    # --- Ensure abilities exist ---
    if "abilities" not in char or not isinstance(char["abilities"], dict):
        char["abilities"] = {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10}

    # --- Ability bonuses: handle both dict and 5e-API-style list ---
    ab = race.get("ability_bonuses") or {}
    if isinstance(ab, list):
        # 5e API style:
        # "ability_bonuses": [{"name":"CON","bonus":2}, ...]
        for entry in ab:
            if not isinstance(entry, dict):
                continue
            key = entry.get("name")
            # sometimes nested: {"ability_score":{"name":"CON"}, "bonus":2}
            if not key and isinstance(entry.get("ability_score"), dict):
                key = entry["ability_score"].get("name")
            bonus = entry.get("bonus", 0)
            if key in char["abilities"]:
                char["abilities"][key] = int(char["abilities"][key]) + int(bonus)
    elif isinstance(ab, dict):

        #  Older “simple dict” format
        for k, v in ab.items():
            if k in char["abilities"]:
                char["abilities"][k] = int(char["abilities"][k]) + int(v)

    # --- Speed: API uses an int (e.g., 30) ---
    spd = race.get("speed")
    if isinstance(spd, int):
        char["speed"] = f"{spd} ft."
    elif isinstance(spd, str) and spd:
        char["speed"] = spd

    # --- Languages: API uses list of dicts with "name" ---
    langs_field = race.get("languages") or []
    new_langs = set()
    for l in langs_field:
        if isinstance(l, dict):
            name = l.get("name")
        else:
            name = str(l)
        if name:
            new_langs.add(name)

    existing_langs = set()
    if isinstance(char.get("languages"), str) and char["languages"]:
        existing_langs |= {part.strip() for part in char["languages"].split(",") if part.strip()}

    merged = existing_langs | new_langs
    if merged:
        char["languages"] = ", ".join(sorted(merged))

    # --- Traits -> Features: API uses list of dicts with "name" ---
    feats = char.setdefault("features", [])
    traits = race.get("traits") or []
    for t in traits:
        if isinstance(t, dict):
            name = t.get("name")
        else:
            name = str(t)
        if name and name not in feats:
            feats.append(name)

def apply_background(char: dict, bg: dict):
    char["background"] = bg.get("name", "")
    char.setdefault("profs", {}).setdefault("skills", [])
    skills = set(char["profs"]["skills"])
    for s in (bg.get("skills") or []):
        skills.add(s)
    char["profs"]["skills"] = sorted(skills)
    # languages (simple concat)
    if bg.get("languages"):
        existing = set((char.get("languages") or "").split(", ")) if char.get("languages") else set()
        for l in bg["languages"]:
            if l:
                existing.add(l)
        char["languages"] = ", ".join(sorted(existing))
    # features
    feats = char.setdefault("features", [])
    for f in (bg.get("features") or []):
        if f not in feats:
            feats.append(f)

def get_bab_for_level(bab_type: str, level: int) -> int:
    """
    Calculate Base Attack Bonus based on progression type and level.
    
    BAB Types:
    - "full": +1 per level (Fighter, Barbarian, Paladin, Ranger, Monk, Marshal, Spellblade)
    - "3/4": +3/4 per level (Rogue, Artificer)
    - "1/2": +1/2 per level (Cleric, Druid, Bard, Warlock, Wizard)
    - "1/4": +1/4 per level (Sorcerer)
    """
    bab_type = (bab_type or "").lower().strip()
    
    if bab_type in ("full", "1", "full bab", "+1"):
        return level
    elif bab_type in ("3/4", "¾", "three-quarter", "¾ bab"):
        return (level * 3) // 4
    elif bab_type in ("1/2", "½", "half", "half bab", "½ bab"):
        return level // 2
    elif bab_type in ("1/4", "¼", "quarter", "one-fourth", "¼ bab"):
        return level // 4
    else:
        # Default to 3/4 if not specified
        return (level * 3) // 4


def get_save_bonus_for_level(level: int) -> int:
    """
    Calculate save bonus for primary stats.
    Uses 3.5e-style progression: +2 at level 1, +1 every 2 levels after.
    """
    return 2 + (level // 2)


def apply_class_level1(char: dict, cls: dict, kit_idx: int = 0):
    """Apply a class to a character and recompute HP/AC/BAB/Saves."""
    # basic identity
    char["class"] = cls.get("name", "")
    char["level"] = 1
    char["proficiency_bonus"] = 2  # Keep for compatibility, but BAB is primary

    # make sure we have abilities to work with (needed for HP/AC)
    char.setdefault(
        "abilities",
        {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
    )
    
    # ---- BAB (Base Attack Bonus) ----
    bab_type = cls.get("base_attack_bonus", cls.get("bab_progression", "3/4"))
    char["bab_type"] = bab_type
    char["bab"] = get_bab_for_level(bab_type, 1)
    
    # ---- Save Bonuses ----
    # Primary abilities get the good save progression (+2 at level 1)
    # Other saves get +0 at level 1
    primary_abilities = cls.get("primary_abilities", [])
    # Normalize ability names to 3-letter codes
    primary_stats = []
    for ab in primary_abilities:
        ab_upper = ab.upper().strip()
        if ab_upper in ("STR", "STRENGTH"):
            primary_stats.append("STR")
        elif ab_upper in ("DEX", "DEXTERITY"):
            primary_stats.append("DEX")
        elif ab_upper in ("CON", "CONSTITUTION"):
            primary_stats.append("CON")
        elif ab_upper in ("INT", "INTELLIGENCE"):
            primary_stats.append("INT")
        elif ab_upper in ("WIS", "WISDOM"):
            primary_stats.append("WIS")
        elif ab_upper in ("CHA", "CHARISMA"):
            primary_stats.append("CHA")
    
    char["primary_saves"] = primary_stats
    save_bonus = get_save_bonus_for_level(1)
    char["save_bonuses"] = {
        "STR": save_bonus if "STR" in primary_stats else 0,
        "DEX": save_bonus if "DEX" in primary_stats else 0,
        "CON": save_bonus if "CON" in primary_stats else 0,
        "INT": save_bonus if "INT" in primary_stats else 0,
        "WIS": save_bonus if "WIS" in primary_stats else 0,
        "CHA": save_bonus if "CHA" in primary_stats else 0,
    }

    # proficiencies
    pr = char.setdefault("profs", {})
    for key, src in (
        ("saves", "primary_saves"),  # This now correctly uses primary_saves we just set
        ("armor", "armor_proficiencies"),
        ("weapons", "weapon_proficiencies"),
    ):
        pr.setdefault(key, [])
        cur = set(pr[key])
        # Try multiple field names for compatibility
        values = cls.get(src) or cls.get(src.replace("_proficiencies", "_profs")) or []
        for v in values:
            if v:
                cur.add(v)
        pr[key] = sorted(cur)
    
    # Also store primary saves in profs for display
    pr["saves"] = primary_stats.copy()

    # level 1 features
    feats = char.setdefault("features", [])
    for f in (cls.get("level_1_features") or []):
        if f not in feats:
            feats.append(f)

    # HP for level 1
    hp = compute_hp_level1(char, cls)
    char["hp"] = hp
    char["max_hp"] = hp

    # starting equipment kit
    kits = cls.get("starting_equipment_kits") or []
    kit = kits[kit_idx] if kits and 0 <= kit_idx < len(kits) else {}
    eq = set(char.get("equipment") or [])
    if kit.get("armor"):
        eq.add(kit["armor"])
    if kit.get("shield"):
        eq.add("Shield")
    if kit.get("focus"):
        eq.add(kit["focus"])
    for extra in (kit.get("extras") or []):
        eq.add(extra)
    char["equipment"] = sorted(eq)

    set_default_attack_from_kit(char, kit)

    # make sure any weapon equipment becomes attacks
    sync_attacks_from_equipment(char)

    char["ac"] = compute_ac_from_equipment(char)

def ensure_resource(char: dict, name: str, max_val: int):
    """
    Ensure char['resources'][name] exists with current/max.
    If it already exists, keep current but clamp to new max.
    """
    if max_val < 0:
        max_val = 0
    res = char.setdefault("resources", {})
    entry = res.get(name, {})
    current = entry.get("current", max_val)
    res[name] = {"current": min(current, max_val), "max": max_val}


def add_level1_class_resources_and_actions(char: dict):
    """
    For now: handle Barbarian, Bard, and Artificer level 1.
    Sets up resource pools (Rage, Bardic Performance, Crafting Reservoir)
    and adds simple class actions that the UI can display/use.
    """
    cls_name = (char.get("class") or "").strip()
    abilities = char.get("abilities", {})
    features = char.setdefault("features", [])
    actions = char.setdefault("actions", [])

    # ---- Barbarian ----
    if cls_name == "Barbarian":
        # Rage (we treat it as 1 use at level 1 for now)
        if not any("Rage" in f for f in features):
            features.append(
                "Rage (Ex): 1/minute, +2 STR/CON checks & saves, +2 WIS saves, "
                "+2 melee damage, -2 AC, resist B/P/S while raging."
            )
        ensure_resource(char, "Rage", 1)

        if not any(a.get("name") == "Rage" for a in actions):
            actions.append({
                "name": "Rage",
                "resource": "Rage",
                "description": (
                    "Bonus Action: Enter a rage for 1 minute, consuming 1 Rage use. "
                    "Applies your Rage bonuses/penalties until it ends."
                ),
            })

        # You can also add “Fast Movement” / “Illiteracy” as simple text features if you like:
        if not any("Fast Movement" in f for f in features):
            features.append("Fast Movement: Increased land speed while not in heavy armor.")
        if not any("Illiteracy" in f for f in features):
            features.append("Illiteracy: Cannot read/write unless you spend skill points to learn.")

    # ---- Bard ----
    elif cls_name == "Bard":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        lvl = int(char.get("level", 1))
        uses = max(1, cha_mod + (lvl // 2))  # matches: CHA mod + half level (min 1)
        ensure_resource(char, "Bardic Performance", uses)

        if not any("Bardic Performance" in f for f in features):
            features.append(
                "Bardic Performance: Bonus Action. Spend a use to Inspire, Sooth, "
                "or Hinder as per your performance options."
            )

        if not any(a.get("name") == "Bardic Performance" for a in actions):
            actions.append({
                "name": "Bardic Performance",
                "resource": "Bardic Performance",
                "description": (
                    "Bonus Action: Begin a performance affecting allies/enemies within 30 ft, "
                    "using your Performance die and consuming 1 use."
                ),
            })

        # If you want to mark Bardic Knowledge explicitly:
        if not any("Bardic Knowledge" in f for f in features):
            features.append(
                "Bardic Knowledge: +½ Bard level (min +1) to Knowledge checks; at 6th, all INT-based skills."
            )

    # ---- Artificer ----
    elif cls_name == "Artificer":
        int_mod = _ability_mod(abilities.get("INT", 10))
        lvl = int(char.get("level", 1))
        
        # Crafting Points scale with level (from the class table)
        crafting_points_by_level = {
            1: 2, 2: 3, 3: 3, 4: 4, 5: 4, 6: 5, 7: 5, 8: 6, 9: 6, 10: 7,
            11: 7, 12: 8, 13: 8, 14: 9, 15: 9, 16: 10, 17: 10, 18: 11, 19: 11, 20: 12
        }
        base_cp = crafting_points_by_level.get(lvl, 2)
        
        # Crafting Reservoir max = 2 × INT mod (minimum 2)
        reservoir_max = max(2, 2 * int_mod)
        ensure_resource(char, "Crafting Reservoir", reservoir_max)
        ensure_resource(char, "Crafting Points", base_cp)
        
        # Calculate gadget uses (INT mod, minimum 1)
        gadget_uses = max(1, int_mod)
        ensure_resource(char, "Gadget Uses", gadget_uses)

        # ---- Level 1 Features ----
        if not any("Crafting Reservoir" in f for f in features):
            features.append(
                f"Crafting Reservoir: Pool of {reservoir_max} points (2 × INT mod, min 2) used to craft/repair/infuse items. Refills after rest."
            )

        if not any("Infused Tools" in f for f in features):
            features.append(
                "Infused Tools: Spend 1 hour during rest to infuse a mundane item. Costs 1-2 CP. "
                "Weapon: +1 attack/damage (2 CP). Armor: +1 DEX saves (2 CP). Tools: +2 skill check (1 CP)."
            )
        
        if not any("Field Mechanic" in f for f in features):
            features.append(
                "Field Mechanic: Use Tinker skill to stabilize dying creatures or repair constructs. "
                "Can craft basic gadgets during rest."
            )

        # ---- Level 1 Actions ----
        if not any(a.get("name") == "Infused Tools" for a in actions):
            actions.append({
                "name": "Infused Tools",
                "resource": "Crafting Reservoir",
                "cost": 2,
                "action_type": "rest",
                "description": (
                    "Rest Action: Spend Crafting Reservoir points to infuse a weapon (+1 attack/damage, 2 CP), "
                    "armor (+1 DEX saves, 2 CP), or tools (+2 skill check, 1 CP) for 8 hours."
                ),
            })
        
        # Field Mechanic Gadgets
        if not any(a.get("name") == "Flash Canister" for a in actions):
            actions.append({
                "name": "Flash Canister",
                "resource": "Gadget Uses",
                "cost": 1,
                "action_type": "bonus",
                "save_dc": 8 + int_mod,
                "save_type": "DEX",
                "effect": "blinded",
                "description": (
                    f"Bonus Action: Throw up to 30 ft. Each creature within 10 ft must succeed on a "
                    f"DC {8 + int_mod} DEX save or be blinded until the start of their next turn."
                ),
            })
        
        if not any(a.get("name") == "Smoke Vial" for a in actions):
            actions.append({
                "name": "Smoke Vial",
                "resource": "Gadget Uses",
                "cost": 1,
                "action_type": "bonus",
                "description": (
                    "Bonus Action: Create a 10-foot-radius lightly obscured smoke cloud lasting 1 minute or until dispersed."
                ),
            })
        
        # ---- Level 2+ Features ----
        if lvl >= 2:
            if not any("Quick Repair" in f for f in features):
                features.append(
                    f"Quick Repair: During short rest, repair a construct within 5 ft, restoring {lvl + int_mod} HP."
                )
            
            # Explosive Gadgets
            if not any("Explosive Gadgets" in f for f in features):
                features.append(
                    "Explosive Gadgets: Can craft explosive devices during rest (Fireburst Charge, Shrapnel Bomb, Smoke Bomb)."
                )
            
            if not any(a.get("name") == "Fireburst Charge" for a in actions):
                actions.append({
                    "name": "Fireburst Charge",
                    "resource": "Crafting Reservoir",
                    "cost": 2,
                    "action_type": "action",
                    "damage": "2d6",
                    "damage_type": "fire",
                    "save_dc": 8 + int_mod,
                    "save_type": "DEX",
                    "range": 10,
                    "description": (
                        f"Action: Throw at target. Creatures in 10-ft radius must make DC {8 + int_mod} DEX save "
                        f"or take 2d6 fire damage (half on success)."
                    ),
                })
            
            if not any(a.get("name") == "Shrapnel Bomb" for a in actions):
                actions.append({
                    "name": "Shrapnel Bomb",
                    "resource": "Crafting Reservoir",
                    "cost": 2,
                    "action_type": "action",
                    "damage": "2d6",
                    "damage_type": "piercing",
                    "save_dc": 8 + int_mod,
                    "save_type": "DEX",
                    "range": 10,
                    "description": (
                        f"Action: Throw at target. Creatures in 10-ft radius must make DC {8 + int_mod} DEX save "
                        f"or take 2d6 piercing damage (half on success)."
                    ),
                })
        
        # ---- Level 3: Signature Invention ----
        if lvl >= 3:
            if not any("Signature Invention" in f for f in features):
                features.append(
                    "Signature Invention: Choose one - Personal Suit of Armor (AC = 10 + INT mod), "
                    "Mechanical Servant (HP = level, AC = 12 + INT mod, 1d6 attack), or "
                    "Cannon Weapon (1d6 damage, 120 ft range, uses INT for attack)."
                )
            
            # Check if invention is selected
            invention = char.get("signature_invention")
            if invention == "armor":
                char["ac"] = max(char.get("ac", 10), 10 + int_mod)
                if not any(a.get("name") == "Armor Reaction" for a in actions):
                    actions.append({
                        "name": "Armor Reaction",
                        "action_type": "reaction",
                        "description": "Reaction: Reduce damage from one attack by INT mod + level.",
                    })
            elif invention == "servant":
                # Mechanical Servant stats stored separately
                char.setdefault("mechanical_servant", {
                    "name": "Mechanical Servant",
                    "hp": lvl,
                    "max_hp": lvl,
                    "ac": 12 + int_mod,
                    "speed_ft": 30,
                    "attacks": [{
                        "name": "Mechanical Limbs",
                        "to_hit": int_mod + 2,
                        "damage": "1d6",
                        "damage_type": "bludgeoning",
                        "range": 5,
                    }],
                })
            elif invention == "cannon":
                # Add cannon as an attack option
                cannon_attack = {
                    "name": "Artificer Cannon",
                    "to_hit": int_mod + 2,
                    "damage": "1d6" if lvl < 10 else "1d10",
                    "damage_type": char.get("cannon_damage_type", "force"),
                    "range": 120,
                    "attack_type": "ranged",
                    "uses_int": True,
                }
                if not any(a.get("name") == "Artificer Cannon" for a in char.get("attacks", [])):
                    char.setdefault("attacks", []).append(cannon_attack)
        
        # Mark as non-caster (uses Crafting Points, not spell slots)
        char["caster_type"] = "artificer"  # Special marker for non-standard casting

    # ---- Fighter ----
    elif cls_name == "Fighter":
        lvl = int(char.get("level", 1))
        
        # Martial Dice pool - starts at 4d6, increases at 7 and 15
        martial_dice_count = 4
        if lvl >= 15:
            martial_dice_count = 6
        elif lvl >= 7:
            martial_dice_count = 5
        
        ensure_resource(char, "Martial Dice", martial_dice_count)
        
        # Martial die size scales
        if lvl >= 15:
            die_size = "d12"
        elif lvl >= 11:
            die_size = "d10"
        elif lvl >= 7:
            die_size = "d8"
        else:
            die_size = "d6"
        
        if not any("Combat Maneuvers" in f for f in features):
            features.append(f"Combat Maneuvers: {martial_dice_count} Martial Dice ({die_size}). Use for maneuvers like Focused Strike, Trip, Disarm, etc.")
        
        if not any("Fighting Style" in f for f in features):
            features.append("Fighting Style: Gain a Fighting Style feat of your choice.")
        
        # Action Surge at level 2+
        if lvl >= 2:
            ensure_resource(char, "Action Surge", 1)
            if not any("Action Surge" in f for f in features):
                features.append("Action Surge: Take one additional action on your turn. Recharges on rest.")
            if not any(a.get("name") == "Action Surge" for a in actions):
                actions.append({
                    "name": "Action Surge",
                    "resource": "Action Surge",
                    "action_type": "free",
                    "description": "Take one additional action on your turn.",
                })
    
    # ---- Cleric ----
    elif cls_name == "Cleric":
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        lvl = int(char.get("level", 1))
        
        if not any("Spellcasting" in f for f in features):
            features.append(f"Spellcasting: Wisdom-based divine caster. Spell Save DC = 8 + spell level + WIS mod.")
        
        if not any("Divine Domain" in f for f in features):
            features.append("Divine Domain: Choose a domain that grants bonus spells and features.")
        
        # Channel Divinity at level 2+
        if lvl >= 2:
            ensure_resource(char, "Channel Divinity", 1)
            if not any("Channel Divinity" in f for f in features):
                features.append("Channel Divinity: Invoke divine power. Use to Turn Undead or domain feature.")
            if not any(a.get("name") == "Turn Undead" for a in actions):
                actions.append({
                    "name": "Turn Undead",
                    "resource": "Channel Divinity",
                    "action_type": "action",
                    "save_dc": 8 + wis_mod,
                    "save_type": "WIS",
                    "description": f"Action: Undead within 30 ft must make DC {8 + wis_mod} WIS save or be turned for 1 minute.",
                })
    
    # ---- Druid ----
    elif cls_name == "Druid":
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        lvl = int(char.get("level", 1))
        
        if not any("Druidic" in f for f in features):
            features.append("Druidic: You know the secret language of druids.")
        
        if not any("Spellcasting" in f for f in features):
            features.append(f"Spellcasting: Wisdom-based nature caster. Prepared = WIS mod + Druid level.")
        
        if not any("Wild Shape" in f for f in features):
            features.append("Wild Shape: Transform into beasts you have seen. Uses scale with level.")
        
        # Wild Shape uses
        wild_shape_uses = 2 if lvl < 20 else 999  # Unlimited at 20
        ensure_resource(char, "Wild Shape", wild_shape_uses)
        
        if not any(a.get("name") == "Wild Shape" for a in actions):
            actions.append({
                "name": "Wild Shape",
                "resource": "Wild Shape",
                "action_type": "bonus" if lvl >= 4 else "action",
                "description": "Transform into a beast. Duration and CR limits based on level.",
            })
    
    # ---- Monk ----
    elif cls_name == "Monk":
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        dex_mod = _ability_mod(abilities.get("DEX", 10))
        lvl = int(char.get("level", 1))
        
        # Unarmored Defense
        if not any("Unarmored Defense" in f for f in features):
            features.append(f"Unarmored Defense: AC = 10 + DEX mod + WIS mod (currently {10 + dex_mod + wis_mod}) while unarmored.")
        
        # Martial Arts die scales
        if lvl >= 17:
            martial_die = "d12"
        elif lvl >= 11:
            martial_die = "d10"
        elif lvl >= 5:
            martial_die = "d8"
        else:
            martial_die = "d6"
        
        if not any("Martial Arts" in f for f in features):
            features.append(f"Martial Arts: Unarmed strikes deal {martial_die}. Bonus Action unarmed strike. Use DEX for unarmed/monk weapons.")
        
        if not any(a.get("name") == "Bonus Unarmed Strike" for a in actions):
            actions.append({
                "name": "Bonus Unarmed Strike",
                "action_type": "bonus",
                "damage": martial_die,
                "damage_type": "bludgeoning",
                "description": f"Bonus Action: Make an unarmed strike dealing {martial_die} + DEX mod damage.",
            })
        
        # Ki at level 2+
        if lvl >= 2:
            ki_points = lvl
            ensure_resource(char, "Ki", ki_points)
            ki_dc = 10 + wis_mod
            
            if not any("Ki Pool" in f for f in features):
                features.append(f"Ki Pool: {ki_points} Ki points. Ki save DC = {ki_dc}.")
            
            if not any(a.get("name") == "Flurry of Blows" for a in actions):
                actions.append({
                    "name": "Flurry of Blows",
                    "resource": "Ki",
                    "cost": 1,
                    "action_type": "bonus",
                    "description": "Bonus Action (1 Ki): Make two unarmed strikes.",
                })
            
            if not any(a.get("name") == "Step of the Wind" for a in actions):
                actions.append({
                    "name": "Step of the Wind",
                    "resource": "Ki",
                    "cost": 1,
                    "action_type": "bonus",
                    "description": "Bonus Action (1 Ki): Disengage or Dash as a bonus action.",
                })
            
            if not any(a.get("name") == "Patient Defense" for a in actions):
                actions.append({
                    "name": "Patient Defense",
                    "resource": "Ki",
                    "cost": 1,
                    "action_type": "bonus",
                    "description": "Bonus Action (1 Ki): Dodge as a bonus action.",
                })
    
    # ---- Paladin ----
    elif cls_name == "Paladin":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        lvl = int(char.get("level", 1))
        
        # Lay on Hands pool
        lay_on_hands_pool = 5 * lvl
        ensure_resource(char, "Lay on Hands", lay_on_hands_pool)
        
        if not any("Lay on Hands" in f for f in features):
            features.append(f"Lay on Hands: Healing pool of {lay_on_hands_pool} HP. Restore as an action by touch.")
        
        if not any(a.get("name") == "Lay on Hands" for a in actions):
            actions.append({
                "name": "Lay on Hands",
                "resource": "Lay on Hands",
                "action_type": "action",
                "description": f"Action: Touch a creature to restore HP from your pool (max {lay_on_hands_pool}).",
            })
        
        if not any("Aura of Good" in f for f in features):
            features.append("Aura of Good: You emit an aura of good out to 10 feet.")
        
        if not any("Spellcasting" in f for f in features):
            features.append("Spellcasting: Charisma-based half-caster. Prepare spells after rest.")
        
        # Divine Smite at level 2+
        if lvl >= 2:
            if not any("Divine Smite" in f for f in features):
                features.append("Divine Smite: Expend spell slot on hit for +2d8 radiant (+1d8 per slot level). Extra vs undead/fiends.")
            
            if not any(a.get("name") == "Divine Smite" for a in actions):
                actions.append({
                    "name": "Divine Smite",
                    "action_type": "free",
                    "resource": "Spell Slots",
                    "description": "On hit: Expend a spell slot for +2d8 radiant damage (+1d8 per slot level above 1st). Max 5d8.",
                })
    
    # ---- Ranger ----
    elif cls_name == "Ranger":
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        lvl = int(char.get("level", 1))
        
        if not any("Favored Enemy" in f for f in features):
            features.append("Favored Enemy: +2 damage against chosen enemy type.")
        
        if not any("Natural Explorer" in f for f in features):
            features.append("Natural Explorer: Benefits in chosen terrain (no slow, can't get lost, stealth at normal pace).")
        
        if not any("Spellcasting" in f for f in features):
            features.append("Spellcasting: Wisdom-based half-caster.")
        
        # Fighting Style at level 2+
        if lvl >= 2:
            if not any("Fighting Style" in f for f in features):
                features.append("Fighting Style: Gain a Fighting Style feat.")
            
            if not any("Wild Empathy" in f for f in features):
                features.append(f"Wild Empathy: Influence beasts within 30 ft. DC = 10 + WIS mod ({10 + wis_mod}).")
    
    # ---- Rogue ----
    elif cls_name == "Rogue":
        dex_mod = _ability_mod(abilities.get("DEX", 10))
        lvl = int(char.get("level", 1))
        
        # Sneak Attack dice scale
        sneak_dice = (lvl + 1) // 2  # 1d6 at 1, 2d6 at 3, etc.
        
        if not any("Sneak Attack" in f for f in features):
            features.append(f"Sneak Attack: +{sneak_dice}d6 damage once per turn when target is flanked, denied DEX, or distracted.")
        
        if not any("Thieves' Cant" in f for f in features):
            features.append("Thieves' Cant: You know the secret language of rogues.")
        
        # Stealthy at level 2+
        if lvl >= 2:
            if not any("Stealthy" in f for f in features):
                features.append(f"Stealthy: While hidden, enemies take -{dex_mod} penalty to Perception checks to detect you.")
        
        # Evasion at level 3+
        if lvl >= 3:
            if not any("Evasion" in f for f in features):
                features.append("Evasion: On successful DEX save for half damage, take no damage instead.")
    
    # ---- Sorcerer ----
    elif cls_name == "Sorcerer":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        lvl = int(char.get("level", 1))
        
        if not any("Spellcasting" in f for f in features):
            features.append("Spellcasting: Charisma-based innate caster. Spells known, not prepared.")
        
        if not any("Sorcerous Bloodline" in f for f in features):
            features.append("Sorcerous Bloodline: Choose Dragon, Fey, or Fiendish bloodline for bonus spells and features.")
        
        if not any("Minor Bloodline" in f for f in features):
            features.append("Minor Bloodline: Resistance based on bloodline (fire, charm/fear, etc.).")
        
        # Sorcery Points at level 2+
        if lvl >= 2:
            sorcery_points = lvl
            ensure_resource(char, "Sorcery Points", sorcery_points)
            
            if not any("Font of Arcane Power" in f for f in features):
                features.append(f"Font of Arcane Power: {sorcery_points} Sorcery Points. Convert slots to points or vice versa.")
            
            if not any(a.get("name") == "Convert Slot to Points" for a in actions):
                actions.append({
                    "name": "Convert Slot to Points",
                    "resource": "Spell Slots",
                    "action_type": "free",
                    "description": "Expend a spell slot to gain Sorcery Points equal to slot level.",
                })
        
        # Metamagic at level 3+
        if lvl >= 3:
            if not any("Metamagic" in f for f in features):
                features.append("Metamagic: Modify spells with options like Quickened, Twinned, Empowered.")
    
    # ---- Warlock ----
    elif cls_name == "Warlock":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        lvl = int(char.get("level", 1))
        
        if not any("Pact Magic" in f for f in features):
            features.append("Pact Magic: Charisma-based. Few slots but recharge on short rest. All slots same level.")
        
        if not any("Eldritch Pact" in f for f in features):
            features.append("Eldritch Pact: Choose a patron (Fiend, Great Old One, Archfey, etc.) for features.")
        
        # Pact slots scale differently - all same level
        if lvl >= 9:
            slot_level = 5
        elif lvl >= 7:
            slot_level = 4
        elif lvl >= 5:
            slot_level = 3
        elif lvl >= 3:
            slot_level = 2
        else:
            slot_level = 1
        
        pact_slots = 1 if lvl == 1 else 2
        if lvl >= 11:
            pact_slots = 3
        if lvl >= 17:
            pact_slots = 4
        
        ensure_resource(char, "Pact Slots", pact_slots)
        char["pact_slot_level"] = slot_level
    
    # ---- Wizard ----
    elif cls_name == "Wizard":
        int_mod = _ability_mod(abilities.get("INT", 10))
        lvl = int(char.get("level", 1))
        
        if not any("Spellcasting" in f for f in features):
            features.append(f"Spellcasting: Intelligence-based. Spellbook with 6 first-level spells. Prepare INT mod + level spells.")
        
        if not any("Familiar" in f for f in features):
            features.append(f"Familiar: Gain a familiar (HP = level + INT mod = {lvl + int_mod}). Telepathy within 100 ft.")
        
        if not any("Ritual Adept" in f for f in features):
            features.append("Ritual Adept: Cast ritual spells from spellbook without preparing them.")
        
        # School Specialization at level 3+
        if lvl >= 3:
            if not any("Magic School" in f for f in features):
                features.append("Magic School Specialization: Choose a school for bonus features.")
    
    # ---- Spellblade ----
    elif cls_name == "Spellblade":
        int_mod = _ability_mod(abilities.get("INT", 10))
        lvl = int(char.get("level", 1))
        
        if not any("Weapon Bond" in f for f in features):
            features.append("Weapon Bond: Summon bonded weapon as Bonus Action. Can't be disarmed. Use as spell focus.")
        
        if not any("Spellcasting" in f for f in features):
            features.append("Spellcasting: Intelligence-based. Prepare spells after rest.")
        
        if not any("Arcane Channeling" in f for f in features):
            features.append("Arcane Channeling: Deliver touch spells through weapon attacks.")
        
        if not any(a.get("name") == "Summon Bonded Weapon" for a in actions):
            actions.append({
                "name": "Summon Bonded Weapon",
                "action_type": "bonus",
                "description": "Bonus Action: Summon your bonded weapon to your hand.",
            })
        
        # Arcane Surge at level 3+
        if lvl >= 3:
            ensure_resource(char, "Arcane Surge", 1)
            if not any("Arcane Surge" in f for f in features):
                features.append("Arcane Surge: Once per day, empower yourself for 1 minute (+1d4 force on attacks, +1d6 on channeled spells).")
            
            if not any(a.get("name") == "Arcane Surge" for a in actions):
                actions.append({
                    "name": "Arcane Surge",
                    "resource": "Arcane Surge",
                    "action_type": "bonus",
                    "description": "Bonus Action: For 1 minute, +1d4 force damage on weapon attacks, +1d6 on channeled spells.",
                })
    
    # ---- Marshal ----
    elif cls_name == "Marshal":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        lvl = int(char.get("level", 1))
        
        # Martial Die scales
        if lvl >= 16:
            die_size = "d12"
        elif lvl >= 11:
            die_size = "d10"
        elif lvl >= 6:
            die_size = "d8"
        else:
            die_size = "d6"
        
        # Marshal gets fewer dice but they're more versatile
        martial_dice_count = 2 + (lvl // 4)
        ensure_resource(char, "Martial Dice", martial_dice_count)
        
        if not any("Martial Die" in f for f in features):
            features.append(f"Martial Die: {martial_dice_count} dice ({die_size}). Add to attacks, damage, checks, saves, or fuel maneuvers.")
        
        if not any("Fighting Style" in f for f in features):
            features.append("Fighting Style: Gain a Fighting Style feat.")
        
        if not any("Minor Auras" in f for f in features):
            features.append(f"Minor Auras: Project an aura granting +{max(0, cha_mod)} to allies within 30 ft. Switch as Bonus Action.")
        
        if not any(a.get("name") == "Switch Aura" for a in actions):
            actions.append({
                "name": "Switch Aura",
                "action_type": "bonus",
                "description": "Bonus Action: Switch your active Minor Aura to a different one.",
            })
        
        # Major Aura at level 2+
        if lvl >= 2:
            major_bonus = 1 + (lvl - 2) // 4  # +1 at 2, +2 at 6, +3 at 10, +4 at 14, +5 at 18
            if not any("Major Aura" in f for f in features):
                features.append(f"Major Aura: +{major_bonus} to attack, AC, DR, or saves for allies in 30 ft.")

def apply_feats(char: dict, feat_names: list[str]):
    feats = char.setdefault("feats", [])
    for f in feat_names:
        if f and f not in feats:
            feats.append(f)

# ---------------- Helpers: Session State ----------------
def init_state():
    ss = st.session_state
    ss.setdefault("boot_mode", None)  # "load" | "new" | "running"
    ss.setdefault("session_id", datetime.now().strftime("%Y%m%d_%H%M%S"))
    ss.setdefault("chat_log", [])      # list[tuple(speaker, text)]
    ss.setdefault("world_log", "You stand at the threshold of adventure.")
    ss.setdefault("party", [])         # list of character dicts
    ss.setdefault("enemies", [])       # list of enemy dicts
    ss.setdefault("difficulty", "Normal")
    ss.setdefault("npc_attitude", 50)  # tiny memory for talk replies
    ss.setdefault("last_topic", None)

def serialize_state() -> Dict[str, Any]:
    # Serialize grid data
    grid_data = None
    if "grid" in st.session_state and st.session_state.grid:
        grid = st.session_state.grid
        grid_data = {
            "width": grid.get("width", 20),
            "height": grid.get("height", 20),
            "square_size_ft": grid.get("square_size_ft", 5),
            "biome": grid.get("biome"),
            "seed": grid.get("seed"),
            "cells": grid.get("cells", []),
        }
    
    return {
        "session_id": st.session_state.session_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "chat_log": st.session_state.chat_log,
        "world_log": st.session_state.world_log,
        "party": st.session_state.party,
        "enemies": st.session_state.enemies,
        "difficulty": st.session_state.difficulty,
        "grid": grid_data,
        "dm_notes": st.session_state.get("dm_notes", ""),
    }

def _migrate_grid_cells(cells: list) -> list:
    """Migrate old grid cell formats to new format."""
    if not cells:
        return cells
    
    tiles = load_tiles()
    
    migrated = []
    for row in cells:
        new_row = []
        for cell in row:
            if isinstance(cell, dict):
                # Already new format
                if "tile" in cell:
                    new_row.append(cell)
                else:
                    # Unknown dict format
                    new_row.append({"tile": "open", "hazard": None})
            elif isinstance(cell, int):
                # Old int format: 0=open, 1=wall, 2=difficult
                tile_map = {0: "open", 1: "wall", 2: "difficult"}
                new_row.append({"tile": tile_map.get(cell, "open"), "hazard": None})
            elif isinstance(cell, str):
                # String tile name - validate against loaded tiles
                new_row.append({"tile": cell if cell in tiles else "open", "hazard": None})
            else:
                new_row.append({"tile": "open", "hazard": None})
        migrated.append(new_row)
    return migrated

def load_state_blob(blob: Dict[str, Any]):
    st.session_state.session_id = blob.get("session_id", datetime.now().strftime("%Y%m%d_%H%M%S"))
    st.session_state.chat_log = blob.get("chat_log", [])
    st.session_state.world_log = blob.get("world_log", "")
    st.session_state.party = blob.get("party", [])
    st.session_state.enemies = blob.get("enemies", [])
    st.session_state.difficulty = blob.get("difficulty", "Normal")
    st.session_state.dm_notes = blob.get("dm_notes", "")
    
    # Load grid data
    grid_data = blob.get("grid")
    if grid_data:
        cells = grid_data.get("cells", [])
        # Migrate old cell formats if needed
        cells = _migrate_grid_cells(cells)
        
        st.session_state.grid = {
            "width": grid_data.get("width", 20),
            "height": grid_data.get("height", 20),
            "square_size_ft": grid_data.get("square_size_ft", 5),
            "biome": grid_data.get("biome"),
            "seed": grid_data.get("seed"),
            "cells": cells,
        }
    else:
        # No grid in save - will be initialized on first access
        st.session_state.grid = None

# ---------------- Dice + Dialogue Utilities ----------------
def roll_dice(expr: str) -> Tuple[int, str]:

    expr = expr.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(?:(\d*)d(\d+))?([+-]\d+)?", expr)
    if not m:
        if (expr.isdigit()) or (expr.startswith("-") and expr[1:].isdigit()):
            val = int(expr); return val, f"{val} (flat)"
        return 0, f"Unrecognized dice: {expr}"

    num = int(m.group(1)) if m.group(1) not in (None, "") else (1 if m.group(2) else 0)
    sides = int(m.group(2)) if m.group(2) else 0
    mod = int(m.group(3)) if m.group(3) else 0

    rolls = [random.randint(1, sides) for _ in range(num)] if sides else []
    total = sum(rolls) + mod
    parts = "+".join(map(str, rolls)) if rolls else ""
    if mod != 0:
        parts = (parts + (f"{'+' if mod>0 else ''}{mod}")).lstrip("+")
    if parts == "":
        parts = str(total)
    return total, f"{parts} = {total}"

def extract_inline_rolls(text: str) -> List[str]:
    pattern = r"(?:(?<=/roll\s)|(?<=\broll\s))(\d*d\d+(?:[+-]\d+)?|\d{1,3}\b)"
    return [m.group(1) for m in re.finditer(pattern, text.lower())]

def detect_intent(text: str) -> Tuple[str, Dict]:
    t = text.strip().lower()
    if t.startswith("/roll") or t.startswith("roll "):
        dice = extract_inline_rolls(t)
        return "roll", {"dice": dice or ["d20"]}

    if any(k in t for k in ["attack", "strike", "shoot", "swing", "stab", "fire at"]):
        m = re.search(r"attack\s+the\s+([\w'-]+)|attack\s+([\w'-]+)", t)
        target = m.group(1) if m and m.group(1) else (m.group(2) if m else None)
        return "attack", {"target": target}

    if any(k in t for k in ["talk", "speak", "ask", "say", "negotiate", "persuade", "intimidate"]):
        m = re.search(r"(about|regarding)\s+(.+)$", t)
        topic = m.group(2) if m else None
        return "talk", {"topic": topic}

    if any(k in t for k in ["search", "investigate", "inspect", "look around", "examine", "perception"]):
        return "search", {}

    if any(k in t for k in ["cast", "spell", "ritual"]):
        m = re.search(r"cast\s+([a-z][a-z\s']+)", t)
        spell = m.group(1).strip() if m else None
        return "cast", {"spell": spell}

    if any(k in t for k in ["move", "go to", "run to", "advance to", "fall back", "retreat"]):
        m = re.search(r"(to|toward)\s+(.+)$", t)
        where = m.group(2).strip() if m else None
        return "move", {"where": where}

    return "other", {}

def reply_for(text: str) -> str:
    intent, ent = detect_intent(text)
    ss = st.session_state

    if intent == "roll":
        lines = []
        for d in ent.get("dice", ["d20"]):
            total, breakdown = roll_dice(d)
            lines.append(f"• {d}: {breakdown}")
        return "Rolls:\n" + "\n".join(lines)

    if intent == "attack":
        tgt = ent.get("target") or "the target"
        ac_note = ""
        for e in ss.enemies:
            if e.get("name", "").lower() == (ent.get("target") or "").lower():
                ac_note = f" (Target AC: {e.get('ac', '—')})"
                break
        return f"Make an attack roll against {tgt}{ac_note}. On a hit, roll weapon damage."

    if intent == "talk":
        topic = ent.get("topic")
        if topic:
            ss["last_topic"] = topic
            ss["npc_attitude"] = min(100, ss["npc_attitude"] + 2)
            return f"You discuss **{topic}**. The other side seems slightly more receptive (Attitude {ss['npc_attitude']}/100). What do you say next?"
        return "State your opening line or topic."

    if intent == "search":
        dc = random.choice([10, 12, 13, 15])
        return f"Make a Search/Perception check vs DC {dc}. State your modifier."

    if intent == "cast":
        spell = ent.get("spell") or "a spell"
        return f"You begin casting **{spell}**. Provide target and intended effect."

    if intent == "move":
        where = ent.get("where") or "a new position"
        return f"You move to **{where}**. Note marching order and pace."

    return "Action noted. Use: attack, talk, search, cast, move, or /roll XdY+Z."

# ---------------- Data Shapes ----------------
# Minimal D&D 5e sheet shape
EMPTY_CHAR = {
    "name": "",
    "ac": 10,
    "hp": 10,
    "speed": "30 ft.",
    "abilities": {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
    "skills": {},
    "senses": "",
    "languages": "",
    "attacks": [],  # list of {name, to_hit:int, damage:str, reach/range:opt}
    "resources": {}, 
    "actions": [],    
}

def coerce_5e_sheet(blob: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accepts various 5e-like sheet JSON and maps to the minimal shape used here.
    Unknown fields ignored; missing fields set to defaults.
    """
    out = json.loads(json.dumps(EMPTY_CHAR))
    out["name"] = blob.get("name", out["name"])
    out["ac"] = blob.get("ac", blob.get("armor_class", out["ac"]))
    out["hp"] = blob.get("hp", blob.get("hit_points", out["hp"]))
    out["speed"] = blob.get("speed", out["speed"])

    abilities = blob.get("abilities") or blob.get("ability_scores") or {}
    for k in out["abilities"].keys():
        out["abilities"][k] = int(abilities.get(k, out["abilities"][k]))

    out["skills"] = blob.get("skills", out["skills"])
    out["senses"] = blob.get("senses", out["senses"])
    out["languages"] = blob.get("languages", out["languages"])

    attacks = []
    for atk in blob.get("attacks", []):
        attacks.append({
            "name": atk.get("name", "Attack"),
            "to_hit": int(atk.get("to_hit", 0)),
            "damage": atk.get("damage", "1d6"),
            "reach": atk.get("reach", None),
            "range": atk.get("range", None),
        })
    out["attacks"] = attacks
    return out

# ---------------- Init ----------------
init_state()
load_srd_monsters()  # reminder: SRD list is available even before choosing Load/New.
load_srd_conditions()

st.markdown("### Virtual DM — Session Manager")

# ==== Character Builder state ==== (Confirmed working)
def init_builder_state():
    ss = st.session_state
    ss.setdefault("builder_char", {
        "name": "", "level": 1, "class": "", "subclass": "", "race": "", "background": "",
        "ac": 10, "hp": 10, "speed": "30 ft.",
        "abilities": {"STR":10,"DEX":10,"CON":10,"INT":10,"WIS":10,"CHA":10},
        "proficiency_bonus": 2,
        "profs": {"saves": [], "skills": [], "weapons": [], "armor": []},
        "features": [],           # textual features
        "feats": [],
        "spells": {        # structured spell data
            "cantrips": [],      # list of names
            "leveled": {},       # {spell_level: [names]}
        },
        "equipment": [],
        "attacks": [],
        "default_attack_index": 0,
        "resources": {},          # e.g. Rage, Bardic Performance, Crafting Reservoir
        "actions": [],            # structured class actions the UI can show
    })

    ss.setdefault("builder_name", "")
    # 1..7 = Race, Abilities, Background, Class, Skills, Feats, Equipment
    ss.setdefault("builder_step", 1)
    # per-builder temporary store for skill ranks
    ss.setdefault("builder_skill_ranks", {})

init_builder_state()

# ---------------- Boot Flow ----------------
if st.session_state.boot_mode is None:
    st.markdown("# 🎲 Welcome to Virtual DM")
    st.markdown("Your virtual tabletop companion for solo play, DM assistance, and session management.")
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🆕 Start New Session")
        st.markdown("""
        Create a new adventure from scratch:
        - Build or import party members
        - Add enemies from the SRD bestiary
        - Configure your encounter
        """)
        if st.button("Start New Session", use_container_width=True, type="primary"):
            st.session_state.boot_mode = "new"
            st.rerun()
    
    with col2:
        st.markdown("### 📂 Load Previous Session")
        st.markdown("""
        Continue where you left off:
        - Upload a saved session JSON
        - Resume combat and exploration
        - Keep your party progress
        """)
        if st.button("Load Previous Session", use_container_width=True):
            st.session_state.boot_mode = "load"
            st.rerun()
    
    st.markdown("---")
    st.caption("Use the sidebar navigation to switch between pages at any time.")
    st.stop()

# ---------------- Load Session ----------------
if st.session_state.boot_mode == "load":
    st.markdown("# 📂 Load Session")
    st.markdown("Upload a previously saved Virtual DM session file to continue your adventure.")
    
    st.markdown("---")
    
    up = st.file_uploader("Upload a saved session (.json)", type=["json"])
    
    if up is None:
        st.info("👆 Select a `.json` session file to upload")
        st.caption("Session files are created using the 'Download Session' button during play.")
    else:
        try:
            blob = json.load(up)
            load_state_blob(blob)
            st.success("✅ Session loaded successfully!")
            st.balloons()
            st.session_state.boot_mode = "running"
            st.rerun()
        except Exception as e:
            st.error(f"❌ Could not load file: {e}")
            st.caption("Make sure you're uploading a valid Virtual DM session JSON file.")
    
    st.stop()

# ---------------- New Session: Character Entry ----------------
if st.session_state.boot_mode == "new":
    st.markdown("# ⚙️ Session Setup")
    st.markdown("Configure your party and enemies before beginning the session.")
    
    st.markdown("---")

    # Tabs for entry methods
    t_upload, t_paste, t_form, t_build = st.tabs(["Upload JSON", "Paste JSON", "Manual Entry", "Build Character"])

    with t_upload:
        up_chars = st.file_uploader("Upload one or more 5e character sheets", type=["json"], accept_multiple_files=True)
        if up_chars:
            added = 0
            for f in up_chars:
                try:
                    blob = json.load(f)
                    char = coerce_5e_sheet(blob)
                    if char.get("name"):
                        st.session_state.party.append(char)
                        added += 1
                except Exception as e:
                    st.warning(f"Failed to read {f.name}: {e}")
            if added:
                st.success(f"Added {added} character(s) to the party.")

    with t_paste:
        raw = st.text_area("Paste 5e JSON here (single character)", height=220)
        if st.button("Add Character From JSON"):
            try:
                blob = json.loads(raw)
                char = coerce_5e_sheet(blob)
                if char.get("name"):
                    st.session_state.party.append(char)
                    st.success(f"Added: {char['name']}")
                else:
                    st.warning("Name missing in JSON.")
            except Exception as e:
                st.error(f"Invalid JSON: {e}")

    with t_form:
        with st.form("char_form"):
            name = st.text_input("Name")
            colA, colB, colC, colD = st.columns(4)
            with colA:
                ac = st.number_input("AC", 0, 40, 10)
            with colB:
                hp = st.number_input("HP", 0, 500, 10)
            with colC:
                spd = st.text_input("Speed", value="30 ft.")
            with colD:
                lng = st.text_input("Languages", value="Common")

            st.markdown("**Abilities**")
            a1, a2, a3, a4, a5, a6 = st.columns(6)
            STR = a1.number_input("STR", 1, 30, 10)
            DEX = a2.number_input("DEX", 1, 30, 10)
            CON = a3.number_input("CON", 1, 30, 10)
            INT = a4.number_input("INT", 1, 30, 10)
            WIS = a5.number_input("WIS", 1, 30, 10)
            CHA = a6.number_input("CHA", 1, 30, 10)

            st.markdown("**Primary Attack**")
            atk_name = st.text_input("Attack Name", value="Weapon")
            atk_to_hit = st.number_input("To-Hit Bonus", -10, 20, 0)
            atk_damage = st.text_input("Damage Dice", value="1d6+0")

            submitted = st.form_submit_button("Add Character")
            if submitted:
                c = json.loads(json.dumps(EMPTY_CHAR))
                c["name"] = name
                c["ac"] = int(ac)
                c["hp"] = int(hp)
                c["speed"] = spd
                c["languages"] = lng
                c["abilities"] = {"STR": STR, "DEX": DEX, "CON": CON, "INT": INT, "WIS": WIS, "CHA": CHA}
                c["attacks"] = [{"name": atk_name, "to_hit": int(atk_to_hit), "damage": atk_damage}]
                if c["name"]:
                    st.session_state.party.append(c)
                    st.success(f"Added: {c['name']}")
                else:
                    st.warning("Name is required.")

    with t_build:
        st.markdown("### Build Character (Step-by-Step)")
        # reminder: these loaders already exist above; they accept .json or .txt

        races = load_srd_races()
        bgs = load_srd_backgrounds()
        classes = load_srd_classes()
        feats_db = load_srd_feats()
        equip_db = load_srd_equipment()

        c = st.session_state.builder_char
        step = st.session_state.builder_step
        total_steps = 7
        st.progress(step / float(total_steps), text=f"Step {step} of {total_steps}")

        # Sticky name across steps
        st.text_input("Character Name", key="builder_name")
        if st.session_state.builder_name:
            c["name"] = st.session_state.builder_name

        # convenience
        def _get_picked_race():
            r_pick = st.session_state.get("builder_race_pick", "")
            if not r_pick:
                return None, ""
            rb = next((r for r in races if r.get("name") == r_pick), None)
            return rb, r_pick

        # ------------------------------------------------------
        # STEP 1: Race
        # ------------------------------------------------------
        if step == 1:
            st.subheader("Step 1: Choose Race")
            race_names = [r.get("name", "") for r in races]
            r_pick = st.selectbox("Race", race_names, key="builder_race_pick")

            if r_pick:
                with st.expander("Race Details", expanded=False):
                    st.write(next((r for r in races if r.get("name") == r_pick), {}))

            col = st.columns([1, 1])
            if col[0].button("Next: Ability Scores", type="primary"):
                if r_pick:
                    st.session_state.builder_step = 2
                    st.toast(f"Race selected: {r_pick}")
                    st.rerun()
                else:
                    st.warning("Please choose a race before continuing.")

            st.caption("SRD races source: " + str(st.session_state.get("srd_races_path", "(not found)")))

        # ------------------------------------------------------
        # STEP 2: Ability Scores (4d6, plus racial totals preview)
        # ------------------------------------------------------
        if step == 2:
            st.subheader("Step 2: Ability Scores")

            race_blob, r_pick = _get_picked_race()

            with st.expander("Ability Scores (4d6 drop lowest)", expanded=True):
                abilities = c.setdefault(
                    "abilities",
                    {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                )

                if st.button("Roll 4d6 (drop lowest)", key="builder_roll_4d6"):
                    scores = roll_ability_scores_4d6_drop_lowest()
                    for key, val in zip(["STR", "DEX", "CON", "INT", "WIS", "CHA"], scores):
                        abilities[key] = val
                    st.toast(f"Rolled scores: {scores}")

                # BASE editable scores
                col1, col2, col3 = st.columns(3)
                abilities["STR"] = int(col1.number_input("STR (Base)", 3, 20, int(abilities.get("STR", 10)), key="builder_STR_base"))
                abilities["DEX"] = int(col2.number_input("DEX (Base)", 3, 20, int(abilities.get("DEX", 10)), key="builder_DEX_base"))
                abilities["CON"] = int(col3.number_input("CON (Base)", 3, 20, int(abilities.get("CON", 10)), key="builder_CON_base"))

                col4, col5, col6 = st.columns(3)
                abilities["INT"] = int(col4.number_input("INT (Base)", 3, 20, int(abilities.get("INT", 10)), key="builder_INT_base"))
                abilities["WIS"] = int(col5.number_input("WIS (Base)", 3, 20, int(abilities.get("WIS", 10)), key="builder_WIS_base"))
                abilities["CHA"] = int(col6.number_input("CHA (Base)", 3, 20, int(abilities.get("CHA", 10)), key="builder_CHA_base"))

                # --- compute racial bonuses without mutating the character ---
                race_bonus = {k: 0 for k in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]}
            
            if race_blob:
                ab = race_blob.get("ability_bonuses") or {}
                # 5e SRD style: list of {"ability_score": {"index": "con", "name": "CON"}, "bonus": 2}
                if isinstance(ab, list):
                    for entry in ab:
                        if not isinstance(entry, dict):
                            continue
                        key = None
                        if "name" in entry:
                            key = str(entry["name"]).upper()
                        if not key and isinstance(entry.get("ability_score"), dict):
                            as_obj = entry["ability_score"]
                            key = (as_obj.get("name") or as_obj.get("index") or "").upper()
                        bonus = int(entry.get("bonus", 0))
                        if key in race_bonus:
                            race_bonus[key] += bonus
                # simple dict style: {"STR": 2, "CON": 2}
                elif isinstance(ab, dict):
                    for k, v in ab.items():
                        key = str(k).upper()
                        if key in race_bonus:
                            race_bonus[key] += int(v)

            # build totals for all six abilities first
            totals = {}
            for abbr in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]:
                base = int(abilities.get(abbr, 10))
                totals[abbr] = base + int(race_bonus.get(abbr, 0))

            # now it's safe to reference all of them in the UI
            st.markdown("**Final Ability Totals (with Race)**")
            t1, t2, t3 = st.columns(3)
            t1.number_input("STR (Total)", 1, 30, totals["STR"], key="builder_STR_total", disabled=True)
            t2.number_input("DEX (Total)", 1, 30, totals["DEX"], key="builder_DEX_total", disabled=True)
            t3.number_input("CON (Total)", 1, 30, totals["CON"], key="builder_CON_total", disabled=True)

            t4, t5, t6 = st.columns(3)
            t4.number_input("INT (Total)", 1, 30, totals["INT"], key="builder_INT_total", disabled=True)
            t5.number_input("WIS (Total)", 1, 30, totals["WIS"], key="builder_WIS_total", disabled=True)
            t6.number_input("CHA (Total)", 1, 30, totals["CHA"], key="builder_CHA_total", disabled=True)

            # Navigation buttons
            col = st.columns([1, 1])
            if col[0].button("Back", key="abilities_back"):
                st.session_state.builder_step = 1
                st.rerun()

            if col[1].button("Apply Race & Continue to Background", type="primary"):
                if not r_pick or not race_blob:
                    st.warning("Please choose a race in Step 1 first.")
                else:
                    # apply_race mutates c["abilities"] to include these racial bonuses
                    apply_race(c, race_blob)
                    st.session_state.builder_step = 3
                    st.toast("Ability scores applied and race bonuses added.")
                    st.rerun()

        # ------------------------------------------------------
        # STEP 3: Background
        # ------------------------------------------------------
        if step == 3:
            st.subheader("Step 3: Choose Background")
            bg_names = [b.get("name", "") for b in bgs]
            b_pick = st.selectbox("Background", bg_names, key="builder_bg_pick")

            if b_pick:
                with st.expander("Background Details", expanded=False):
                    st.write(next((b for b in bgs if b.get("name") == b_pick), {}))

            col = st.columns([1, 1])
            if col[0].button("Back", key="bg_back"):
                st.session_state.builder_step = 2
                st.rerun()

            if col[1].button("Apply Background", type="primary"):
                if b_pick:
                    apply_background(c, next(b for b in bgs if b.get("name") == b_pick))
                    st.session_state.builder_step = 4
                    st.toast(f"Background applied: {b_pick}")
                    st.rerun()

        # ------------------------------------------------------
        # STEP 4: Class
        # ------------------------------------------------------
        if step == 4:
            st.subheader("Step 4: Choose Class (Level 1)")
            cls_names = [x.get("name", "") for x in classes]
            c_pick = st.selectbox("Class", cls_names, key="builder_class_pick")
            kit_idx = 0

            if c_pick:
                c_blob = next((x for x in classes if x.get("name") == c_pick), None)
                kits = (c_blob or {}).get("starting_equipment_kits") or []
                if kits:
                    kit_labels = [k.get("name", f"Kit {i+1}") for i, k in enumerate(kits)]
                    kit_idx = st.selectbox(
                        "Starting Equipment",
                        list(range(len(kits))),
                        format_func=lambda i: kit_labels[i],
                        key="builder_class_kit_idx",
                    )
                
                # --------- Spellcasting Section ---------
                # Check if class has spellcasting at level 1
                spell_ability = (c_blob or {}).get("spellcasting_ability", "")
                levels_data = (c_blob or {}).get("levels", {})
                level_1_data = levels_data.get("1", {})
                cantrips_known = level_1_data.get("cantrips_known", 0)
                spells_known = level_1_data.get("spells_known", 0)
                
                has_spellcasting = bool(spell_ability) and (cantrips_known > 0 or spells_known > 0)
                
                if has_spellcasting:
                    st.markdown("---")
                    st.markdown(f"### 🔮 Spellcasting (Ability: **{spell_ability}**)")
                    
                    # Load spells for this class
                    available_cantrips, available_level1 = get_spells_for_class(c_pick, max_level=1)
                    
                    # Initialize spell selection state
                    if "builder_cantrips" not in st.session_state:
                        st.session_state.builder_cantrips = []
                    if "builder_spells_l1" not in st.session_state:
                        st.session_state.builder_spells_l1 = []
                    
                    # Cantrip selection
                    if cantrips_known > 0 and available_cantrips:
                        st.markdown(f"**Cantrips Known:** {cantrips_known}")
                        cantrip_names = [s["name"] for s in available_cantrips]
                        selected_cantrips = st.multiselect(
                            "Select Cantrips",
                            cantrip_names,
                            default=st.session_state.builder_cantrips[:cantrips_known],
                            max_selections=cantrips_known,
                            key="builder_cantrips_select",
                        )
                        st.session_state.builder_cantrips = selected_cantrips
                        
                        # Show cantrip details
                        if selected_cantrips:
                            with st.expander("Cantrip Details", expanded=False):
                                for name in selected_cantrips:
                                    spell = next((s for s in available_cantrips if s["name"] == name), None)
                                    if spell:
                                        dmg_info = f" | **Damage:** {spell['damage']} {spell.get('damage_type', '')}" if spell.get('damage') else ""
                                        save_info = f" | **Save:** {spell['save']}" if spell.get('save') else ""
                                        atk_info = " | **Spell Attack**" if spell.get('type') == 'spell_attack' else ""
                                        st.markdown(f"**{name}** ({spell['school']}){dmg_info}{save_info}{atk_info}")
                                        st.caption(spell.get('description', '')[:200] + "..." if len(spell.get('description', '')) > 200 else spell.get('description', ''))
                    
                    # Level 1 spell selection
                    if spells_known > 0 and available_level1:
                        st.markdown(f"**Level 1 Spells Known:** {spells_known}")
                        spell_l1_names = [s["name"] for s in available_level1]
                        selected_spells = st.multiselect(
                            "Select Level 1 Spells",
                            spell_l1_names,
                            default=st.session_state.builder_spells_l1[:spells_known],
                            max_selections=spells_known,
                            key="builder_spells_l1_select",
                        )
                        st.session_state.builder_spells_l1 = selected_spells
                        
                        # Show spell details
                        if selected_spells:
                            with st.expander("Spell Details", expanded=False):
                                for name in selected_spells:
                                    spell = next((s for s in available_level1 if s["name"] == name), None)
                                    if spell:
                                        dmg_info = f" | **Damage:** {spell['damage']} {spell.get('damage_type', '')}" if spell.get('damage') else ""
                                        save_info = f" | **Save:** {spell['save']}" if spell.get('save') else ""
                                        atk_info = " | **Spell Attack**" if spell.get('type') == 'spell_attack' else ""
                                        conc_info = " | ⚡ Concentration" if spell.get('concentration') else ""
                                        st.markdown(f"**{name}** ({spell['school']}){dmg_info}{save_info}{atk_info}{conc_info}")
                                        st.caption(spell.get('description', '')[:200] + "..." if len(spell.get('description', '')) > 200 else spell.get('description', ''))
                    
                    # Spell slots info
                    spell_slots = level_1_data.get("spell_slots_by_level", {})
                    if spell_slots:
                        slots_str = ", ".join(f"Level {k}: {v} slots" for k, v in spell_slots.items())
                        st.info(f"**Spell Slots at Level 1:** {slots_str}")
                
                with st.expander("Class Details", expanded=False):
                    st.write(c_blob or {})
                
                # ---- Artificer-specific options ----
                if c_pick == "Artificer":
                    st.markdown("---")
                    st.markdown("### ⚙️ Artificer Options")
                    st.info("Artificers use **Crafting Points** instead of spell slots. Your inventions are technology, not magic!")
                    
                    # Note about Signature Invention (level 3 feature)
                    st.caption("At level 3, you'll choose your **Signature Invention**: Personal Armor, Mechanical Servant, or Cannon Weapon.")
                    
                    # For now, let them pre-select if they want (stored for later)
                    with st.expander("Preview Signature Invention (Level 3)", expanded=False):
                        invention_choice = st.radio(
                            "Choose your invention path:",
                            ["armor", "servant", "cannon"],
                            format_func=lambda x: {
                                "armor": "⚔️ Personal Suit of Armor - AC = 10 + INT mod, damage reduction",
                                "servant": "🤖 Mechanical Servant - Autonomous companion, HP = level",
                                "cannon": "💥 Cannon Weapon - 1d6 damage, 120 ft range, uses INT"
                            }.get(x, x),
                            key="builder_artificer_invention",
                            horizontal=False,
                        )
                        st.session_state.builder_artificer_invention = invention_choice
                        
                        if invention_choice == "cannon":
                            cannon_type = st.selectbox(
                                "Cannon damage type:",
                                ["force", "piercing", "thunder", "fire", "cold", "lightning"],
                                key="builder_cannon_type"
                            )
                            st.session_state.builder_cannon_type = cannon_type

            col = st.columns([1, 1])
            if col[0].button("Back  ", key="class_back"):
                st.session_state.builder_step = 3
                st.rerun()

            if col[1].button("Apply Class", type="primary"):
                if c_pick:
                    cls_blob = next(x for x in classes if x.get("name") == c_pick)
                    apply_class_level1(
                        c,
                        cls_blob,
                        kit_idx=int(st.session_state.get("builder_class_kit_idx", 0)),
                    )
                    
                    # Store Artificer-specific choices before initializing resources
                    if c_pick == "Artificer":
                        c["signature_invention"] = st.session_state.get("builder_artificer_invention", "cannon")
                        c["cannon_damage_type"] = st.session_state.get("builder_cannon_type", "force")
                    
                    # NEW: initialize level 1 class resources/actions for Barbarian, Bard, Artificer
                    add_level1_class_resources_and_actions(c)
                    
                    # --------- Apply Spellcasting ---------
                    spell_ability = cls_blob.get("spellcasting_ability", "")
                    if spell_ability:
                        c["spellcasting_ability"] = spell_ability
                        
                        # Get selected spells
                        selected_cantrips = st.session_state.get("builder_cantrips", [])
                        selected_spells_l1 = st.session_state.get("builder_spells_l1", [])
                        
                        # Load spell data
                        all_spells = load_srd_spells()
                        actions = c.setdefault("actions", [])
                        spells_list = c.setdefault("spells", [])
                        
                        # Add cantrips as actions (at-will)
                        for spell_name in selected_cantrips:
                            spell_data = next((s for s in all_spells if s["name"] == spell_name), None)
                            if spell_data:
                                spells_list.append(spell_name)
                                action = spell_to_action(spell_data, c)
                                action["at_will"] = True  # Cantrips are at-will
                                actions.append(action)
                        
                        # Add level 1 spells as actions (use spell slots)
                        for spell_name in selected_spells_l1:
                            spell_data = next((s for s in all_spells if s["name"] == spell_name), None)
                            if spell_data:
                                spells_list.append(spell_name)
                                action = spell_to_action(spell_data, c)
                                action["at_will"] = False  # Level 1+ spells use slots
                                actions.append(action)
                        
                        # Store spell slots
                        levels_data = cls_blob.get("levels", {})
                        level_1_data = levels_data.get("1", {})
                        spell_slots = level_1_data.get("spell_slots_by_level", {})
                        if spell_slots:
                            resources = c.setdefault("resources", {})
                            for lvl, slots in spell_slots.items():
                                resources[f"Spell Slot (Level {lvl})"] = {"current": slots, "max": slots}
                        
                        # Clear spell selection state for next character
                        st.session_state.builder_cantrips = []
                        st.session_state.builder_spells_l1 = []

                    st.session_state.builder_step = 5
                    st.rerun()
                else:
                    st.warning("Please choose a class before applying it.")

        # ------------------------------------------------------
        # STEP 5: Skills (uses class skill points + INT mod)
        # ------------------------------------------------------
        if step == 5:
            st.subheader("Step 5: Assign Skills")

            c_pick = st.session_state.get("builder_class_pick", "")
            cls_blob = next((x for x in classes if x.get("name") == c_pick), None) if c_pick else None

            if not cls_blob:
                st.warning("Please choose and apply a class in Step 4 first.")
            else:
                # --------- figure out the class's skill list ----------
                # Try several possible keys so we work with different JSON formats
                skill_list = []
                for key in ["skill_list", "skills", "class_skills", "trained_skills"]:
                    val = cls_blob.get(key)
                    if isinstance(val, list) and val:
                        skill_list = [str(s) for s in val]
                        break

                if not skill_list:
                    st.warning("This class has no skill list defined. "
                            "Check your SRD_Classes.json for a 'skill_list' or similar field.")
                else:
                    # --------- figure out how many skill points we have ----------
                    raw_sp = str(cls_blob.get("skill_points_per_level", "") or cls_blob.get("skill_points", "0"))
                    import re as _re
                    m = _re.search(r"(\d+)", raw_sp)
                    base_points = int(m.group(1)) if m else 0

                    # If the class JSON doesn't have skill points, use a fallback (e.g. 2 + INT)
                    if base_points == 0:
                        base_points = 2  # tweak this default

                    int_score = int(c.get("abilities", {}).get("INT", 10))
                    int_mod = _ability_mod(int_score)
                    total_points = max(1, base_points + int_mod)

                    st.markdown(
                        f"Class skill points: **{base_points} + INT mod ({int_mod:+d}) = {total_points}**"
                    )

                    # --------- rank inputs ----------
                    ranks_state = st.session_state.builder_skill_ranks
                    for sk in skill_list:
                        ranks_state.setdefault(sk, 0)

                    cols = st.columns(3)
                    spent = 0
                    for i, sk in enumerate(skill_list):
                        col = cols[i % 3]
                        current = int(ranks_state.get(sk, 0))
                        new_val = col.number_input(
                            sk,
                            min_value=0,
                            max_value=10,
                            value=current,
                            key=f"skill_rank_{sk}",
                        )
                        ranks_state[sk] = new_val
                        spent += new_val

                    st.markdown(f"**Skill points spent:** {spent} / {total_points}")
                    if spent > total_points:
                        st.error("You have spent more skill points than available.")

            col = st.columns([1, 1])
            if col[0].button("Back   ", key="skills_back"):
                st.session_state.builder_step = 4
                st.rerun()

            if col[1].button("Apply Skills", type="primary"):
                if not cls_blob:
                    st.warning("You must choose a class in Step 4 first.")
                else:
                    # recompute totals for validation
                    raw_sp = str(cls_blob.get("skill_points_per_level", "") or cls_blob.get("skill_points", "0"))
                    import re as _re
                    m = _re.search(r"(\d+)", raw_sp)
                    base_points = int(m.group(1)) if m else 0
                    if base_points == 0:
                        base_points = 2

                    int_score = int(c.get("abilities", {}).get("INT", 10))
                    int_mod = _ability_mod(int_score)
                    total_points = max(1, base_points + int_mod)

                    # same logic to discover skill list
                    skill_list = []
                    for key in ["skill_list", "skills", "class_skills", "trained_skills"]:
                        val = cls_blob.get(key)
                        if isinstance(val, list) and val:
                            skill_list = [str(s) for s in val]
                            break

                    ranks_state = st.session_state.builder_skill_ranks
                    spent = sum(int(ranks_state.get(sk, 0)) for sk in skill_list)

                    if spent > total_points:
                        st.error("Too many points spent; reduce some ranks before continuing.")
                    else:
                        # write to character
                        skills_dict = c.setdefault("skills", {})
                        prof_skills = set(c.setdefault("profs", {}).setdefault("skills", []))
                        for sk in skill_list:
                            r = int(ranks_state.get(sk, 0))
                            if r > 0:
                                skills_dict[sk] = r
                                prof_skills.add(sk)
                        c["profs"]["skills"] = sorted(prof_skills)
                        st.session_state.builder_step = 6
                        st.toast("Skills applied.")
                        st.rerun()

        # ------------------------------------------------------
        # STEP 6: Feats
        # ------------------------------------------------------
        if step == 6:
            st.subheader("Step 6: Choose Feats (Optional)")
            feat_names = [f.get("name", "") if isinstance(f, dict) else str(f) for f in feats_db]
            chosen = st.multiselect("Feats", feat_names, key="builder_feats_multi")

            col = st.columns([1, 1])
            if col[0].button("Back    ", key="feats_back"):
                st.session_state.builder_step = 5
                st.rerun()

            if col[1].button("Apply Feats", type="primary"):
                apply_feats(c, st.session_state.get("builder_feats_multi", []))
                st.session_state.builder_step = 7
                st.toast("Feats applied.")
                st.rerun()

        # ------------------------------------------------------
        # STEP 7: Equipment
        # ------------------------------------------------------
        if step == 7:
            st.subheader("Step 7: Add Equipment (Optional)")
            item_names = [i.get("name", "") if isinstance(i, dict) else str(i) for i in equip_db]
            extras = st.multiselect("Add items", item_names, key="builder_items_multi")

            if st.button("Add Items"):
                eq = set(c.get("equipment") or [])
                for it in extras:
                    if it:
                        eq.add(it)
                c["equipment"] = sorted(eq)
                c["ac"] = compute_ac_from_equipment(c)

                sync_attacks_from_equipment(c)

                st.toast("Items added.")

            col = st.columns([1, 1, 2])
            if col[0].button("Back     ", key="equip_back"):
                st.session_state.builder_step = 6
                st.rerun()

            if col[1].button("Reset Builder"):
                st.session_state.builder_char = {
                    "name": "",
                    "level": 1,
                    "class": "",
                    "subclass": "",
                    "race": "",
                    "background": "",
                    "ac": 10,
                    "hp": 10,
                    "speed": "30 ft.",
                    "abilities": {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                    "proficiency_bonus": 2,
                    "profs": {"saves": [], "skills": [], "weapons": [], "armor": []},
                    "features": [],
                    "feats": [],
                    "spells": [],
                    "equipment": [],
                    "attacks": [],
                    "default_attack_index": 0,
                    "resources": {},   # NEW
                    "actions": [],   
                }
                st.session_state.builder_name = ""
                st.session_state.builder_step = 1
                st.session_state.builder_skill_ranks = {}
                st.toast("Cleared working character.")

            if col[2].button("Add to Party", type="primary"):
                if not c.get("name"):
                    st.warning("Please set a character name.")
                else:
                    st.session_state.party.append(json.loads(json.dumps(c)))
                    st.success(f"Added to party: {c['name']}")
                    # stay on setup page; builder remains for creating another character
            
        st.markdown("---")
        
        with st.expander("🔍 Character Preview (JSON)", expanded=False):
            st.json(st.session_state.builder_char)

        st.markdown("#### 👥 Current Party")
        if not st.session_state.party:
            st.info("🧙 No party members yet. Use the tabs above to add characters.")
        else:
            for i, c in enumerate(st.session_state.party):
                box = st.container(border=True)
                t1, t2, t3, t4 = box.columns([4, 2, 2, 2])

                with t1:
                    st.markdown(f"**{c.get('name','')}**")
                with t2:
                    c["ac"] = int(
                        st.number_input(
                            "AC", 0, 40, int(c.get("ac", 10)), key=f"run_p_ac_{i}"
                        )
                    )
                with t3:
                    c["hp"] = int(
                        st.number_input(
                            "HP", 0, 500, int(c.get("hp", 10)), key=f"run_p_hp_{i}"
                        )
                    )
                with t4:
                    if st.button("Remove", key=f"run_p_rm_{i}"):
                        del st.session_state.party[i]
                        st.rerun()

                # Determine if this party member is the active turn
                is_active_pc = False
                if st.session_state.in_combat:
                    ent = current_turn()
                    if ent and ent.get("kind") == "party" and ent.get("idx") == i:
                        is_active_pc = True

                # Attacks panel – always visible, but marked if it's not their turn
                with box.expander("Attacks"):
                    attacks = c.get("attacks", [])
                    if not attacks:
                        st.write("No attacks listed.")
                    else:
                        for a in attacks:
                            st.write(a)

                    if st.session_state.in_combat and not is_active_pc:
                        st.caption("Waiting for this character's turn.")

        st.markdown("#### Enemies")
        with st.container(border=True):
            
            # Manual entry
            e1, e2, e3, e4, e5 = st.columns([4, 2, 2, 2, 2])
            e_name = e1.text_input("Name", key="e_name")
            e_ac = e2.number_input("AC", 0, 40, 13, key="e_ac")
            e_hp = e3.number_input("HP", 0, 500, 11, key="e_hp")
            e_atk = e4.text_input("Attack (e.g., 'Bite', +4, '2d4+2')", key="e_atk")
            add_enemy = e5.button("Add Enemy")
            if add_enemy and e_name.strip():
                st.session_state.enemies.append(
                    {
                        "name": e_name.strip(),
                        "ac": int(e_ac),
                        "hp": int(e_hp),
                        "attacks": [{"name": e_atk or "Attack", "to_hit": 0, "damage": "1d6"}],
                    }
                )
                st.success(f"Enemy added: {e_name}")

            # From SRD with quantity
            st.markdown("---")
            st.markdown("**Add From SRD**")

            if not st.session_state.get("srd_enemies"):
                st.caption("SRD file not found at ../data/SRD_Monsters.json")
            else:
                srd_names = [m.get("name", "") for m in st.session_state.srd_enemies if m.get("name")]
                srd_name = st.selectbox("SRD Monster", srd_names, key="add_srd_name")
                qty = st.number_input("Quantity", 1, 20, 1, key="add_srd_qty")

                sb = next((m for m in st.session_state.srd_enemies if m.get("name") == srd_name), None)

                if st.button("Add SRD Enemy", type="primary", key="add_srd_enemy_btn"):
                    if sb:
                        for _ in range(int(qty)):
                            blob = json.loads(json.dumps(sb))  # safe deep copy
                            blob["src"] = sb.get("name", "Enemy")
                            blob["name"] = f"{sb.get('name','Enemy')} #{len(st.session_state.enemies)+1}"
                            blob["hp"] = int(blob.get("hp", 10))
                            blob["max_hp"] = int(blob.get("max_hp", blob["hp"]))
                            blob["ac"] = int(blob.get("ac", 10))
                            blob["_hydrated"] = True  # Mark as hydrated since it came from SRD
                            st.session_state.enemies.append(blob)

                        st.toast(f"Added {qty}× {sb.get('name','Enemy')}")
                        st.rerun()
                    else:
                        st.warning("No SRD monster selected.")
                        

    st.markdown("---")
    
    # Summary before beginning
    party_count = len(st.session_state.party)
    enemy_count = len(st.session_state.enemies)
    
    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        st.metric("Party Members", party_count)
    with col2:
        st.metric("Enemies", enemy_count)
    with col3:
        if st.button("🚀 Begin Session", type="primary", use_container_width=True):
            if not st.session_state.party:
                st.warning("⚠️ Add at least one party member before beginning.")
            else:
                st.session_state.boot_mode = "running"
                st.balloons()
                st.rerun()
    
    if not st.session_state.party:
        st.caption("💡 Tip: You need at least one party member to begin a session.")

    st.stop() 

# ---------------- Running Session ----------------

# Run state validation and show warnings if any issues found
_validation_warnings = debug_validate_state()
if _validation_warnings:
    with st.expander("⚠️ Schema Validation Warnings", expanded=False):
        for w in _validation_warnings:
            st.warning(w)

# ========== TOP HEADER BAR ==========
st.markdown(f"# ⚔️ Session: {st.session_state.session_id}")

# Combat status indicator
if st.session_state.in_combat:
    ent = current_turn()
    if ent:
        st.success(f"🎯 **Combat Active** — Round {st.session_state.combat_round} | Turn: **{ent['name']}** ({ent['kind']})")
    else:
        st.warning("⚠️ Combat active but no valid turn entry")
else:
    st.info("🕊️ **Exploration Mode** — Not in combat")

st.divider()

# ========== MAIN LAYOUT: LEFT (Combatants) + RIGHT (Combat/Roller) ==========
left_col, right_col = st.columns([5, 7])

# ===== LEFT COLUMN: Party + Enemies =====
with left_col:
    # ========== PARTY SECTION ==========
    st.markdown("### 👥 Party")
    if not st.session_state.party:
        st.info("🧙 No party members yet. Go to **Setup** to add characters.")
    else:
        for i, c in enumerate(st.session_state.party):
            box = st.container(border=True)
            t1, t2, t3, t4, t5 = box.columns([3, 2, 2, 2, 2])

            with t1:
                st.markdown(f"**{c.get('name','')}**")
            with t2:
                c["ac"] = int(
                    st.number_input(
                        "AC", 0, 40, int(c.get("ac", 10)), key=f"run_p_ac_{i}"
                    )
                )
            with t3:
                c["hp"] = int(
                    st.number_input(
                        "HP", 0, 500, int(c.get("hp", 10)), key=f"run_p_hp_{i}"
                    )
                )
            with t4:
                # Position band dropdown (only during combat)
                if st.session_state.in_combat:
                    current_band = ensure_position_band(c)
                    band_idx = POSITION_BANDS.index(current_band) if current_band in POSITION_BANDS else 1
                    new_band = st.selectbox(
                        "Pos",
                        POSITION_BANDS,
                        index=band_idx,
                        key=f"run_p_band_{i}",
                        format_func=lambda b: get_band_display(b)
                    )
                    c["position_band"] = new_band
                else:
                    st.caption("—")
            with t5:
                if st.button("Remove", key=f"run_p_rm_{i}"):
                    del st.session_state.party[i]
                    st.rerun()

            # Is this the active turn PC?
            is_active_pc = False
            if st.session_state.in_combat:
                ent = current_turn()
                if ent and ent.get("kind") == "party" and ent.get("idx") == i:
                    is_active_pc = True

            # --- Attacks panel for this party member ---
            with box.expander("Attacks"):
                attacks = c.get("attacks") or []
                if not attacks:
                    st.caption("No attacks listed.")
                else:
                    for a in attacks:
                        # Use helper functions for consistent field access
                        name = a.get("name", "Attack")
                        to_hit = get_attack_to_hit(a)
                        dmg = get_attack_damage(a)
                        dmg_type = get_attack_damage_type(a)
                        if dmg_type:
                            st.write(f"{name}: +{to_hit} to hit, {dmg} {dmg_type}")
                        else:
                            st.write(f"{name}: +{to_hit} to hit, {dmg}")

                if st.session_state.in_combat and not is_active_pc:
                    st.caption("Waiting for this character's turn.")

            # --- Conditions panel for this party member ---
            with box.expander("Conditions"):
                conditions = ensure_conditions(c)
                
                if not conditions:
                    st.caption("No active conditions.")
                else:
                    for ci, cond in enumerate(conditions):
                        cond_col1, cond_col2 = st.columns([4, 1])
                        with cond_col1:
                            st.write(get_condition_display(cond))
                        with cond_col2:
                            if st.button("✖", key=f"rm_cond_p_{i}_{ci}"):
                                conditions.pop(ci)
                                st.rerun()
                
                # Add condition form
                st.markdown("**Add Condition**")
                srd_cond_names = get_srd_condition_names()
                cond_options = srd_cond_names + ["(Custom)"]
                
                add_cond_col1, add_cond_col2 = st.columns([2, 1])
                with add_cond_col1:
                    selected_cond = st.selectbox(
                        "Condition",
                        cond_options,
                        key=f"add_cond_sel_p_{i}",
                        label_visibility="collapsed"
                    )
                with add_cond_col2:
                    cond_duration = st.number_input(
                        "Rounds",
                        min_value=0,
                        value=0,
                        key=f"add_cond_dur_p_{i}",
                        help="0 = indefinite"
                    )
                
                if selected_cond == "(Custom)":
                    custom_cond_name = st.text_input(
                        "Custom Condition Name",
                        key=f"add_cond_custom_p_{i}"
                    )
                else:
                    custom_cond_name = None
                
                if st.button("Add Condition", key=f"add_cond_btn_p_{i}"):
                    cond_name = custom_cond_name if selected_cond == "(Custom)" else selected_cond
                    if cond_name:
                        dur = cond_duration if cond_duration > 0 else None
                        add_condition(c, cond_name, duration_rounds=dur)
                        st.toast(f"Added {cond_name} to {c.get('name', 'character')}")
                        st.rerun()
                    else:
                        st.warning("Please enter a condition name.")

            # --- Actions & Resources ---
            with box.expander("Actions & Resources"):
                resources = c.get("resources", {}) or {}
                if resources:
                    st.markdown("**Resources**")
                    for rname, rdata in resources.items():
                        rc1, rc2, rc3 = st.columns([3, 2, 2])
                        current = int(rdata.get("current", 0))
                        max_val = int(rdata.get("max", 0))

                        with rc1:
                            st.markdown(f"{rname}: **{current} / {max_val}**")
                        with rc2:
                            if st.button(
                                f"Use {rname}", key=f"use_res_{i}_{rname}"
                            ):
                                if current > 0:
                                    current -= 1
                                    st.session_state.party[i].setdefault(
                                        "resources", {}
                                    )[rname]["current"] = current
                                    st.toast(
                                        f"{c.get('name','')} uses {rname}! "
                                        f"({current}/{max_val} left)"
                                    )
                                else:
                                    st.warning(
                                        f"{c.get('name','')} has no {rname} uses left."
                                    )
                        with rc3:
                            if st.button(
                                "Reset", key=f"reset_res_{i}_{rname}"
                            ):
                                st.session_state.party[i].setdefault(
                                    "resources", {}
                                )[rname]["current"] = max_val
                                st.toast(
                                    f"{rname} reset to full for {c.get('name','')}."
                                )

                actions = c.get("actions", []) or []
                if actions:
                    st.markdown("**Actions**")
                    for a in actions:
                        line = f"- **{a.get('name','Unnamed')}**"
                        if a.get("resource"):
                            line += f" _(uses {a['resource']})_"
                        st.markdown(line)
                        if a.get("description"):
                            st.caption(a["description"])

    # ========== ENEMIES SECTION (still in left_col) ==========
    st.markdown("---")
    st.markdown("### 👹 Enemies")
    
    if not st.session_state.enemies:
        st.info("🕊️ No enemies in encounter. Add enemies from Setup or use the controls below.")
        # reminder: if this grows large, consider paging or filters by type/CR.
    else:
        for i, e in enumerate(st.session_state.enemies):
            card = st.container(border=True)
            h1, h2, h3, h4, h5 = card.columns([3,2,2,2,2])
            with h1: st.markdown(f"**{e.get('name','')}**")
            with h2: e["ac"] = int(st.number_input("AC", 0, 40, int(e.get("ac",10)), key=f"e_ac_{i}"))
            with h3: e["hp"] = int(st.number_input("HP", 0, 500, int(e.get("hp",10)), key=f"e_hp_{i}"))
            with h4:
                # Position band dropdown (only during combat)
                if st.session_state.in_combat:
                    current_band = ensure_position_band(e)
                    band_idx = POSITION_BANDS.index(current_band) if current_band in POSITION_BANDS else 1
                    new_band = st.selectbox(
                        "Pos",
                        POSITION_BANDS,
                        index=band_idx,
                        key=f"e_band_{i}",
                        format_func=lambda b: get_band_display(b)
                    )
                    e["position_band"] = new_band
                else:
                    st.caption("—")
            with h5:
                if st.button("Remove", key=f"e_rm_{i}"):
                    del st.session_state.enemies[i]; st.rerun()
            with card.expander("Stat & Actions"):
                name = e.get("name", "Enemy")
                ac = e.get("ac", 10)
                hp = e.get("hp", 10)
                st.write(f"{name}: AC {ac}, HP {hp}")

                # Check if already hydrated - avoids expensive SRD lookup every render
                is_hydrated = e.get("_hydrated", False)
                
                # Show Sync button if not hydrated
                if not is_hydrated:
                    # Look up SRD entry (by name or src)
                    base_name = str(name).split("#")[0].strip()
                    srd = next(
                        (
                            m for m in st.session_state.get("srd_enemies", [])
                            if m.get("name") == name
                            or m.get("name") == e.get("src")
                            or m.get("name") == base_name
                        ),
                        None,
                    )
                    
                    if srd:
                        if st.button("🔄 Sync From SRD", key=f"sync_srd_{i}"):
                            # Hydrate this encounter enemy from SRD
                            keep_name = e.get("name", srd.get("name", "Enemy"))
                            keep_conditions = e.get("conditions", [])
                            keep_position = e.get("position_band", "near")
                            st.session_state.enemies[i] = {
                                **srd,
                                "name": keep_name,
                                "hp": int(e.get("hp", srd.get("hp", 10))),
                                "max_hp": int(e.get("max_hp", srd.get("max_hp", srd.get("hp", 10)))),
                                "ac": int(e.get("ac", srd.get("ac", 10))),
                                "conditions": keep_conditions,
                                "position_band": keep_position,
                                "_hydrated": True,  # Mark as hydrated
                            }
                            st.toast(f"Synced {keep_name} from SRD")
                            st.rerun()
                        st.caption("Click to load full stats from SRD")
                    else:
                        st.caption("No SRD data found for this monster.")
                
                # Display actions/attacks if available (whether hydrated or not)
                actions = e.get("actions", []) or []
                attacks = e.get("attacks", []) or []

                if actions:
                    st.markdown("**Actions**")
                    for a in actions:
                        nm = a.get("name", "Action")
                        desc = a.get("description", a.get("desc", ""))
                        if desc:
                            st.markdown(f"- **{nm}**: {desc}")
                        else:
                            st.markdown(f"- **{nm}**")

                if attacks:
                    st.markdown("**Attacks**")
                    for a in attacks:
                        nm = a.get("name", "Attack")
                        th = get_attack_to_hit(a)
                        dmg = get_attack_damage(a)
                        dt = get_attack_damage_type(a)
                        line = f"- **{nm}** (+{th} to hit) — {dmg}"
                        if dt:
                            line += f" {dt}"
                        st.markdown(line)

                specials = e.get("special_abilities", []) or []
                if specials:
                    st.markdown("**Special Abilities**")
                    for sa in specials:
                        st.markdown(f"- **{sa.get('name','')}**: {sa.get('desc','')}")
            
            # --- Conditions panel for this enemy ---
            with card.expander("Conditions"):
                conditions = ensure_conditions(e)
                
                if not conditions:
                    st.caption("No active conditions.")
                else:
                    for ci, cond in enumerate(conditions):
                        cond_col1, cond_col2 = st.columns([4, 1])
                        with cond_col1:
                            st.write(get_condition_display(cond))
                        with cond_col2:
                            if st.button("✖", key=f"rm_cond_e_{i}_{ci}"):
                                conditions.pop(ci)
                                st.rerun()
                
                # Add condition form
                st.markdown("**Add Condition**")
                srd_cond_names = get_srd_condition_names()
                cond_options = srd_cond_names + ["(Custom)"]
                
                add_cond_col1, add_cond_col2 = st.columns([2, 1])
                with add_cond_col1:
                    selected_cond = st.selectbox(
                        "Condition",
                        cond_options,
                        key=f"add_cond_sel_e_{i}",
                        label_visibility="collapsed"
                    )
                with add_cond_col2:
                    cond_duration = st.number_input(
                        "Rounds",
                        min_value=0,
                        value=0,
                        key=f"add_cond_dur_e_{i}",
                        help="0 = indefinite"
                    )
                
                if selected_cond == "(Custom)":
                    custom_cond_name = st.text_input(
                        "Custom Condition Name",
                        key=f"add_cond_custom_e_{i}"
                    )
                else:
                    custom_cond_name = None
                
                if st.button("Add Condition", key=f"add_cond_btn_e_{i}"):
                    cond_name = custom_cond_name if selected_cond == "(Custom)" else selected_cond
                    if cond_name:
                        dur = cond_duration if cond_duration > 0 else None
                        add_condition(e, cond_name, duration_rounds=dur)
                        st.toast(f"Added {cond_name} to {e.get('name', 'enemy')}")
                        st.rerun()
                    else:
                        st.warning("Please enter a condition name.")
    
    # Quick Add Enemy (in left column)
    with st.expander("➕ Quick Add Enemy", expanded=False):
        add_mode = st.radio("Add Mode", ["From SRD", "Manual"], horizontal=True, key="left_add_mode")
        
        if add_mode == "From SRD":
            if not st.session_state.get("srd_enemies"):
                st.warning("SRD bestiary not loaded.")
            else:
                srd_names = [m["name"] for m in st.session_state.srd_enemies]
                srd_pick = st.selectbox("Monster", srd_names, key="left_srd_pick")
                srd_qty = st.number_input("Quantity", 1, 10, 1, key="left_srd_qty")
                if st.button("Add", key="left_add_srd_btn"):
                    src = next((m for m in st.session_state.srd_enemies if m["name"] == srd_pick), None)
                    if src:
                        for i in range(int(srd_qty)):
                            blob = json.loads(json.dumps(src))
                            blob["name"] = f"{src['name']}" if srd_qty == 1 else f"{src['name']} #{i+1}"
                            blob["src"] = src["name"]
                            blob["_hydrated"] = True
                            st.session_state.enemies.append(blob)
                        st.toast(f"Added {srd_qty}× {srd_pick}")
                        st.rerun()
        else:
            e_name = st.text_input("Name", key="left_e_name")
            e_ac = st.number_input("AC", 0, 40, 13, key="left_e_ac")
            e_hp = st.number_input("HP", 0, 500, 11, key="left_e_hp")
            if st.button("Add", key="left_add_manual_btn"):
                if e_name.strip():
                    st.session_state.enemies.append({
                        "name": e_name.strip(),
                        "ac": int(e_ac),
                        "hp": int(e_hp),
                        "attacks": [{"name": "Attack", "to_hit": 0, "damage": "1d6"}]
                    })
                    st.toast(f"Added {e_name}")
                    st.rerun()

# ===== RIGHT COLUMN: Combat Tracker + Attack Roller =====
with right_col:
    # ---------------- Combat / Turn Tracker ----------------
    st.markdown("### ⚔️ Combat Tracker")
    
    cA, cB, cC, cD = st.columns([2,1,1,1])
    
    with cA:
        if not st.session_state.in_combat:
            if st.button("Start Combat (Roll Initiative)"):
                if not st.session_state.party or not st.session_state.enemies:
                    st.warning("Need at least one party member and one enemy.")
                else:
                    start_combat()
                    st.success("Combat started. Initiative rolled.")
        else:
            ent = current_turn()
            if ent:
                st.markdown(
                    f"**Round {st.session_state.combat_round}** — "
                    f"Turn: **{ent['name']}** ({ent['kind']}, Init {ent['init']})"
                )
            else:
                st.markdown("Combat active, but no valid turn entry.")
    
    with cB:
        if st.session_state.in_combat and st.button("Next Turn"):
            next_turn()
    
    with cC:
        # Auto-resolve enemy turn button
        if st.session_state.in_combat:
            ent = current_turn()
            is_enemy_turn = ent and ent.get("kind") == "enemy"
            
            if st.button("🤖 Auto Enemy", disabled=not is_enemy_turn, help="Auto-resolve enemy turn"):
                if is_enemy_turn:
                    # Get enemy info for logging
                    enemy_idx = ent.get("idx", 0)
                    enemy = st.session_state.enemies[enemy_idx] if enemy_idx < len(st.session_state.enemies) else None
                    
                    # Capture state snapshot for logging
                    state_snapshot = None
                    if st.session_state.get("ai_logging_enabled", False) and AI_LOGGING_AVAILABLE:
                        enemy_pos = enemy.get("pos") if enemy else None
                        targets = [p for p in st.session_state.party if int(p.get("hp", 0)) > 0]
                        nearest_dist = None
                        if enemy_pos and targets:
                            from ai.featurize import get_grid_distance
                            nearest_dist = min(get_grid_distance(enemy_pos, t.get("pos", {})) for t in targets)
                        state_snapshot = {
                            "round": st.session_state.get("combat_round", 1),
                            "enemy_hp": enemy.get("hp") if enemy else None,
                            "enemy_pos": enemy_pos,
                            "target_count": len(targets),
                            "nearest_target_dist": nearest_dist,
                        }
                    
                    # Execute AI turn
                    ai_messages = ai_resolve_enemy_turn()
                    
                    # Log all messages to chat
                    for msg in ai_messages:
                        st.session_state.chat_log.append(("System", msg))
                    
                    # Log to AI telemetry if enabled
                    if st.session_state.get("ai_logging_enabled", False) and AI_LOGGING_AVAILABLE and state_snapshot:
                        logger = get_ui_logger()
                        if logger:
                            logger.log_ui_decision(
                                enemy_name=enemy.get("name", "Enemy") if enemy else "Unknown",
                                enemy_idx=enemy_idx,
                                state_snapshot=state_snapshot,
                                action_chosen={"messages": ai_messages[:3]},  # First 3 messages summarize action
                                outcome={"message_count": len(ai_messages)}
                            )
                    
                    # Show results in a toast
                    st.toast(f"Enemy turn resolved: {len(ai_messages)} actions")
                    st.rerun()
    
    with cD:
        if st.session_state.in_combat and st.button("End Combat"):
            end_combat()
            st.info("Combat ended.")
    
    # Initiative Order display
    if st.session_state.initiative_order:
        st.markdown("**Initiative Order**")
        for i, ent in enumerate(st.session_state.initiative_order):
            marker = "➡️" if (i == st.session_state.turn_index and st.session_state.in_combat) else ""
            st.write(f"{marker} {ent['name']} — Init {ent['init']} (DEX mod {ent['dex_mod']})")
    
    # Display action economy state during combat
    if st.session_state.in_combat:
        st.markdown("**Action Economy**")
        st.caption(explain_action_state())
    
    # AI Telemetry expander
    with st.expander("🤖 AI Telemetry", expanded=False):
        if AI_LOGGING_AVAILABLE:
            # Initialize logging state
            if "ai_logging_enabled" not in st.session_state:
                st.session_state.ai_logging_enabled = False
            
            logging_enabled = st.toggle(
                "Enable AI Logging",
                value=st.session_state.ai_logging_enabled,
                key="ai_logging_toggle",
                help="Log enemy AI decisions to JSONL files for training data"
            )
            
            if logging_enabled != st.session_state.ai_logging_enabled:
                st.session_state.ai_logging_enabled = logging_enabled
                set_ui_logging_enabled(logging_enabled)
                if logging_enabled:
                    st.success("AI logging enabled. Decisions will be saved to data/ai/rollout_logs/")
                else:
                    st.info("AI logging disabled.")
            
            if st.session_state.ai_logging_enabled:
                st.caption("📊 Logging active - enemy decisions are being recorded")
                
                # Show log directory
                log_dir = os.path.join(_project_root, "data", "ai", "rollout_logs")
                if os.path.exists(log_dir):
                    log_files = [f for f in os.listdir(log_dir) if f.endswith(".jsonl")]
                    st.caption(f"Log files: {len(log_files)} in data/ai/rollout_logs/")
        else:
            st.info("AI logging module not available. Install ai/ module for telemetry.")
            st.caption("The UI works fine without it - this is for RL training data collection.")
    
    st.markdown("### 🎯 Attack Roller")
    
    # Only active during combat, and only for the active combatant (PC or enemy)
    ent = current_turn()
    if not (st.session_state.in_combat and ent):
        st.info("🎲 Attack Roller is only available during combat. Start combat to use this feature.")
    else:
        kind = ent.get("kind")
        idx = ent.get("idx")
    
        # Resolve attacker (party or enemy) + target list
        # NOTE: kind must be "party" or "enemy" (never "pc")
        if kind == "party":
            if idx is None or idx >= len(st.session_state.party):
                st.warning("Active party member not found in party list.")
            else:
                att = st.session_state.party[idx]
                targets = st.session_state.enemies
                target_kind = "enemy"
        elif kind == "enemy":
            if idx is None or idx >= len(st.session_state.enemies):
                st.warning("Active enemy not found in enemies list.")
            else:
                att = st.session_state.enemies[idx]
                targets = st.session_state.party
                target_kind = "party"
        else:
            att = None
            targets = []
            target_kind = None
            st.caption("Unknown active combatant type.")
    
        if att:
            # Display action economy state for this actor
            st.caption(f"**Actions Available:** {explain_action_state()}")
            
            # reminder: enemies added from SRD are already normalized into our schema
            actions = att.get("attacks") or att.get("actions") or []
            action_names = [a.get("name", "Action") for a in actions] + ["(Custom)"]
    
            # Unique widget keys per-turn/actor so Streamlit never duplicates keys
            actor_key = f"{kind}_{idx}"
    
            act = st.selectbox(
                "Action",
                action_names,
                key=f"atk_act_sel_{actor_key}",
            )
    
            # Determine action type and get action object
            aobj = None
            required_action_type = "standard"  # default for attacks
            
            if act == "(Custom)":
                to_hit = st.number_input(
                    "To-Hit Bonus",
                    -10,
                    20,
                    0,
                    key=f"atk_custom_to_{actor_key}",
                )
                dmg = st.text_input(
                    "Damage Dice",
                    value="1d6",
                    key=f"atk_custom_dmg_{actor_key}",
                )
                dmg_type = st.text_input(
                    "Damage Type (optional)",
                    value="",
                    key=f"atk_custom_dt_{actor_key}",
                )
                # Custom attacks default to standard action
                required_action_type = "standard"
            else:
                aobj = next((a for a in actions if a.get("name") == act), None)
                # Use helper functions for consistent field access
                to_hit = get_attack_to_hit(aobj) if aobj else 0
                dmg = get_attack_damage(aobj) if aobj else "1d6"
                dmg_type = get_attack_damage_type(aobj) if aobj else ""
                # Check if action has a specific action_type from ACTION_SCHEMA
                required_action_type = get_action_type_for_attack(aobj)
    
            # Detect if this is a spell save action
            is_spell_save = aobj and aobj.get("save") and aobj.get("dc")
            is_spell_attack = aobj and aobj.get("type") == "spell_attack"
            spell_dc = aobj.get("dc") if aobj else None
            spell_save = aobj.get("save") if aobj else None
    
            # Show what action type this will consume and range info
            st.caption(f"This action requires: **{required_action_type.capitalize()}** action")
            
            # Show spell info if applicable
            if is_spell_save:
                st.caption(f"🔮 **Spell Save:** DC {spell_dc} {spell_save}")
            elif is_spell_attack:
                st.caption(f"🔮 **Spell Attack:** +{to_hit} to hit")
            
            # Show attack range requirement
            if aobj:
                st.caption(f"Attack range: {explain_band_requirement(aobj)}")
            
            # Show attacker's current position
            attacker_band = get_position_band(att)
            st.caption(f"Your position: **{get_band_display(attacker_band)}**")
    
            if not targets:
                st.caption("No valid targets available.")
            else:
                # Target picker with position info
                def format_target(i):
                    t = targets[i]
                    t_band = get_position_band(t)
                    return f"{t.get('name', f'Target #{i+1}')} ({t_band})"
                
                target_idx = st.selectbox(
                    "Target",
                    list(range(len(targets))),
                    format_func=format_target,
                    key=f"atk_target_{actor_key}",
                )
    
                target = targets[target_idx]
                target_ac = int(target.get("ac", 10))
                target_band = get_position_band(target)
                st.caption(f"Target AC: {target_ac} | Position: **{get_band_display(target_band)}**")

                # Check if the required action type is available
                action_available = can_spend(required_action_type)
                
                # Check range band validity
                attack_for_range = aobj if aobj else {"range": 5}  # Custom attacks default to melee
                range_valid = can_attack_at_band(attack_for_range, target_band)
                
                # Button label changes based on action type
                button_label = "Cast Spell" if (is_spell_save or is_spell_attack) else "Roll Attack"
                
                if not action_available:
                    st.error(f"❌ {required_action_type.capitalize()} action already used this turn!")
                    st.button(button_label, key=f"atk_roll_{actor_key}", disabled=True)
                elif not range_valid:
                    max_band = get_attack_max_band(attack_for_range)
                    st.error(f"❌ Target is at **{target_band}** range, but this attack only reaches **{max_band}**! Move closer or choose a different attack.")
                    st.button(button_label, key=f"atk_roll_{actor_key}", disabled=True)
                elif st.button(button_label, key=f"atk_roll_{actor_key}"):
                    # Spend the action
                    spend(required_action_type)
                    
                    # ========== SPELL SAVE RESOLUTION ==========
                    if is_spell_save:
                        # Target makes saving throw
                        d20 = random.randint(1, 20)
                        
                        # Get target's save modifier (if available)
                        save_mod = 0
                        target_abilities = target.get("abilities", {})
                        if spell_save and spell_save in target_abilities:
                            save_mod = (int(target_abilities[spell_save]) - 10) // 2
                        
                        save_total = d20 + save_mod
                        save_success = save_total >= spell_dc
                        
                        st.write(
                            f"🎯 **{target.get('name', 'Target')}** makes a **{spell_save}** save: "
                            f"d20({d20}) + {save_mod} = **{save_total}** vs DC {spell_dc} → "
                            f"{'**SAVED!**' if save_success else '**FAILED!**'}"
                        )
                        
                        st.session_state.chat_log.append(
                            (
                                "System",
                                f"{att.get('name','Caster')} casts {act} on {target.get('name','Target')} → "
                                f"{spell_save} save: {save_total} vs DC {spell_dc} → {'SAVED' if save_success else 'FAILED'} "
                                f"({required_action_type.capitalize()} action spent)",
                            )
                        )
                        
                        # Apply damage on failed save (or half on success for some spells)
                        if not save_success:
                            if dmg and dmg != "—":
                                dmg_total, breakdown = roll_dice(dmg)
                                st.write(f"💥 Damage: {dmg} → **{dmg_total}** ({breakdown})")
                                if dmg_type:
                                    st.caption(f"Damage Type: {dmg_type}")
                                
                                # Apply damage
                                if target_kind == "enemy":
                                    before = int(st.session_state.enemies[target_idx].get("hp", 0))
                                    after = max(0, before - int(dmg_total))
                                    st.session_state.enemies[target_idx]["hp"] = after
                                else:
                                    before = int(st.session_state.party[target_idx].get("hp", 0))
                                    after = max(0, before - int(dmg_total))
                                    st.session_state.party[target_idx]["hp"] = after
                                
                                st.write(
                                    f"{target.get('name','Target')} takes **{dmg_total}** damage "
                                    f"and is now at **{after} HP** (was {before})."
                                )
                                
                                st.session_state.chat_log.append(
                                    (
                                        "System",
                                        f"{att.get('name','Caster')} deals {dmg_total} {dmg_type or ''} damage to "
                                        f"{target.get('name','Target')} ({before} → {after} HP).",
                                    )
                                )
                            else:
                                st.write("Spell effect applied (no damage).")
                        else:
                            st.write("Target resists the spell effect!")
                    
                    # ========== SPELL ATTACK / REGULAR ATTACK RESOLUTION ==========
                    else:
                        d20 = random.randint(1, 20)
                        total = d20 + int(to_hit)
                        hit = total >= target_ac
    
                        attack_type = "🔮 Spell attack" if is_spell_attack else "To-Hit"
                        st.write(
                            f"{attack_type}: d20({d20}) + {to_hit} = **{total}** "
                            f"vs AC {target_ac} → {'**HIT**' if hit else '**MISS**'}"
                        )
    
                        st.session_state.chat_log.append(
                            (
                                "System",
                                f"{att.get('name','Attacker')} {'casts' if is_spell_attack else 'attacks'} {target.get('name','Target')} with {act} → "
                                f"{total} vs AC {target_ac} → {'HIT' if hit else 'MISS'} "
                                f"({required_action_type.capitalize()} action spent)",
                            )
                        )
    
                        if hit:
                            # Defensive: handle missing or invalid damage
                            if dmg == "—" or not dmg:
                                st.write("Damage: **—** (no damage specified)")
                                dmg_total = 0
                            else:
                                dmg_total, breakdown = roll_dice(dmg)
                                st.write(f"Damage: {dmg} → **{dmg_total}** ({breakdown})")
                            if dmg_type:
                                st.caption(f"Damage Type: {dmg_type}")
    
                            # Apply damage to the correct list in session state
                            if target_kind == "enemy":
                                before = int(st.session_state.enemies[target_idx].get("hp", 0))
                                after = max(0, before - int(dmg_total))
                                st.session_state.enemies[target_idx]["hp"] = after
                            else:
                                before = int(st.session_state.party[target_idx].get("hp", 0))
                                after = max(0, before - int(dmg_total))
                                st.session_state.party[target_idx]["hp"] = after
    
                            st.write(
                                f"{target.get('name','Target')} takes **{dmg_total}** damage "
                                f"and is now at **{after} HP** (was {before})."
                            )
    
                            st.session_state.chat_log.append(
                                (
                                    "System",
                                    f"{att.get('name','Attacker')} deals {dmg_total} damage to "
                                    f"{target.get('name','Target')} ({before} → {after} HP).",
                                )
                            )


# ========== TACTICAL MAP SECTION ==========
st.divider()
st.markdown("### 🗺️ Tactical Map")

# Initialize map state
if "map_selected_actor" not in st.session_state:
    st.session_state.map_selected_actor = None
if "map_edit_mode" not in st.session_state:
    st.session_state.map_edit_mode = False
if "map_show_coords" not in st.session_state:
    st.session_state.map_show_coords = False
if "map_last_click" not in st.session_state:
    st.session_state.map_last_click = None
if "map_hazard_paint" not in st.session_state:
    st.session_state.map_hazard_paint = "None"

# Ensure grid exists
ensure_grid()
auto_place_actors()

# Map controls
map_ctrl_col1, map_ctrl_col2, map_ctrl_col3, map_ctrl_col4 = st.columns([2, 2, 2, 2])

with map_ctrl_col1:
    grid_width = st.number_input("Grid Width", min_value=5, max_value=30, value=st.session_state.grid.get("width", 20), key="map_width")
    grid_height = st.number_input("Grid Height", min_value=5, max_value=30, value=st.session_state.grid.get("height", 20), key="map_height")

with map_ctrl_col2:
    square_size = st.selectbox("Square Size (ft)", [5, 10], index=0 if st.session_state.grid.get("square_size_ft", 5) == 5 else 1, key="map_square_size")
    terrain_names = get_terrain_names()
    current_biome = st.session_state.grid.get("biome") or (terrain_names[0] if terrain_names else "Forest")
    biome_idx = terrain_names.index(current_biome) if current_biome in terrain_names else 0
    selected_biome = st.selectbox("Encounter Biome", terrain_names, index=biome_idx, key="map_biome")

with map_ctrl_col3:
    map_seed = st.number_input("Seed", min_value=0, max_value=999999, value=st.session_state.grid.get("seed") or 12345, key="map_seed")
    if st.button("🎲 Generate Map", key="map_generate"):
        new_grid = generate_map(grid_width, grid_height, selected_biome, map_seed)
        new_grid["square_size_ft"] = square_size
        st.session_state.grid = new_grid
        # Re-place actors on new grid
        for actor in st.session_state.get("party", []):
            actor["pos"] = None
        for actor in st.session_state.get("enemies", []):
            actor["pos"] = None
        auto_place_actors()
        st.toast(f"Generated {selected_biome} map (seed: {map_seed})")
        st.rerun()

with map_ctrl_col4:
    st.session_state.map_edit_mode = st.toggle("✏️ Edit Mode", value=st.session_state.map_edit_mode, key="map_edit_toggle")
    st.session_state.map_show_coords = st.toggle("📍 Show Coords", value=st.session_state.map_show_coords, key="map_coords_toggle")

# Handle grid clicks via query params
try:
    query_params = st.query_params
    click_x = query_params.get("grid_click_x")
    click_y = query_params.get("grid_click_y")
    click_t = query_params.get("grid_click_t")
    
    if click_x is not None and click_y is not None and click_t is not None:
        click_x = int(click_x)
        click_y = int(click_y)
        click_key = f"{click_x},{click_y},{click_t}"
        
        if st.session_state.map_last_click != click_key:
            st.session_state.map_last_click = click_key
            
            grid = st.session_state.grid
            
            if st.session_state.map_edit_mode:
                # Edit mode: cycle tile type or paint hazard
                cell = get_cell(grid, click_x, click_y)
                if cell:
                    hazard_paint = st.session_state.get("map_hazard_paint", "None")
                    
                    if hazard_paint and hazard_paint != "None":
                        # Paint hazard on non-blocked tiles
                        tile = get_tile(cell["tile"])
                        if not tile.get("blocked", False):
                            set_cell_hazard(grid, click_x, click_y, hazard_paint)
                            hazard_info = get_hazard(hazard_paint)
                            st.toast(f"Hazard at ({click_x},{click_y}) → {hazard_info.get('name', hazard_paint)}")
                        else:
                            st.warning("Cannot place hazard on blocked tile!")
                    else:
                        # Cycle tile type using tiles.json ordering
                        tile_order = get_tile_ids()
                        current_idx = tile_order.index(cell["tile"]) if cell["tile"] in tile_order else 0
                        next_idx = (current_idx + 1) % len(tile_order)
                        next_tile_id = tile_order[next_idx]
                        set_cell_tile(grid, click_x, click_y, next_tile_id)
                        # Clear hazard when changing to blocked tile
                        next_tile = get_tile(next_tile_id)
                        if next_tile.get("blocked", False):
                            set_cell_hazard(grid, click_x, click_y, None)
                        st.toast(f"Tile at ({click_x},{click_y}) → {next_tile.get('name', next_tile_id)}")
                    
                    # Clear query params
                    st.query_params.clear()
                    st.rerun()
            else:
                # Normal mode: select actor or move
                kind, idx, actor = get_actor_at(click_x, click_y)
                
                if actor is not None:
                    # Clicked on an actor - select it
                    st.session_state.map_selected_actor = {"kind": kind, "idx": idx}
                    st.toast(f"Selected: {actor.get('name', 'Actor')}")
                    st.query_params.clear()
                    st.rerun()
                elif st.session_state.map_selected_actor:
                    # Clicked on empty cell - try to move selected actor
                    sel = st.session_state.map_selected_actor
                    sel_kind = sel.get("kind")
                    sel_idx = sel.get("idx")
                    
                    if sel_kind == "party" and sel_idx < len(st.session_state.party):
                        actor = st.session_state.party[sel_idx]
                    elif sel_kind == "enemy" and sel_idx < len(st.session_state.enemies):
                        actor = st.session_state.enemies[sel_idx]
                    else:
                        actor = None
                    
                    if actor:
                        pos = actor.get("pos", {})
                        start_x, start_y = pos.get("x", 0), pos.get("y", 0)
                        speed_ft = actor.get("speed_ft", 30)
                        square_size_ft = grid.get("square_size_ft", 5)
                        max_squares = speed_ft // square_size_ft
                        
                        # Check if destination is valid
                        if is_cell_blocked(grid, click_x, click_y):
                            st.warning(f"Cannot move to ({click_x},{click_y}) - blocked terrain!")
                        elif is_cell_occupied(click_x, click_y, actor):
                            st.warning(f"Cannot move to ({click_x},{click_y}) - occupied!")
                        else:
                            # In combat: check movement cost and spend move action
                            if st.session_state.in_combat:
                                # Check if move action available
                                if not can_spend("move"):
                                    st.warning("No move action available this turn!")
                                else:
                                    path = find_path(grid, start_x, start_y, click_x, click_y, max_squares, actor)
                                    if path is None:
                                        st.warning(f"Cannot reach ({click_x},{click_y}) - too far or no valid path!")
                                    else:
                                        # Valid move - execute it
                                        spend("move")
                                        actor["pos"] = {"x": click_x, "y": click_y}
                                        st.toast(f"{actor.get('name', 'Actor')} moved to ({click_x},{click_y})")
                                        st.session_state.chat_log.append(
                                            ("System", f"{actor.get('name', 'Actor')} moves to ({click_x},{click_y})")
                                        )
                            else:
                                # Out of combat: free movement (still check path exists)
                                path = find_path(grid, start_x, start_y, click_x, click_y, 999, actor)
                                if path is None:
                                    st.warning(f"Cannot reach ({click_x},{click_y}) - no valid path!")
                                else:
                                    actor["pos"] = {"x": click_x, "y": click_y}
                                    st.toast(f"{actor.get('name', 'Actor')} moved to ({click_x},{click_y})")
                    
                    st.query_params.clear()
                    st.rerun()
except Exception as e:
    pass  # Ignore query param errors

# Calculate reachable squares for selected actor
reachable = None
selected_actor = st.session_state.map_selected_actor
if selected_actor and not st.session_state.map_edit_mode:
    sel_kind = selected_actor.get("kind")
    sel_idx = selected_actor.get("idx")
    
    actor = None
    if sel_kind == "party" and sel_idx < len(st.session_state.get("party", [])):
        actor = st.session_state.party[sel_idx]
    elif sel_kind == "enemy" and sel_idx < len(st.session_state.get("enemies", [])):
        actor = st.session_state.enemies[sel_idx]
    
    if actor:
        pos = actor.get("pos", {})
        if pos:
            speed_ft = actor.get("speed_ft", 30)
            square_size_ft = st.session_state.grid.get("square_size_ft", 5)
            max_squares = speed_ft // square_size_ft
            reachable = dijkstra_reachable(st.session_state.grid, pos["x"], pos["y"], max_squares, actor)

# Render the grid
import streamlit.components.v1 as components

grid_html = render_grid_html(
    st.session_state.grid,
    st.session_state.map_selected_actor,
    reachable,
    st.session_state.map_show_coords,
    st.session_state.map_edit_mode
)

# Display grid
map_col, info_col = st.columns([3, 1])

with map_col:
    components.html(grid_html, height=st.session_state.grid["height"] * 28 + 40, scrolling=True)

with info_col:
    st.markdown("**Selected Actor**")
    if st.session_state.map_selected_actor:
        sel = st.session_state.map_selected_actor
        sel_kind = sel.get("kind")
        sel_idx = sel.get("idx")
        
        actor = None
        if sel_kind == "party" and sel_idx < len(st.session_state.get("party", [])):
            actor = st.session_state.party[sel_idx]
        elif sel_kind == "enemy" and sel_idx < len(st.session_state.get("enemies", [])):
            actor = st.session_state.enemies[sel_idx]
        
        if actor:
            st.write(f"**{actor.get('name', 'Unknown')}**")
            st.caption(f"Speed: {actor.get('speed_ft', 30)} ft")
            pos = actor.get("pos", {})
            st.caption(f"Position: ({pos.get('x', '?')}, {pos.get('y', '?')})")
            
            if st.button("Deselect", key="map_deselect"):
                st.session_state.map_selected_actor = None
                st.rerun()
    else:
        st.caption("Click an actor to select")
    
    st.markdown("---")
    st.markdown("**Legend**")
    tiles = load_tiles()
    for tile_id in get_tile_ids()[:4]:  # Show first 4 tiles in legend
        tile_info = tiles.get(tile_id, {})
        st.markdown(f"<span style='background:{tile_info.get('color', '#ccc')};padding:2px 6px;'>{tile_info.get('name', tile_id)}</span>", unsafe_allow_html=True)
    st.caption("🟠 = Hazard")
    
    if st.session_state.map_edit_mode:
        st.markdown("---")
        st.markdown("**Edit Mode**")
        st.caption("Click tiles to cycle type")
        
        # Hazard painter - show hazard names from hazards.json
        biome = get_biome_config(st.session_state.grid.get("biome", "Forest"))
        hazard_ids = biome.get("hazards", []) if biome else []
        hazards_data = load_hazards()
        # Build options with display names
        hazard_options = ["None"]
        hazard_id_map = {}
        for hid in hazard_ids:
            if hid in hazards_data:
                h_name = hazards_data[hid].get("name", hid)
                hazard_options.append(h_name)
                hazard_id_map[h_name] = hid
        
        selected_hazard_name = st.selectbox("Paint Hazard", hazard_options, key="map_hazard_paint_name")
        
        # Store the hazard ID (not name) for painting
        if selected_hazard_name != "None":
            st.session_state.map_hazard_paint = hazard_id_map.get(selected_hazard_name, selected_hazard_name)
            hazard_info = hazards_data.get(st.session_state.map_hazard_paint, {})
            st.caption(f"Click tiles to add: {hazard_info.get('description', '')[:50]}...")
        else:
            st.session_state.map_hazard_paint = "None"

# ========== BOTTOM SECTION: DM Notes + Chat ==========
st.divider()

dm_notes_col, chat_col = st.columns([4, 8])

# ---- DM Notes (separate from chat) ----
with dm_notes_col:
    st.markdown("### 📝 DM Notes")
    st.text_area(
        "Private notes (not shown in chat)",
        key="dm_notes",
        height=200,
        placeholder="Use this area for:\n• Session planning\n• NPC motivations\n• Plot hooks\n• Secret information"
    )

# ---- Chat Log ----
with chat_col:
    st.markdown("### 💬 Chat Log")
    
    # Chat input at top
    c1, c2 = st.columns([6,1])
    with c1:
        user_msg = st.text_input(
            "Type a message (e.g., 'attack the goblin', '/roll 2d6+1')",
            key="chat_input",
            label_visibility="collapsed",
            placeholder="Type a message..."
        )
    with c2:
        send = st.button("Send", use_container_width=True)

    # Handle chat submission
    if send:
        msg = (user_msg or "").strip()
        if msg:
            st.session_state.chat_log.append(("Player", msg))

            # 1) Move intent (consumes Move action on the active turn)
            move_result = resolve_move_action(msg)
            if move_result is not None:
                st.session_state.chat_log.append(("System", move_result))
            else:
                # 2) Attack intent
                result = resolve_attack(msg)
                if result is not None:
                    st.session_state.chat_log.append(("System", result))
                else:
                    # 3) Skill check intent
                    skill_result = resolve_skill_check(msg)
                    if skill_result is not None:
                        st.session_state.chat_log.append(("System", skill_result))
                    else:
                        # 4) Default DM reply
                        reply = reply_for(msg)
                        if not msg.lower().startswith("/roll") and "roll " in msg.lower():
                            more = extract_inline_rolls(msg)
                            if more:
                                lines = []
                                for d in more:
                                    t, br = roll_dice(d)
                                    lines.append(f"• {d}: {br}")
                                reply += "\n\nInline rolls:\n" + "\n".join(lines)
                        st.session_state.chat_log.append(("DM", reply))

            st.rerun()
    
    # Chat message display
    chat_box = st.container(border=True, height=250)

    # Display chat messages
    if not st.session_state.chat_log:
        st.caption("💭 No messages yet. Type below to interact with the Virtual DM.")
    else:
        for speaker, text in st.session_state.chat_log[-30:]:
            if speaker == "System":
                st.caption(f"🎲 {text}")
            elif speaker == "DM":
                st.info(f"🎭 **DM:** {text}")
            elif speaker == "Player":
                st.success(f"👤 **You:** {text}")
            else:
                st.markdown(f"**{speaker}:** {text}")

# ========== FOOTER: Bestiary Reference ==========
st.divider()
st.markdown("### 📖 Reference")

with st.expander("🐉 Browse Bestiary", expanded=False):
    if not st.session_state.get("srd_enemies"):
        st.info("📚 SRD Bestiary not loaded. Check that SRD_Monsters.json exists in the data folder.")
    else:
        names = [m["name"] for m in st.session_state.srd_enemies]
        pick = st.selectbox("View statblock", names, key="bestiary_pick")
        sb = next((m for m in st.session_state.srd_enemies if m["name"] == pick), None)
        if sb:
            # Tolerant full stat renderer
            name = sb.get("name","Unknown")
            size = sb.get("size","—"); typ = sb.get("type","—"); ali = sb.get("alignment","—")
            ac = sb.get("ac","—"); hp = sb.get("hp","—"); hd = sb.get("hit_dice","—"); spd = sb.get("speed","—")
            st.markdown(f"**{name}** — {size} {typ}, {ali}")
            st.markdown(f"**Armor Class** {ac}  •  **Hit Points** {hp} ({hd})  •  **Speed** {spd}")

            abil = sb.get("abilities", {})
            if abil:
                STR = abil.get("STR","—"); DEX = abil.get("DEX","—"); CON = abil.get("CON","—")
                INT = abil.get("INT","—"); WIS = abil.get("WIS","—"); CHA = abil.get("CHA","—")
                st.markdown(f"STR {STR}  |  DEX {DEX}  |  CON {CON}  |  INT {INT}  |  WIS {WIS}  |  CHA {CHA}")

            saves = sb.get("saves", {}); skills = sb.get("skills", {})
            s_saves  = ", ".join(f"{k} {v}" for k,v in saves.items()) if saves else "—"
            s_skills = ", ".join(f"{k} {v}" for k,v in skills.items()) if skills else "—"
            senses = sb.get("senses","—"); langs = sb.get("languages","—"); cr = sb.get("cr","—")
            st.caption(f"Saves: {s_saves}  •  Skills: {s_skills}")
            st.caption(f"Senses: {senses}  •  Languages: {langs}  •  CR: {cr}")

            traits = sb.get("traits", [])
            if traits:
                with st.expander("Traits"):
                    for t in traits:
                        tname = t.get("name","Trait"); ttxt = t.get("text","")
                        st.markdown(f"- **{tname}.** {ttxt}")

            actions = sb.get("actions", [])
            if actions:
                with st.expander("Actions"):
                    for a in actions:
                        nm = a.get("name","Action")
                        th = a.get("to_hit")
                        reach = a.get("reach"); rng = a.get("range")
                        targets = a.get("targets","one")
                        dmg = a.get("damage","—")
                        line = f"**{nm}.**"
                        if th is not None: line += f" +{th} to hit"
                        if reach: line += f", reach {reach}"
                        if rng:   line += f", range {rng}"
                        line += f"; {targets} target. Hit: {dmg}."
                        st.markdown(f"- {line}")

# ---------------- Performance Debug: Display Timings ----------------
if st.session_state.get("perf_debug", False):
    timings = get_perf_timings()
    placeholder = st.session_state.get("_perf_timing_placeholder")
    if placeholder and timings:
        with placeholder.container():
            for name, ms in sorted(timings.items(), key=lambda x: -x[1]):
                st.caption(f"⏱️ {name}: {ms:.2f} ms")

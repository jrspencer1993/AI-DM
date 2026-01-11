# Data and API Contracts

This document defines the canonical schemas used for both the UI and training data generation. These contracts ensure consistency between components.

## Monster Schema (Normalized)

All monsters, regardless of source format, are normalized to this structure:

```json
{
  "name": "Goblin",
  "ac": 15,
  "hp": 7,
  "max_hp": 7,
  "abilities": {
    "STR": 8,
    "DEX": 14,
    "CON": 10,
    "INT": 10,
    "WIS": 8,
    "CHA": 8
  },
  "skills": {
    "Stealth": 6
  },
  "senses": "Darkvision 60 ft., Passive Perception 9",
  "actions": [
    {
      "name": "Scimitar",
      "to_hit": 4,
      "damage": "1d6+2",
      "damage_type": "slashing"
    }
  ],
  "attacks": [
    {
      "name": "Scimitar",
      "to_hit": 4,
      "damage": "1d6+2",
      "damage_type": "slashing"
    }
  ]
}
```

## ACTION_SCHEMA (Canonical)

Every action in the system follows this schema for deterministic reasoning:

```json
{
  "name": "Longsword",
  "type": "attack",
  "action_type": "standard",
  "to_hit": 5,
  "dc": null,
  "save": null,
  "damage": "1d8+3",
  "damage_type": "slashing",
  "condition": null,
  "range": 5,
  "description": "A melee weapon attack with a longsword."
}
```

**Field Definitions:**
- `name`: Display name of the action
- `type`: One of `attack`, `save`, `utility`, `spell`
- `action_type`: One of `move`, `standard`, `quick`, `immediate`
- `to_hit`: Attack bonus (for attacks), or `null`
- `dc`: Difficulty class (for saves), or `null`
- `save`: Save type (`STR`, `DEX`, `CON`, `INT`, `WIS`, `CHA`), or `null`
- `damage`: Dice expression (e.g., `1d6+3`), or `null`
- `damage_type`: Damage type (e.g., `slashing`, `fire`), or `null`
- `condition`: Applied condition (e.g., `prone`, `stunned`), or `null`
- `range`: Range in feet, or `null`
- `description`: Human-readable description

## Session Export Schema (serialize_state)

The session export includes all state needed to restore a session:

```json
{
  "session_id": "20260111_143022",
  "timestamp": "2026-01-11T14:30:22",
  "chat_log": [
    ["Player", "I attack the goblin"],
    ["DM", "Roll your attack"]
  ],
  "world_log": "You stand in a dark cavern...",
  "party": [
    { "name": "Thorn", "ac": 16, "hp": 12, "...": "..." }
  ],
  "enemies": [
    { "name": "Goblin #1", "ac": 15, "hp": 7, "...": "..." }
  ],
  "difficulty": "Normal"
}
```

## Training Data Contracts

### monsters.normalized.json
Array of normalized monster objects.

### actions.normalized.jsonl
One action per line, with `monster_name` field added:
```json
{"monster_name": "Goblin", "name": "Scimitar", "type": "attack", "action_type": "standard", "to_hit": 4, "damage": "1d6+2", "damage_type": "slashing", "description": ""}
```

### rules.snapshot.json
```json
{
  "version": "0.4.0",
  "no_advantage_disadvantage": true,
  "flat_modifier_range": [-2, 2],
  "notes": "Hybrid rules: use flat modifiers instead of advantage/disadvantage"
}
```

### prompts_samples.jsonl
Instruction-style training samples:
```json
{"instruction": "Normalize this SRD monster into canonical schema", "input": {...}, "output": {...}}
```

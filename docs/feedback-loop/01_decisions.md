# Design Decisions Log

This document records key architectural and design decisions made during development. Each entry includes a date and short rationale.

## Decision Log

### 2026-01-11 — Documentation Separation
I keep documentation files (`/docs`) strictly separate from runtime code. These files must never be imported by Python modules. This ensures that documentation changes do not affect application behavior and that the codebase remains clean.

### 2026-01-11 — Normalized SRD Schema
I normalize all SRD data into a consistent schema for deterministic reasoning. Regardless of the source format (5e API style, text-based, or custom JSON), all monsters, actions, and entities are transformed into a canonical structure before use. This reduces edge cases and simplifies both UI logic and future training data generation.

### 2026-01-11 — No Advantage/Disadvantage (Hybrid Rules)
I avoid the standard 5e advantage/disadvantage mechanic entirely. Instead, I use flat modifiers (e.g., +2/-2) or DC-based adjustments. This decision aligns with the project's hybrid rules system and produces more predictable, deterministic outcomes suitable for training data.

### 2026-01-11 — Data-Driven Architecture
I treat the application as data-driven, storing SRD content, rules, and configurations in JSON files rather than hardcoding them. This approach supports rapid iteration, transparent data transformations, and consistent validation across the system.

### 2026-01-11 — JSONL Training Corpora
I generate training corpora as JSONL (JSON Lines) files for reproducible experiments. Each line represents a single training example with instruction, input, and output fields. This format is compatible with common fine-tuning pipelines and allows incremental dataset updates.

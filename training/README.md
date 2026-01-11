# Training Pipeline

This directory contains scripts for generating training corpora from SRD data.

## Purpose

I generate corpora from SRD content to support future training of language models on D&D 5e mechanics adapted to the project's hybrid rules. The outputs are structured for reproducibility and compatibility with common fine-tuning pipelines.

## Usage

Run the corpus builder from the project root:

```bash
python training/build_corpus.py
```

The script will:
1. Locate SRD monster data from `../data/SRD_Monsters.json` or `../data/SRD_Monsters.txt`
2. Normalize monsters into the canonical schema
3. Extract actions into ACTION_SCHEMA format
4. Generate training samples in JSONL format
5. Write all outputs to `/training/out/`

## Outputs

All generated files are written to `/training/out/`:

| File | Description |
|------|-------------|
| `monsters.normalized.json` | Full normalized monsters list |
| `actions.normalized.jsonl` | One action per line with `monster_name` field |
| `rules.snapshot.json` | Rules configuration including hybrid rules flags |
| `prompts_samples.jsonl` | Instruction-style samples for fine-tuning |

## Reproducibility

I can re-run `build_corpus.py` at any time to regenerate the same output files. The normalization logic mirrors what the UI uses, ensuring consistency between runtime behavior and training data.

## Hybrid Rules Note

The generated data reflects the project's hybrid rules: no advantage/disadvantage mechanics. Instead, flat modifiers (+2/-2) and DC-based adjustments are used throughout.

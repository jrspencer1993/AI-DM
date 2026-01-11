# Acceptance Testing Criteria

This document defines the acceptance checklist I use to validate the application after each development iteration.

## Acceptance Checklist

### Application Stability
- [ ] App boots with `streamlit run VirtualDM_UI_Prototype.py`
- [ ] No runtime errors on startup
- [ ] Main interface renders within acceptable time

### SRD Data Loading
- [ ] SRD loads (monsters) if present in `../data/`
- [ ] Monster names appear in the SRD dropdown
- [ ] Monster data includes normalized actions/attacks

### Combat Functionality
- [ ] I can add an SRD enemy and it has actions/attacks populated
- [ ] Combat can roll attacks and apply damage
- [ ] Initiative order is calculated and displayed correctly
- [ ] Turn progression works without errors

### Character Builder
- [ ] Character creation workflow completes without errors
- [ ] Race, class, background, and equipment apply correctly
- [ ] HP and AC are computed based on selections

### Export Functions
- [ ] Export functions produce valid JSON files without crashing
- [ ] Session JSON can be re-imported successfully
- [ ] JSONL exports (if present) contain valid JSON per line

### Training Pipeline
- [ ] Training script runs: `python training/build_corpus.py`
- [ ] Script generates output files in `/training/out/`
- [ ] Output files contain valid, parseable JSON/JSONL

### Hybrid Rules Compliance
- [ ] No references to "advantage" or "disadvantage" in mechanics
- [ ] Flat modifiers (+2/-2) or DC adjustments are used instead

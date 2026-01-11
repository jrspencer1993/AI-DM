# Cursor Prompts

This document contains reusable prompts I paste into Cursor to maintain consistency and control during development.

## Implementation Prompts

### Focused Implementation
```
Implement Step X exactly as described. Do not refactor unrelated code. Do not add features beyond the specification.
```

### File Change Summary
```
Show me a file list of what changed, including line counts added/removed.
```

### Minimal Validation
```
Run minimal linting and ensure all imports work. Report any syntax errors or missing dependencies.
```

### Mechanics Update
```
When you change mechanics, update the acceptance tests in /docs/feedback-loop/02_acceptance_tests.md to reflect the new behavior.
```

## Review Prompts

### Schema Compliance
```
Verify that all monster/action data conforms to the schemas defined in /docs/feedback-loop/03_data_contracts.md.
```

### Hybrid Rules Check
```
Search for any references to "advantage" or "disadvantage" and replace them with flat modifiers (+2/-2) or DC-based rules.
```

### Documentation Isolation
```
Confirm that no Python module imports anything from /docs. Documentation must remain separate from runtime code.
```

## Debugging Prompts

### Error Investigation
```
I received this error: [paste error]. Identify the root cause and propose a minimal fix.
```

### Performance Analysis
```
Review the profiler output and identify the top 3 sources of CPU usage. Suggest optimizations.
```

## Training Pipeline Prompts

### Corpus Generation
```
Run the training corpus builder and verify that all output files in /training/out/ contain valid JSON/JSONL.
```

### Sample Validation
```
Check that prompts_samples.jsonl contains well-formed instruction/input/output entries suitable for fine-tuning.
```

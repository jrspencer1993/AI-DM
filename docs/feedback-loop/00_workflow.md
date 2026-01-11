# Development Workflow

This document describes my iterative feedback loop between ChatGPT and Cursor for developing the Virtual DM application.

## Running the Application Locally

I run the application using Streamlit from the project root:

```bash
cd UI
streamlit run VirtualDM_UI_Prototype.py
```

The application launches in my default browser. I verify that the main interface loads without errors and that SRD data (monsters, races, classes, etc.) is accessible from the `../data/` directory.

## Verifying Acceptance Tests

After each implementation cycle, I manually verify the acceptance criteria defined in `02_acceptance_tests.md`. I check:

1. The app boots without runtime errors.
2. SRD monsters load and display correctly.
3. Combat mechanics function as expected.
4. Export functions produce valid JSON/JSONL.
5. Any new training scripts run and generate output files.

## Feedback to ChatGPT

When I encounter issues or need to iterate, I paste the following back into ChatGPT:

- **Diffs**: The specific code changes made by Cursor.
- **Errors**: Full stack traces or error messages from the terminal.
- **Screenshots**: Visual confirmation of UI state or unexpected behavior.
- **Profiler Output**: Results from `profiler_output.prof` when investigating performance.

## The Loop

1. I define the next step or feature requirement.
2. Cursor implements the change based on my prompt.
3. I run acceptance tests and observe behavior.
4. I capture any failures, errors, or unexpected results.
5. I paste findings back into ChatGPT and iterate until tests pass.

This loop ensures that each change is validated before moving to the next feature, maintaining system stability throughout development.

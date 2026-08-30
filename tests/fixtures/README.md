# Test Fixtures

Static test data used by the automated test suite.

- `sample_frame.png` — tiny (8×8) PNG used as a synthetic capture frame
  for end-to-end plumbing tests (image hashing, dedup, size math). Keep
  fixtures small so the repo stays cheap to clone.
- `prompt_packs/` — minimal sample packs used by `test_prompt_packs.py`
  to exercise the manifest validator.
  - `valid_minimal.json` — smallest pack that should load without errors.
  - `valid_full.json` — pack exercising every optional field (version,
    constraints, examples, spoiler defaults).
  - `invalid_bad_id.json` — has an `id` that violates the snake_case
    pattern; loader must log a warning and skip it.
  - `invalid_missing_fields.json` — omits required fields; loader must
    reject.

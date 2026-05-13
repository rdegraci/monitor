# CHECKLIST_MODEL_CONFIG_V2

## Goal
Track the work needed to formalize `src/monitor_oop/model_config_v2.json` as the canonical greenfield model configuration schema.

This tracker is intentionally separate from compaction and general rate-limiting implementation work.

## Scope
This tracker covers:
- documenting the schema shape
- validating model alias and provider mappings
- supporting explicit `provider_table/tier_key` references
- keeping the schema focused on model and TPM resolution
- ensuring the schema supports future Anthropic LiteLLM integration
- confirming the schema will support the rate-limiting policy inputs needed for TPM, optional RPM, completion headroom, and wait-vs-fail behavior
- confirming the schema will keep context/output capacity settings separate from rate-limit policy settings
- confirming context/output window values are used for compaction/headroom planning and remain separate from rate-limit policy
- confirming the first code slice still uses conservative runtime fallbacks for model limit values, while the full schema-backed loader remains future work

## Milestone 1: Schema definition
- [x] Define the schema as the canonical greenfield model config source.
- [x] Define the `provider_table/tier_key` tier-reference format.
- [x] Define the required top-level mapping groups.
- [x] Define the intended separation from prompt, compaction, logging, and history config.

## Milestone 2: Validation rules
- [ ] Define validation rules for required mappings.
- [ ] Define validation rules for unknown provider tables.
- [ ] Define validation rules for malformed tier references.
- [ ] Define validation rules for missing tier keys.
- [ ] Define validation rules for duplicate or conflicting aliases.
- [ ] Define validation rules for expected value types.

## Milestone 3: Loader behavior
- [x] Implement the loader for `model_config_v2.json`.
- [x] Implement provider resolution from `model_tpm_mapping`.
- [x] Implement model string resolution from `model_mapping`.
- [x] Implement tier resolution from `model_max_tpm`.
- [x] Implement provider-table lookup from the tier-reference string.
- [x] Implement clear error reporting for invalid schema entries.
- [x] Confirm first-run copy behavior seeds `model_config_v2.json` from the committed `src/monitor_oop/model_config_v2.json` when the user app config directory does not yet contain the file.
- [x] Confirm `model_config_v2.json` is loaded during bootstrap after first-run seeding and before any model or rate-limit resolution is used.
- [x] Confirm `ConfigService` applies the loaded model config into `RuntimeConfig`.
- [x] Confirm `RuntimeConfig` carries `model_alias`, `provider`, `full_model_name`, `tokens_per_minute`, and `requests_per_minute`.

## Milestone 4: Verification
- [ ] Add tests for valid schema loading.
- [ ] Add tests for malformed tier references.
- [ ] Add tests for missing provider tables.
- [ ] Add tests for missing tier keys.
- [ ] Add tests for duplicate aliases or conflicting entries.
- [ ] Add tests confirming the schema remains isolated from compaction and prompt config.

## Notes
- Keep the schema explicit and easy to validate.
- Prefer deterministic resolution over heuristics.
- Avoid mixing unrelated config concerns into this file.
- The schema should remain compatible with future provider additions.

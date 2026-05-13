# PLAN_MODEL_CONFIG_V2

## Goal
Define the canonical greenfield model configuration schema for `monitor_oop`.

`src/monitor_oop/model_config_v2.json` is the intended source of truth for model aliases, provider resolution, context windows, output windows, history budgets, and rate-limit tier references in the new application. The schema should remain explicit so the loader and runtime can resolve model behavior without embedding provider logic in adapters.

## Purpose
This file is the schema design reference for the new configuration format. It exists to make the loader, validator, and rate-limit resolver unambiguous as part of the current bootstrap/runtime integration.

## Core Responsibilities
The schema should define:
- model alias to provider mapping
- model alias to full provider/model string mapping
- conversation-history budget per model alias
- context window per model alias
- output window per model alias
- model-to-tier reference for TPM resolution
- provider-specific TPM tier tables

## Startup Order Note
This model config file is seeded or copy-created before model resolution is used, and it participates in the same bootstrap phase as the other user-config files.

## Canonical Tier Reference Format
The recommended tier-reference format is:
- `provider_table/tier_key`

Meaning:
- `provider_table` selects the provider tier table, such as `openai_model_tpm_tier` or `xai_model_tpm_tier`
- `tier_key` selects the exact tier entry inside that table
- the resolver uses the pair to produce the effective TPM value

This explicit form is preferred because it keeps the schema deterministic and easy to validate.

## Expected Top-Level Shape
The greenfield schema should contain the following top-level maps:
- `model_tpm_mapping`
- `model_mapping`
- `conversation_history_mapping`
- `context_window_mapping`
- `output_window_mapping`
- `model_max_tpm`
- `openai_model_tpm_tier`
- `anthropic_model_tpm_tier`
- `xai_model_tpm_tier`
- `google_model_tpm_tier`

Additional provider tables may be added later if more providers are introduced.

## Recommended Resolution Flow
A loader should resolve configuration in this order:
1. Read the model alias.
2. Resolve the provider from `model_tpm_mapping`.
3. Resolve the fully qualified provider/model string from `model_mapping`.
4. Resolve the tier reference from `model_max_tpm`.
5. Split the tier reference into provider table and tier key.
6. Resolve the final TPM ceiling from the selected provider table.

## Validation Expectations
The eventual loader should validate that:
- every model alias is present in each required map
- provider-table references exist and are well formed
- every `tier_key` exists in the referenced provider table
- values have the expected types
- duplicate model aliases are rejected
- unknown provider tables are rejected
- missing required mappings are reported clearly

## Separation From Other Config Domains
This schema should stay focused on model and rate-limit resolution.
It should not absorb unrelated concerns such as:
- compaction policy
- prompt persistence
- conversation history storage paths
- logging configuration
- UI state
- rate-limiting policy inputs needed for TPM enforcement
- optional RPM support
- completion headroom configuration
- wait-vs-fail behavior

`context_window_mapping` and `output_window_mapping` are part of model capacity configuration, not usage-rate policy, and the schema should keep those concerns separate from TPM/RPM settings. Context windows can also trigger compaction decisions, and output windows can influence headroom planning, but both remain model-capacity inputs separate from rate-limit policy.

## Notes
- Treat this schema as the contract for future config loading in `monitor_oop`.
- Keep the tier reference explicit rather than inferring provider tables from model names.
- Prefer validation errors that point directly to the problematic key.
- This schema should support the upcoming Anthropic LiteLLM adapter without special-casing it in transport code.
- The committed `src/monitor_oop/model_config_v2.json` is the packaged source copied into the user app config directory on first run if the user copy does not exist.
- `ConfigService` now loads and applies `model_config_v2.json` during bootstrap, and `RuntimeConfig` carries the resolved model fields used by the running application.
- Remaining work is limited to validation refinement, error reporting polish, and any schema tightening needed as additional provider tables are introduced.
- The first code slice still uses conservative runtime fallbacks for model limit values while the full `model_config_v2.json`-backed schema loader remains future work.

# CHECKLIST_IMPROVED_C

- [x] Confirmed the authoritative location for the `C:` calculation is `conversation.py`; the display layer is unchanged.
- [x] Identified the structured tool/session indicators used to trigger the safety margin.
- [x] Defined conservative safety-margin values in `conversation.py`.
- [x] Kept the margin application in the conversation layer; the display layer is unchanged.
- [x] Preserved current token usage tracking.
- [ ] Add or update tests for the revised `C:` behavior.
- [x] Verified the prompt/status line still renders correctly for normal chat.
- [x] Verified the prompt/status line remains conservative in agent/tool-heavy sessions.

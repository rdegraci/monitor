# CLIENT_SERVER_PROTOCOL.md

# EXPERIMENTAL - WIP

## Overview

This protocol enables a secure client-server workflow for operations involving file data, where:
- The client maintains exclusive access to its local filesystem.
- The server (often an LLM-backed system) never directly accesses client files.
- All file content is explicitly provided by the client, ensuring privacy and user control.

## Protocol Outline

### 1. Metadata Request (Client → Server)
The client initiates a transaction by sending metadata about the intended operation and (optionally) the target file. No file contents are sent yet.

**Example:**
```json
{
    "command": "examine",
    "file_name": "foo.py",
    "file_size": 2048,
    "file_type": "text/x-python",
    "request_modification": false
}
```

### 2. Server Readiness/Instructions (Server → Client)
The server responds with readiness status or instructions. This may include accepted file sizes, encoding, specific instructions for upload, or refusal if not supported.

**Example:**
```json
{
    "status": "ready_for_data",
    "instructions": "Send contents as UTF-8 text.",
    "session_id": "abc123"
}
```

### 3. Data Transfer (Client → Server)
The client transmits the actual payload as agreed, including any required session or transaction ID.

**Example:**
```json
{
    "session_id": "abc123",
    "file_content": "<file contents here>",
    "encoding": "utf-8"
}
```

### 4. Server Processing & Response (Server → Client)
The server analyzes/processes the data. Response can include a modified file (if requested/appropriate), analysis results, error messages, etc.

- **If server returns modified data:**
    - The client writes/saves it to disk as appropriate.
- **If server returns only analysis/summary text:**
    - The client displays this to the user.

**Modified file example:**
```json
{
    "modified_file_content": "<new contents>",
    "message": "File refactored successfully."
}
```

**Analysis/summary example:**
```json
{
    "result": "No issues found.",
    "message": "Analysis complete."
}
```


## Extension Ideas
- **Session/transaction IDs** for multi-stage, resumable, or chunked uploads.
- **Capabilities negotiation** in the metadata phase (e.g., which operations are supported).
- **Chunked data transfer** for very large files.
- **Rich server replies** (suggested filenames, diffs, supplementary artifacts, etc.).

## Security Considerations
- The server never accesses or enumerates the client's filesystem.
- File data is only transferred when explicitly sent by the client.
- Consider transport encryption (HTTPS) and, if needed, authentication and checksumming.

## Summary Table

| Step               | Direction         | Payload                       | Purpose                                  |
|--------------------|------------------|-------------------------------|------------------------------------------|
| Metadata           | Client → Server  | Command, file info, request   | Initiate transaction                     |
| Readiness/Instr    | Server → Client  | Status, instructions, session | Confirm readiness and specify protocol   |
| Data Transfer      | Client → Server  | File contents                 | Send file data if requested              |
| Processing Result  | Server → Client  | Result and/or new file        | Deliver output for user action           |

## Example Flow Diagram

```
Client                  Server
  | --- metadata -------> |
  | <--- ready/instruct -|
  | --- file data ------>|
  | <--- result/data ----|
  (save/print as needed)
```

---

This protocol ensures secure, controllable operations on client files with no risk of remote server file snooping. It is extensible for future needs such as chunking, authentication, and resumability.

## Advanced Extension: Tool/Function-Call Pattern (LLM Tool-Calling Style)

As an optional advanced protocol variant, the server, after receiving client metadata, may send structured tool or function call requests to the client. This pattern enables more dynamic and extensible workflows, inspired by LLM tool/function-calling and agentic paradigms.

### Workflow

1. **Initiation**: Client sends metadata, as in the basic protocol.
2. **Server Tool/Function Call**: Instead of (or in addition to) simple readiness instructions, the server may request the client to run one or more defined tools/functions (e.g., read_file, compute_hash, list_directory, etc.) by sending a structured call message.
3. **Client Execution**: The client executes only those tool/function calls it supports and is authorized for, performs the requested operation, and returns the result in a structured response.
4. **Iteration**: This process may repeat with additional tool/function calls, or the protocol returns to data transfer, summary, or modification steps as per the negotiated workflow.

### Benefits

- **Extensibility**: New tool/functions can be added by updating client and server capabilities, without changing the core protocol.
- **Rich Interactions**: The server can orchestrate complex multi-step workflows (e.g., compute checksums before upload, validate content, interactively select files or parameters).
- **Client Control & Security**: The client decides which functions to expose and executes only whitelisted, sandboxed operations, preserving file system privacy and safety.

### Example Tool-Call Message

**Tool/function call request (Server → Client):**
```json
{
    "tool_call": {
        "name": "compute_hash",
        "arguments": {
            "algorithm": "sha256",
            "file_name": "foo.py"
        },
        "call_id": "tool-1"
    }
}
```

**Tool/function call response (Client → Server):**
```json
{
    "tool_response": {
        "call_id": "tool-1",
        "name": "compute_hash",
        "result": {
            "algorithm": "sha256",
            "digest": "baf324bb819255b..."
        }
    }
}
```

### Security Implications

- **No Arbitrary Code Execution**: The client must never execute arbitrary or unsafe server code—only named, approved tool/functions implemented locally.
- **Function Whitelisting**: Tools/functions must be explicitly whitelisted, and the client may refuse requests beyond its policy.
- **Auditability**: All tool calls and responses can be logged for audit trails.
- **Same Privacy Guarantees**: At no time does the server gain access beyond the functions intentionally exposed by the client. File enumeration or access still requires explicit client-side action.

### When to Use

This advanced extension is suited for scenarios requiring richer, interactive workflows, greater flexibility, or when the client and server can agree on a suite of helper functions to facilitate secure, controlled automation.



---
This protocol ensures secure, controllable operations on client files with no risk of remote server file snooping. It is extensible for future needs such as chunking, authentication, resumability, and advanced agentic patterns.

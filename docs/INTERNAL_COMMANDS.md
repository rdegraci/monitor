# Internal Commands: llm< and directive<

This document describes two internal REPL commands available in Monitor that help combine local environment data with LLM reasoning: `llm<` and `directive<`.

For context on how to author and store directive files, see docs/DIRECTIVES.md (it explains the directives directory and an example directive).

---

## llm< — run shell code, send output to the LLM

Purpose

- `llm<` executes local shell code (non-interactively), captures stdout, and sends the captured text (or a user-supplied prompt that references it) to Monitor's LLM pipeline.
- Useful for immediate, ad-hoc workflows that combine local diagnostics or file content with LLM analysis.

Syntax

- Basic: llm< "<shell_code>"
- With a user prompt: llm< "<shell_code>" >llm "<user_prompt>"
- With placeholder: llm< "<shell_code>" >llm "<instruction using ${result} to refer to stdout>"

Notes on quoting

- Wrap the shell_code in quotes if it contains spaces, pipes, or characters that the shell might interpret.
- When passing >llm with a prompt containing spaces or special chars, quote it as well.

Execution behavior

1. Monitor parses the command. If the literal `>llm` token is present the command is split into `shell_code` and `user_prompt`. Otherwise the whole remainder is treated as `shell_code`.
2. `shell_code` is executed with run_subprocess in a non-interactive shell; stdout, stderr and exit_code are captured.
3. If the exit code indicates failure, `llm<` surfaces stderr and logs an error. The LLM call may be skipped depending on error handling.
4. If there is a user_prompt and it contains `${result}`, that placeholder is replaced with stdout. If there is a user_prompt without `${result}`, Monitor concatenates the prompt and stdout.
5. The assembled input is passed to `query(...)` (the canonical LLM entrypoint) and output is shown via the usual display pipeline.

Security and safety

- `llm<` executes code on your machine. Do not run untrusted shell commands.
- The shell output is sent to the LLM provider (may be an external service). Do not send secrets or private data.
- Prefer using small, targeted commands (head/sed) to limit tokens and cost.

Best practices

- Use `${result}` in your prompt to make intent explicit.
- Limit output size using head/sed/cut when necessary.
- Request structured output (JSON) for machine parsing when appropriate.
- Use explicit roles and clear instructions (e.g., "You are a senior engineer... return JSON list of issues...").

Examples

1) Quick system diagnostic + recommendation

    llm< "df -h; free -m" >llm "Given the disk and memory stats below (${result}), recommend steps to free disk space and tune memory for a small service. Return a short checklist."

2) Review last commit diff

    llm< "git diff HEAD~1..HEAD" >llm "Analyze this diff (${result}). List top 3 potential correctness issues and suggested fixes in bullets."

3) Explain a function from a file (only lines 100–160)

    llm< "sed -n '100,160p' src/monitor/core/commands.py" >llm "Explain the purpose of this code segment and list edge cases. Use ${result} to refer to the code excerpt."

Troubleshooting

- If the command produces no stdout, you’ll get an empty input to the LLM; check the executed shell command.
- If the shell command fails, inspect the error in stderr which is surfaced by Monitor.
- If output is too large for your chosen model, trim it or summarize before sending.

---

## directive< — load a file from the directives directory and send it to the LLM

Purpose

- `directive<` is a lighter-weight internal command for sending the contents of a file from your configured `DIRECTIVES_DIR` to the LLM, along with up to five parameter lines.
- It is suitable for ad-hoc prompt reuse where you keep prompt templates as text files.

Syntax

    directive< <file_name> <param1> <param2> <param3> <param4> <param5>

Behavior

- The command prints up to five parameter lines in the form `paramN=value` followed by the entire contents of the requested file.
- The combined text is then internalized and sent to Monitor’s LLM pipeline.
- There is no client-side variable substitution; the LLM sees the parameter lines and the file text and is expected to interpret the parameters.

Security and safety

- Files in `DIRECTIVES_DIR` are read and their contents are sent to the LLM. Do not store secrets in directive files.
- Validate and control permissions of the directives directory.

Example: simple greeting directive (two parameters)

1) Save the following file as `greet_directive.txt` in your directives directory (for example `~/.config/monitor/directives/greet_directive.txt`):

    # greet_directive.txt

    You are an assistant that produces a friendly business greeting. Use the parameters provided above (param1 and param2) to customize the result.

    - param1: recipient name
    - param2: company or organization name

    Instructions:
    1) Greet the person using param1.
    2) Mention param2 as the organization and offer a helpful one-sentence suggestion relevant to a business contact.
    3) Provide the output as a short, professional message.

2) Run it in the Monitor REPL

    directive< greet_directive.txt Alice "Acme Corp"

Monitor internally sends the following to the LLM:

    param1=Alice
    param2=Acme Corp
    <contents of greet_directive.txt>

The LLM’s response is shown via Monitor’s display pipeline and logged to the conversation logs.

When to prefer directive< vs. llm<

- Use `llm<` when you need to capture dynamic local output (command results, file snippets, diagnostics) and combine it with a specific LLM instruction.
- Use `directive<` when you have a reusable plain-text prompt/template saved in the directives directory that you want to re-run with simple parameter bindings.

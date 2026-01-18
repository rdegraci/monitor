# Using directive< in Monitor

This document describes the built-in interactive internal command `directive<` and how to use it to load and send directive files (prompt templates or instruction files) to the LLM from the directives directory.

Location

- Default directives directory is configured via the `DIRECTIVES_DIR` setting in your `config.yaml` and loaded into `config.DIRECTIVES_DIR` at runtime.
  - Example default (packaged): `~/.config/monitor/directives` or `~/Library/Application Support/monitor/directives` depending on OS.
- Place your directive files (plain text files) in that directory (or a subdirectory) so the `directive<` command can find them.

What `directive<` does

- `directive< <file_name> <param1> <param2> <param3> <param4> <param5>` is an internal REPL command.
- It reads the requested file from the configured directives directory and prints up to five `paramN=value` lines followed by the file contents.
- The combined textual output (parameter lines + file content) is then internalized and sent to Monitor's internal LLM pipeline (equivalent to the user pasting that text into the REPL and sending it to the LLM).
- The command is implemented as an "internal" command and the result returned by the LLM is displayed using the Monitor display pipeline.

Usage notes

- Up to five parameters are supported. If you pass fewer, the missing param lines will be blank.
- Note: Monitor will still emit up to five `paramN=` lines; any unused parameters will be emitted as empty assignments (for example `param3=`).
- The directive file is treated as plain text. The LLM will see the parameter lines followed by the file text and should interpret the parameters accordingly.
- The command does not perform client-side variable substitution. If you rely on parameter substitution, include clear markers or ask the LLM to treat the preceding `paramN` lines as variables.

Security and safety

- Files in the directives directory are read and their entire contents are sent to the LLM. Do NOT store secrets (API keys, passwords, private data) in those files.
- Only place directives you trust into the configured `DIRECTIVES_DIR` and ensure directory permissions are appropriate for your environment.
- Where possible prefer structured DSPy-style directives (see project docs) for safer, auditable pipelines. `directive<` is useful for ad-hoc prompts but is not a secure execution environment.

What happens

- The `directive<` internal command prints the parameter lines:

    param1=Alice
    param2=Acme Corp

  followed by the full contents of `greet_directive.txt`.

- The combined text is presented to the LLM. The LLM should read the param lines as variable bindings and generate an output that uses them.

- Monitor then shows the LLM's reply via the usual display pipeline and logs the input and result to the conversation log.

- If the directive file cannot be read (for example due to missing file or permission errors), Monitor will surface the underlying stderr message and skip sending the directive to the LLM.

Example: create and use a directive that accepts two parameters

1) Create a directive file

Save the following file as `greet_directive.txt` inside your Monitor directives directory (for example: `~/Library/Application Support/monitor/directives/greet_directive.txt`):

"""
# greet_directive.txt

You are an assistant that produces a friendly business greeting. Use the parameters provided above (param1 and param2) to customize the result.

- param1: recipient name
- param2: company or organization name

Instructions:
1) Greet the person using param1.
2) Mention param2 as the organization and offer a helpful one-sentence suggestion relevant to a business contact.
3) Provide the output as a short, professional message.

Example expected output:
"Hello Alice, great to connect with you at Acme Corp. I recommend we schedule a 15-minute call to review next steps."
"""

2) Invoke it in the Monitor REPL

From the interactive Monitor prompt, run:

    directive< greet_directive.txt Alice "Acme Corp"

(You can pass the company name in quotes if it contains spaces.)

Tips for authoring directives

- Include a short header describing expected parameters and the required output shape. The LLM will benefit from explicit instructions.
- Keep directives concise; large directives will increase token usage and cost.

Implementation

- Contributors looking for the authoritative implementation should consult src/monitor/core/commands.py and the INTERNAL_COMMANDS entry for the `directive<` internal command.

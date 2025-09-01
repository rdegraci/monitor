# Getting Started: Becoming a Productive Programmer with Monitor

Welcome! 🎉 You’ve installed Monitor and can see the `Monitor ready!` prompt. This guide gives concise, practical tips for using Monitor to supercharge your development workflow—even if you’re new to this kind of tool.

## 1. What is Monitor?

Monitor is an AI-powered command-line assistant that understands both natural language and commands. It can:
- Execute shell and file commands.
- Help with code summaries, reviews, and suggestions.
- Manage your workflow with macros and automations.
- Integrate with version control (git), databases, and more.
- Remember your preferences and session context.

---

## 2. Your First Steps

When you see:
```
Monitor ready!
>
```
You’re ready to go. Try these right now:

### Shell Commands

Type regular shell commands, for example:
```sh
ls
cd ..
cat README.md
```

### Natural Language

Ask Monitor using plain language:
```
Summarize this Python file: core/conversation.py
```
or
```
How can I add a new built-in command?
```

---

## 3. Built-ins: Exact Names Matter

Built-in command names are exact. Some built-ins are registered without a leading colon (for example `commands`, `history`, `macros`), while others include a leading colon in their registered name (for example `:llm`, `:reasoning`). To see the exact list and exact registered names, run the built-in:
```
commands
```

Common built-ins (use the exact registered name shown by `commands`):
| Command           | What it does                                   |
|-------------------|------------------------------------------------|
| `commands`        | List all available built-in commands           |
| `history`         | Browse your conversation and command history   |
| `preferences`     | View/edit preferences (like your LLM model)    |
| `reset_history`   | Reset chat history for a new session           |
| `twitch_summary`  | Send a summary to Twitch (demo or real)        |
| `;;;`             | Separate multiple commands in one line         |

Note about help: there is no global `help` command. Some built-ins accept `help` as an argument. For example:
```
:llm help
:reasoning help
```
Run the built-in with `help` to see usage for that specific tool.

Try this multi-command:
```
pwd ;;; ls ;;; history
```

---

## 4. Macros: Act Faster, Write Less

Macros are shortcuts for commands, paths, or frequently used snippets.

Define a macro:
```
<proj=~/projects/monitor
```

Macro syntax and expansion:
- Define with `<key=value`.
- Macro delimiters default to `(` and `)` for expansion.
- Use a macro with the delimiters: for example:
```
cd (proj)
```

List current macros with:
```
macros
```

---

## 5. Get AI Help

Ask Monitor directly for code advice, summaries, or reviews. Be concise and paste code or a filename for context.

Examples:
- "Summarize what this function does: (paste the code or filename)"
- "Suggest a better variable name for `x` in this code."
- "What changed in my last git commit?"

Monitor uses context from open files, history, and your current session to provide targeted help.

---

## 6. Search and Version Control

Monitor connects to powerful tools:

- Git:
  - Run `git status`, `git diff`, or ask natural language questions like:
    ```
    Show the difference between my latest two commits
    ```
- Search:
  - Use `:rg <pattern>` for fast code search (faster than plain `grep` in many setups).
- Logs and History:
  - Application logs are stored at `~/.config/monitor/logs/` by default.
  - You can change log and other configuration settings in `~/.config/monitor/app.yaml`.

---

## 7. Power Features

- Voice Input: Press `F10` to try voice-to-text if your setup supports it. Note: availability depends on your OS and local configuration.
- Edit Code On-the-Fly: Ask "Refactor this function for readability." Paste the code, and Monitor will suggest improvements.
- Summarization: Long chats or files can be auto-summarized to keep context concise.
- Memory: Monitor can remember facts, preferences, and conversation history between sessions (if persistence like Redis or file-based storage is enabled and configured).

---

## 8. Extending Monitor

Create new commands and tools by adding Python modules:

- Built-in commands are implemented under:
  ```
  src/monitor/core/built_ins.py
  ```
  Add or modify built-in handlers there.
- Tools and integrations can be added under:
  ```
  lib/
  ```
  Place reusable helpers and modules in `lib/`.

Follow the existing patterns for argument parsing and help text. Test new built-ins locally and list them with `commands` to confirm their registered names.

---

## 9. Getting Help

- Need a list of built-ins? Run:
```
commands
```
- Want to see macros? Run:
```
macros
```
- Help for a specific built-in (if supported):
```
:llm help
:reasoning help
```
- Configuration and logs:
  - Logs: `~/.config/monitor/logs/`
  - Configuration file: `~/.config/monitor/app.yaml`
- Issues: Check logs for errors or reach out at support@monitorcli.com.

---

## 10. Cheat Sheet

| Action                      | Example                         |
|-----------------------------|---------------------------------|
| Run shell command           | `ls`, `cd project`              |
| Ask a question              | `How do I use macros?`          |
| Define a macro              | `<src=~/myproject/src`          |
| Use a macro                 | `cd (src)`                      |
| Run multiple commands       | `ls ;;; pwd ;;; history`        |
| Show history                | `history`                       |
| Change preferences          | `preferences`                   |
| Reset chat/history          | `reset_history`                 |

---

You're ready to use Monitor to code, automate, and discover smarter ways to work, all from a powerful AI-enhanced command line. 🚀

If you want hands-on walkthroughs, tips for specific programming languages, or macro ideas, ask Monitor or consult the full docs: `README.md` and `ARCHITECTURE.md`.

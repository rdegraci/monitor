# Getting Started: Becoming a Productive Programmer with Monitor

Welcome! 🎉 You’ve installed Monitor and can see the `Monitor ready!` prompt. This guide gives you practical tips for using Monitor to supercharge your development workflow—even if you’re new to this kind of tool.

## 1. What is Monitor?

Monitor is an AI-powered command-line assistant that understands both natural language and commands. It can:
- Execute shell/file commands.
- Help you with code summaries, reviews, and suggestions.
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
You’re ready to go! Try these right now:

### Shell Commands

Just type regular commands, like:
```sh
ls
cd ..
cat README.md
```

### Natural Language

You can say things like:
```
Summarize this Python file: core/conversation.py
```
or  
```
How can I add a new built-in command?
```

---

## 3. Boost Productivity with Built-ins

Monitor comes with a library of shortcuts and tools (called “built-ins”). Some essentials:

| Command             | What it does                                   |
|---------------------|------------------------------------------------|
| `:commands`         | List all available built-in commands           |
| `:history`          | Browse your conversation and command history   |
| `:preferences`      | View/edit preferences (like your LLM model)    |
| `:reset_history`    | Reset chat history for a new session           |
| `:twitch_summary`   | Send a summary to Twitch (demo or real account)|
| `;;;`               | Separate multiple commands in one line         |

**Try this multi-command:**  
```
pwd ;;; ls ;;; :history
```

---

## 4. Macros: Act Faster, Write Less

Think of macros as shortcuts for commands or paths you use often.

**Define a macro:**
```
<proj=~/projects/monitor
```

**Use it:**
```
cd (proj)
```
Macros make repetitive tasks much quicker. You can see current macros with the command:
```
macros
```

---

## 5. Get AI Help

Ask Monitor directly for code advice, summaries, or reviews:

- "Summarize what this function does: (paste the code or filename)"
- "Suggest a better variable name for `x` in this code."
- "What changed in my last git commit?"

Monitor will use context from your current files, history, and even your questions.

---

## 6. Search and Version Control

Monitor connects to powerful tools:

- **Git:**  
  Run `git status`, `git diff`, or ask:  
  ```
  Show the difference between my latest two commits
  ```
- **Search:**  
  Use `:rg <pattern>` for code search (faster than `grep`).
- **History and Logs:**  
  Use `:history` to scroll back through conversation, or check the `logs/` folder for detailed logs.

---

## 7. Power Features

- **Voice Input:** Press `F10` to try voice-to-text (if your setup supports it).
- **Edit Code On-the-Fly:**  
  "Refactor this function for readability." Paste code, and Monitor suggests improvements.
- **Summarization:** Long chats or files? Monitor auto-summarizes so you don't lose focus.
- **Memory:** Monitor remembers facts, your preferences, and conversation history between sessions (if Redis is enabled).

---

## 8. Extending Monitor

You can create new commands and tools by adding Python modules in `lib/` or `core/`. Advanced users can write new macros, built-in commands, or even connect to external APIs.

---

## 9. Getting Help

- **Need a list?** Type `:commands` or `help`
- **Want to see macros?** Type `macros`
- **More details?** See the full documentation: `README.md` or `ARCHITECTURE.md`
- **Issues?** Check `logs/` for errors or reach out at support@monitorcli.com.

---

## 10. Cheat Sheet

| Action                      | Example                         |
|-----------------------------|---------------------------------|
| Run shell command           | ls, cd project                  |
| Ask a question              | How do I use macros?            |
| Define a macro              | <src=~/myproject/src            |
| Use a macro                 | cd (src)                        |
| Run multiple commands       | ls ;;; pwd ;;; git status       |
| Show history                | :history                        |
| Change preferences          | :preferences                    |
| Reset chat/history          | :reset_history                  |

---

Congratulations—you’re ready to use Monitor to code, automate, and discover smarter ways to work, all from a powerful AI-enhanced command-line! 🚀

If you want more hands-on examples or have a specific workflow in mind, just ask Monitor or check the full docs.

---

Let me know if you want hands-on walkthroughs, tips for specific programming languages, or macro ideas!

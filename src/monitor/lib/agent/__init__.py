"""Agent subcommand handlers — :agent subcommand multiplexer split across files.

Each subcommand of :agent (list, logs, logfile, attach, kill, send, spawn)
lives in its own module here. The dispatcher (``dispatcher.dispatch``)
parses the user's argument string into tokens and routes to the right
handler. Shared state (the lazy ScreenHandler proxy and the index
resolver) lives in monitor.lib.terminal_commands and is imported from
there — keeping it in one place lets existing tests that monkeypatch
``terminal_commands._SCREEN_HANDLER`` continue to work.

This package replaces a previous monolithic ~740-line
``run_command_in_screen`` function in monitor.lib.terminal_commands.
That function now thin-delegates to ``dispatcher.dispatch``.

Layout:

    dispatcher.py   Routing logic (parses tokens, calls handler).
    usage.py        Help text + agent_usage().
    list.py         agent_list(tokens) — table of active sessions.
    logs.py         agent_logs(tokens) — tail recent log.
    logfile.py      agent_logfile(tokens) — print logfile path.
    attach.py       agent_attach(tokens) — re-attach via screen -r.
    kill.py         agent_kill(tokens) — kill session + orchestrator cleanup.
    send.py         agent_send(tokens) — send text into a session.
    spawn.py        agent_spawn(command) — fallthrough new-session creator.
"""

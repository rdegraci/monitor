import logging

from monitor.lib.display_output import display_query_result
from monitor.lib.consult import Consult
from monitor.lib.external_services import send_artifact
from monitor.lib.colors import red, yellow, blue, reset 

logger = logging.getLogger(__name__)

DESIGN_CONSULT=None

def configure_consultant():
    from monitor import config 

    global DESIGN_CONSULT
    DESIGN_CONSULT = Consult(
        logger=logger, 
        model=config.MODEL
    )

DESIGN_MODE_ACTIVE = False

def print_design_mode_help():
    print(f"""{blue}Design Mode Commands:{reset}
  {yellow}:help{reset}      - Show this help message
  {yellow}:exit{reset}      - Exit design mode without entering dev mode
  {yellow}:end{reset}       - Also exits design mode without entering dev mode
  {yellow}:dev_mode{reset}  - Finalize and execute the design, switching to dev mode
  {yellow}<anything else>{reset} - Send as a question or design input
""")

def design_mode_command(seed_question=None):
    from monitor.core.conversation import query

    global DESIGN_MODE_ACTIVE
    if DESIGN_MODE_ACTIVE:
        print("Design mode already active.")
        return
    DESIGN_CONSULT.start(seed_question=seed_question)
    DESIGN_MODE_ACTIVE = True
    logger.info("Design mode activated.")
    print("Design mode activated. Begin describing your software or respond to questions.")
    print_design_mode_help()
    while DESIGN_MODE_ACTIVE:
        try:
            user_entry = input("[design]> ")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting design mode...")
            DESIGN_MODE_ACTIVE = False
            break
        uentry = user_entry.strip().lower()
        if uentry in [":exit", ":end", "exit", "end"]:
            print("Exiting design mode without entering dev mode.")  # or whatever you want
            DESIGN_MODE_ACTIVE = False
            break
        if uentry == ":dev_mode":
            dev_mode_command()
            # dev_mode will already finalize and display and execute
            break
        if uentry == ":help":
            print_design_mode_help()
            continue
        question, prompt = DESIGN_CONSULT.ask(user_entry)
        print(f"\n{yellow}Clarify: {question}{reset}\n")
    logger.info("Design mode ended.")
    print("Design mode ended.")

def dev_mode_command():
    """Stop the design interaction and hand over requirements for execution."""
    from monitor.core.conversation import query

    global DESIGN_MODE_ACTIVE
    if not DESIGN_MODE_ACTIVE:
        print("Not currently in design mode.")
        return
    prompt = DESIGN_CONSULT.stop()
    DESIGN_MODE_ACTIVE = False
    print(f"\n{yellow}Finalized design prompt for dev mode:{reset}\n")
    print(prompt)
    logger.info("Switching to development mode")
    print(f"\n{yellow}Switching to development mode. Executing design prompt...{reset}\n")
    # Execute or use the prompt as user input for further code actions
    # This just calls main query/display logic as in normal mode

    query_result = query(prompt)
    display_query_result(
        query_result, 
        update_history_count=lambda: setattr(
            monitor.core.conversation, 
            'TOTAL_CONVERSATION_HISTORY_COUNT', 
            monitor.core.conversation.TOTAL_CONVERSATION_HISTORY_COUNT + 2  # Ensure we update the global in module scope
        )
    )
    send_artifact(query_result)

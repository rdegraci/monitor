
from colored import fg, attr

# Terminal text formatting for colored output
blue = fg('blue')
green = fg('green')
magenta = fg('magenta')
red = fg('red')
yellow = fg('yellow')
reset = attr('reset')

COLOR_WARNING_FUNCS = {'red': red, 'yellow': yellow, 'reset': reset}

def print_colored(message, color):
    """Prints a message to the terminal using the specified color.

    Args:
        message (str): The message to print.
        color (str): The colored terminal code to use for the message.
    """
    print(f"{color}{message}{reset}")

def print_red(message):
    """Prints a message to the terminal in red.

    Args:
        message (str): The message to print.
    """
    print_colored(message, red)

def print_blue(message):
    """Prints a message to the terminal in blue.

    Args:
        message (str): The message to print.
    """
    print_colored(message, blue)

def print_yellow(message):
    """Prints a message to the terminal in yellow.

    Args:
        message (str): The message to print.
    """
    print_colored(message, yellow)

def print_green(message):
    """Prints a message to the terminal in green.

    Args:
        message (str): The message to print.
    """
    print_colored(message, green)

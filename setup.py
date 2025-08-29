"""Minimal shim setup.py

This file is a compatibility shim. It intentionally does not perform packaging
or installation. The project uses pyproject.toml as the authoritative build
configuration. Tools and users should consult pyproject.toml and use modern
PEP 517/518 workflows.

This shim defines a main() function that exits with a clear message
instructing how to proceed.
"""

def main():
    """Display usage instructions and exit.

    This function is intended to be invoked when setup.py is executed directly
    (for example, python setup.py ...). Instead of supporting legacy setup.py
    behavior, it terminates with guidance for modern packaging workflows.

    Raises:
        SystemExit: Always raised to stop execution and display the message.
    """
    raise SystemExit(
        "\n"
        "This project uses pyproject.toml as the authoritative build configuration.\n"
        "Do not use setup.py for building or installing. Instead, use one of the\n"
        "following modern commands:\n\n"
        "  - Build a wheel and source distribution (requires the 'build' package):\n"
        "      python -m pip install --upgrade build\n"
        "      python -m build\n\n"
        "  - Install the package in editable mode using pip (PEP 660 editable support):\n"
        "      python -m pip install --upgrade pip\n"
        "      python -m pip install -e .\n\n"
        "  - Install the package for runtime without building a wheel:\n"
        "      python -m pip install .\n\n"
        "If a tool is invoking setup.py directly, update the tooling to use PEP 517\n"
        "interfaces (pip, build, or the underlying build-backend) that read\n"
        "pyproject.toml. For CI or automation, prefer 'python -m build' or 'pip\n"
        "install' commands shown above.\n"
    )

if __name__ == "__main__":
    main()

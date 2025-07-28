# monitor

Simple hello world pip project.

## Usage

Install (from the parent directory):
    pip install .

Run:
    monitor

## Local Development & Testing

For developing and testing the CLI app without installing via pip, you can use the following approaches:

1. **Run as a module from the project directory:**

   You must tell Python to look in `src/` for modules:
   ```bash
   cd monitor3
   PYTHONPATH=src python -m monitor
    ```
   Or on Windows:
   ```cmd
   set PYTHONPATH=src
   python -m monitor

   This runs the CLI entry point as a module, which is the recommended way to test packages locally.

2. **For development, use editable install:**

   From `monitor3` do:
   ```bash
   pip install -e .
   ```

   This will install the package in "editable" mode. Now you can run the CLI as:

   monitor

   Any changes to the source code will be reflected immediately when you rerun the command.
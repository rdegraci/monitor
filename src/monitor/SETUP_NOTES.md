Python package installation via pip (console_scripts):

- The project will use setup.py and pip to allow installation as a standard command line tool named 'monitor'.
- The entry point will target 'app:main', so app.py must provide a 'main()' function wrapping the startup.
- This ensures 'monitor' is available via the user's PATH after installation (typically in ~/.local/bin, or the venv's bin/).
- All dependencies are sourced from requirements.txt and duplicated in setup.py for pip compatibility.
- setup.py discovers packages matching 'lib*' and 'core*'.
- Additional edits: app.py requires the CLI startup logic be moved under main(), not only under if __name__ == '__main__'.

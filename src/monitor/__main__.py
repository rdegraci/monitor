import importlib.util
import importlib.resources
import appdirs

def main():
    print("hello world")

    # 1. Print the installation path of the 'monitor' package
    monitor_spec = importlib.util.find_spec('monitor')
    print("\n[1] 'monitor' Package Installation Path:")
    if monitor_spec and monitor_spec.origin:
        print("Path:", monitor_spec.origin)
    else:
        print("Could not locate the 'monitor' package installation path.")

    # 2. Try to access a bundled example config file/resource via importlib.resources
    print("\n[2] Accessing bundled example resource 'example.cfg' from 'monitor':")
    try:
        if hasattr(importlib.resources, 'files'):
            # Python 3.9+
            resource = importlib.resources.files('monitor').joinpath('example.cfg')
            if resource.is_file():
                with importlib.resources.as_file(resource) as res_path:
                    with open(res_path, 'r') as f:
                        content = f.read()
                print("Contents of bundled 'example.cfg':")
                print(content)
            else:
                print("'example.cfg' not found in 'monitor' package resources.")
        else:
            # Python <3.9
            with importlib.resources.open_text('monitor', 'example.cfg') as f:
                content = f.read()
            print("Contents of bundled 'example.cfg':")
            print(content)
    except (FileNotFoundError, ImportError, ModuleNotFoundError):
        print("'example.cfg' not found or 'monitor' package does not provide this resource.")
    except Exception as e:
        print(f"Error accessing 'example.cfg': {e}")

    # 3. Print the user-specific config directory for 'monitor'
    print("\n[3] User-Specific Config Directory for 'monitor':")
    user_config_dir = appdirs.user_config_dir('monitor')
    print("User config directory:", user_config_dir)

if __name__ == "__main__":
    main()

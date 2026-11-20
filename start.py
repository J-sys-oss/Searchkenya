"""One-step starter: installs any missing libraries, then runs the demo.

    python start.py        (or press the Run button in VS Code while this file is open)

Works with whatever Python you run it with, so it avoids the common
"No module named 'flask'" problem.
"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 or newer is needed. You have " + sys.version.split()[0] + ". Install a newer Python from python.org.")

NEEDED = {"flask": "Flask", "requests": "requests", "bs4": "beautifulsoup4", "reportlab": "reportlab"}
missing = [pkg for mod, pkg in NEEDED.items() if importlib.util.find_spec(mod) is None]
if missing:
    print("Installing missing libraries:", ", ".join(missing), "(needs internet, one time only)")
    code = subprocess.call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *missing])
    if code != 0:
        sys.exit("\nCould not install the libraries. Check your internet connection and try again.\n"
                 "If it still fails, copy the red text above and send it to me.")

print("Starting the demo. When you see the box below, open http://127.0.0.1:5000 in Chrome.\n")
try:
    import runpy
    runpy.run_path(os.path.join(HERE, "demo.py"), run_name="__main__")
except OSError as e:
    sys.exit(f"\nCould not start the web server: {e}\n"
             "Another program may be using port 5000. Close other copies of the demo, or run:  set PORT=5055  then  python start.py")

"""Checks why the system will not start and tells you the fix. Run:  python diagnose.py"""
import importlib, os, socket, sys, tempfile, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE); sys.path.insert(0, HERE)
problems = []
def ok(m): print("  OK      " + m)
def bad(m, fix): print("  PROBLEM " + m); print("          FIX: " + fix); problems.append(m)

print("\nSearchKenya diagnosis\n" + "=" * 60)
print("Python:", sys.version.split()[0], "|", sys.executable)
print("Folder:", HERE)
if sys.version_info < (3, 9): bad("Python is older than 3.9", "Install the newest Python from python.org (tick 'Add python.exe to PATH').")
else: ok("Python version")
if "WindowsApps" in sys.executable: print("  NOTE    This is the Microsoft Store Python. If anything below fails, install Python from python.org instead.")

for need in ("app", "mock_site", "demo.py", "requirements.txt"):
    if os.path.exists(os.path.join(HERE, need)): ok("found " + need)
    else: bad("missing " + need, "You are not inside the extracted project folder. Extract the zip fully and open the 'searchkenya_indexer' folder itself.")

for mod, pkg in (("flask", "Flask"), ("requests", "requests"), ("bs4", "beautifulsoup4"), ("reportlab", "reportlab")):
    try:
        m = importlib.import_module(mod); ok(f"{pkg} {getattr(m, '__version__', '')}")
    except Exception as e:
        bad(f"{pkg} is not installed ({e.__class__.__name__})", f'Run:  "{sys.executable}" -m pip install {pkg}')

try:
    from app import create_app
    d = tempfile.mkdtemp()
    create_app({"DB_PATH": os.path.join(d, "t.db")}); ok("the application loads and creates its database")
except Exception:
    bad("the application failed to load", "Send me the error text printed just below.")
    traceback.print_exc()

s = socket.socket()
try:
    s.bind(("127.0.0.1", 5000)); ok("port 5000 is free")
except OSError:
    bad("port 5000 is already in use", "Close any other running copy of the demo (other terminal windows), or run  set PORT=5055  before starting and use :5055 in the address.")
finally:
    s.close()

print("=" * 60)
if problems: print(f"{len(problems)} problem(s) found. Do the FIX lines above, then run start.py again.")
else: print("Everything checks out. Run:  python start.py   then open http://127.0.0.1:5000")

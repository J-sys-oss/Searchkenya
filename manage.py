"""Create an administrator:  python manage.py create-admin <username>"""
import getpass
import sys
from app.db import connect, init_db
from app.auth import create_user
import os

db = os.environ.get("SK_DB", "searchkenya.db")
if len(sys.argv) == 3 and sys.argv[1] == "create-admin":
    init_db(db)
    pw = os.environ.get("SK_ADMIN_PASSWORD") or getpass.getpass("Password (min 8 chars): ")
    create_user(connect(db), sys.argv[2], pw)
    print("Administrator created.")
else:
    print(__doc__)

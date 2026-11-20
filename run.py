"""Start the system:  python run.py   (admin account is created by manage.py)"""
import os
from app import create_app

app = create_app({"SCHEDULER_INTERVAL": int(os.environ.get("SK_INTERVAL", "60"))})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))

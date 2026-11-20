# Automated Indexing Management and Real-Time Crawling System

SearchKenya Ltd - Milestone 3 (Flask + SQLite). Runs entirely on your own computer.

## Easiest on Windows
Double-click **START_DEMO.bat**. It sets everything up, starts the demo and opens the site in your browser.
(If Windows shows a blue "protected your PC" box, click More info > Run anyway.)

## 1. Open in Visual Studio Code
File > Open Folder... > choose this folder (the one containing `run.py`).
Install the "Python" extension if VS Code asks.

## 2. Set up (once)
Open a terminal in VS Code (Terminal > New Terminal) and run:

    python -m venv .venv
    .venv\Scripts\activate            (Windows)      source .venv/bin/activate   (macOS / Linux)
    pip install -r requirements.txt

If VS Code asks to use the new environment, choose Yes.

## 3a. See the whole site right now (demo)
    python demo.py
Open http://127.0.0.1:5000 and log in with the details printed in the terminal.
The page being monitored changes by itself every 25 seconds so you can watch the dashboard update.

## 3b. Run it for real
    python manage.py create-admin yourname        (asks for a password, 8+ characters)
    python run.py
Open http://127.0.0.1:5000. Add a seed URL on the Crawl Queue page.
For real use the crawler refuses private/local addresses (set SK_ALLOW_PRIVATE=1 only for testing).

## Pages
| Page | Address | What it does |
|---|---|---|
| Login | /login | Administrator sign-in (locks after 5 failed attempts) |
| Dashboard | / | Live counters, discrepancy log, reconciliation, audit report |
| Crawl Queue | /queue | Add seed URLs, recrawl, remove / de-index pages, start / stop jobs |
| Audit Report | /report | Latency, freshness accuracy, categories; PDF and CSV export |
| Search | /search | Search the index (shows what a user would see) |

## Tests
    python -m unittest discover -s tests          (79 tests, about 50 seconds)

## Folder guide
    app/          the web application (routes, crawler, database, reports, templates, static)
    mock_site/    a controllable test website used by the demo and the tests
    tests/        automated tests
    run.py        start the real system        demo.py   start the demo
    manage.py     create the administrator account

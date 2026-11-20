# Put the REAL system online (empty index, you add your own domains)

Free accounts needed: GitHub (github.com) and Render (render.com, "Sign in with GitHub").

1. Create a GitHub repository called `searchkenya-indexer`.
2. "Add file" > "Upload files": drag in everything from inside the project folder (wsgi_prod.py,
   requirements.txt, Procfile, the app folder, etc.) > "Commit changes".
3. On Render: New + > Web Service > pick the repository, then set:
   - Build command:  pip install -r requirements.txt
   - Start command:  gunicorn wsgi_prod:app --workers 1 --threads 4 --bind 0.0.0.0:$PORT
   - Instance type:  Free
   - Environment variables: ADMIN_PASSWORD (your own, 8+ characters) and SK_SECRET (any long random text)
4. Create Web Service. Open the address Render gives you, log in as `admin`, go to Crawl Queue,
   and add your domains with "+ Add New Seed URL".

Notes
- Keep ONE worker (the scheduler runs inside it).
- Free Render has a temporary disk: the database is emptied whenever the service restarts or redeploys.
  For permanent records use a paid instance with a persistent disk and set SK_DB to a file on that disk
  (for example /var/data/searchkenya.db).
- Free Render sleeps when idle; the first visit afterwards takes about a minute.
- `wsgi.py` is the demo version (sample shop). `wsgi_prod.py` is the real one.

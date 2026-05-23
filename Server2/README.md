# Vayumi Server 2

```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
scrapling install
cp .env.example .env
uvicorn server.app:app --port 8080
```

Deps: `pyproject.toml` / `requirements.txt` (includes `scrapling[fetchers]`, `trafilatura`, `tavily-python`). Page fetch: light static HTTP first, headless browser if the page is thin — same on Mac and Linux after `scrapling install`.

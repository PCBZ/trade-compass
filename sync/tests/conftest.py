"""main.py reads its API settings at import; give it dummies so tests can import it."""

import os

os.environ.setdefault("API_URL", "http://api.invalid")
os.environ.setdefault("API_KEY", "test")

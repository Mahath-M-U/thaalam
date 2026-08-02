import os
from dotenv import load_dotenv

load_dotenv()

client_id = os.getenv("CLIENT_ID") or ""
client_secret = os.getenv("CLIENT_SECRET") or ""
redirect_uri = os.getenv("REDIRECT_URI") or ""
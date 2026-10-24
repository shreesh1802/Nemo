"""Print every model your Token Factory key can use, Nemotron first.

Run this once, then paste the IDs you want into .env as NEMO_MODEL_FAST /
NEMO_MODEL_STANDARD / NEMO_MODEL_DEEP.
"""
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
key = os.getenv("NEBIUS_API_KEY")
if not key:
    sys.exit("Set NEBIUS_API_KEY in .env first.")

client = OpenAI(
    api_key=key,
    base_url=os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1"),
)
ids = sorted((m.id for m in client.models.list()), key=lambda i: ("nemotron" not in i.lower(), i))
for model_id in ids:
    print(model_id)

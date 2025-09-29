from mem0 import MemoryClient
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("MEM0_API_KEY")
print(f"Retrieved MEM0_API_KEY from env: {api_key}")
print(f"Full env check: {os.environ.get('MEM0_API_KEY')}")
client = MemoryClient(api_key=api_key)

user_id = "noah"
messages = [{"role": "user", "content": "My username is noah."}]
client.add(messages, user_id=user_id, metadata={"label": "profile"})

# Search to verify
query = "username"
filters = {"OR": [{"user_id": user_id}]}
results = client.search(query, filters=filters, version="v2")
print("Added memory for user 'noah'.")
print("Search results:", results)
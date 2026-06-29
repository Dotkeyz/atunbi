import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# LAZY INITIALIZATION: Prevents crash on boot if secrets are missing
_client = None

def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("QWEN_API_KEY")
        base_url = os.getenv("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
        if not api_key:
            raise ValueError("QWEN_API_KEY is missing from environment variables.")
        _client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return _client

async def get_embedding(text: str) -> list[float]:
    client = get_client()
    response = await client.embeddings.create(
        input=text,
        model="text-embedding-v4", 
        dimensions=1536            
    )
    return response.data[0].embedding

async def score_importance(text: str) -> float:
    client = get_client()
    response = await client.chat.completions.create(
        model="qwen-plus", 
        messages=[
            {"role": "system", "content": "You are a cognitive memory filter. Rate the long-term importance of the user's statement from 0.0 (forgettable trivia) to 1.0 (critical life fact). Reply with ONLY the float number."},
            {"role": "user", "content": text}
        ],
        temperature=0.1
    )
    try:
        return float(response.choices[0].message.content.strip())
    except ValueError:
        return 0.5

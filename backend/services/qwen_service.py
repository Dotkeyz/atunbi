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


async def score_emotion(text: str) -> float:
    client = get_client()
    response = await client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": "Rate the emotional valence of the text from -1.0 (very negative/trauma) to 1.0 (very positive/joy). Reply with ONLY the float number."},
            {"role": "user", "content": text}
        ],
        temperature=0.1
    )
    try:
        return float(response.choices[0].message.content.strip())
    except:
        return 0.0

async def generate_response(context: str, user_message: str) -> str:
    client = get_client()
    prompt = f"""You are an AI assistant with perfect memory. 
User's current message: "{user_message}"
Relevant memories:
{context}

Respond conversationally using ONLY the information above. Do not make up facts. If you don't have enough context, say so briefly."""
    
    response = await client.chat.completions.create(
        model="qwen-max",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content

async def generate_stream(context: str, user_message: str):
    client = get_client()
    prompt = f"""You are an AI assistant with perfect memory. 
User's current message: "{user_message}"
Relevant memories:
{context}

Respond conversationally using ONLY the information above. Do not make up facts."""
    
    stream = await client.chat.completions.create(
        model="qwen-max",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        stream=True
    )
    async for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            yield chunk.choices[0].delta.content

async def summarize_episode(conversation_text: str) -> str:
    client = get_client()
    response = await client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": "You are a memory consolidation engine. Summarize the following conversation into a single, concise episodic memory (1-2 sentences). Capture the context and key events."},
            {"role": "user", "content": conversation_text}
        ],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

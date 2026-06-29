import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("QWEN_API_KEY"),
    base_url=os.getenv("QWEN_BASE_URL")
)

async def get_embedding(text: str) -> list[float]:
    response = await client.embeddings.create(
        input=text,
        model="text-embedding-v4", 
        dimensions=1536            
    )
    return response.data[0].embedding

async def score_importance(text: str) -> float:
    '''
    Uses Qwen's reasoning engine to act as the brain's amygdala.
    It tags the memory with an importance score from 0.0 to 1.0.
    '''
    response = await client.chat.completions.create(
        model="qwen-plus", # Qwen's reasoning model
        messages=[
            {"role": "system", "content": "You are a cognitive memory filter. Rate the long-term importance of the user's statement from 0.0 (forgettable trivia) to 1.0 (critical life fact). Reply with ONLY the float number."},
            {"role": "user", "content": text}
        ],
        temperature=0.1
    )
    try:
        return float(response.choices[0].message.content.strip())
    except ValueError:
        return 0.5 # Fallback if the LLM hallucinates text

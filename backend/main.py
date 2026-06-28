from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# initialize the App
app = FastAPI(title = "Atunbi Walking Skeleton")

# The DTO (Data Transfer Object)
class ChatRequest(BaseModel):
    message: str = Field(..., min_length = 1, max_length = 1000)
    user_id: str = "dotun-test"

# The Controller Endpoint 
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        # For the skeleton, we just echo it back to prove the server is alive
        ai_response = f"Hello {request.user_id}. The skeleton is walking! You said: {request.message}"

        return {"status": "success", "reply": ai_response}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail="An error occurred while processing the request")

@app.get("/health")
async def health_check():
    return {"status": "alive", "service": "atunbi-skeleton"}   
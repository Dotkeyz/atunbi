import os
from dotenv import load_dotenv
load_dotenv()

# Fixed: Must be at least 32 bytes for SHA256 JWT signing
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-hackathon-key-2026!!")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 # 24 hours

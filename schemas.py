# schemas.py





from pydantic import BaseModel

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: str | None = None


 

class UserCreate(BaseModel):
    email: str
    password: str
    customer_name: str

class Token(BaseModel):
    access_token: str
    token_type: str


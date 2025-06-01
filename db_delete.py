from database import SessionLocal
from models import User

db = SessionLocal()

# Replace this with the email you want to reset
email_to_reset = "trevorkuhlmannk@gmail.com"

user = db.query(User).filter(User.email == email_to_reset).first()
if user:
    db.delete(user)
    db.commit()
    print("User deleted.")
else:
    print("User not found.")

db.close()

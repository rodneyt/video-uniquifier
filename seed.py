import os
from sqlalchemy import text
from api.database import SessionLocal, engine, Base
from api.models import User
from api.auth import get_password_hash

def seed_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    demo_email = "demo@example.com"
    existing = db.query(User).filter(User.email == demo_email).first()
    
    if not existing:
        user = User(
            email=demo_email,
            password_hash=get_password_hash("demo123"),
            plan="standard"
        )
        db.add(user)
        db.commit()
        print(f"Usuario creado: {demo_email} / demo123")
    else:
        print("El usuario demo ya existe")
        
    db.close()

if __name__ == "__main__":
    seed_db()

from database import Base, engine

print("Creating database tables...")
Base.metadata.create_all(bind=engine)
print("✅ Database initialized successfully!")
print("\n📊 Now run the app with: python main.py")

"""
Database models and setup
"""
from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# SQLite database (change to PostgreSQL for production)
DATABASE_URL = "sqlite:///applicants.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Applicant(Base):
    """Represents a unique applicant (person)"""
    __tablename__ = "applicants"
    
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, index=True)
    phone = Column(String, unique=True, index=True)
    labor_id = Column(String, index=True)
    
    # Relationship to applications
    applications = relationship("Application", back_populates="applicant")

class Application(Base):
    """Represents each application (a person can have multiple)"""
    __tablename__ = "applications"
    
    id = Column(Integer, primary_key=True, index=True)
    applicant_id = Column(Integer, ForeignKey("applicants.id"))
    position = Column(String, index=True)
    application_date = Column(Date, index=True)
    source_file = Column(String)
    
    # Relationship to applicant
    applicant = relationship("Applicant", back_populates="applications")

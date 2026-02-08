"""
Main FastAPI application for Excel Data Pool
"""
import os
from datetime import datetime, date
from typing import Optional

import pandas as pd
from fastapi import FastAPI, UploadFile, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import SessionLocal, Applicant, Application

# Initialize FastAPI
app = FastAPI(title="Excel Data Pool", version="1.0.0")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Create uploads directory
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Column names (Amharic)
POSITION_COL = "የስራ መደብ"
DATE_COL = "የመመዝገቢያ ቀን"
PHONE_COL = "ስልክ/ሞባይል"
LABOR_ID_COL = "የሰራተኛ መለያ ቁጥር"
NAME_COL = "ሙሉ ስም"

def clean_phone(phone: str) -> str:
    """Clean and standardize phone numbers"""
    if pd.isna(phone):
        return ""
    
    phone_str = str(phone).strip()
    
    # Remove all non-digit characters
    digits = ''.join(filter(str.isdigit, phone_str))
    
    # Handle Ethiopian numbers
    if digits.startswith('0') and len(digits) == 10:
        return '+251' + digits[1:]
    elif digits.startswith('251') and len(digits) == 12:
        return '+' + digits
    elif digits.startswith('9') and len(digits) == 9:
        return '+251' + digits
    
    return phone_str

def clean_text(text: str) -> str:
    """Clean text fields"""
    if pd.isna(text):
        return ""
    return str(text).strip()

def get_db():
    """Database dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Main page"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/upload")
async def upload_excel(file: UploadFile):
    """Upload and process Excel file"""
    # Validate file type
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "File must be Excel (.xlsx or .xls)")
    
    # Save file
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())
    
    # Read Excel
    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        raise HTTPException(400, f"Error reading Excel: {str(e)}")
    
    # Clean column names
    df.columns = [str(col).strip() for col in df.columns]
    
    # Check required columns
    required_cols = [POSITION_COL, PHONE_COL, NAME_COL]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise HTTPException(400, f"Missing columns: {', '.join(missing)}")
    
    db = SessionLocal()
    stats = {
        "new_applicants": 0,
        "existing_applicants": 0,
        "applications_added": 0
    }
    
    try:
        for _, row in df.iterrows():
            # Clean data
            phone = clean_phone(row.get(PHONE_COL))
            labor_id = clean_text(row.get(LABOR_ID_COL, ""))
            full_name = clean_text(row.get(NAME_COL))
            position = clean_text(row.get(POSITION_COL, "")).lower()
            
            # Parse date
            date_value = row.get(DATE_COL)
            if pd.isna(date_value):
                app_date = date.today()
            else:
                try:
                    app_date = pd.to_datetime(date_value).date()
                except:
                    app_date = date.today()
            
            # Find or create applicant
            applicant = None
            
            # Search by phone (primary)
            if phone:
                applicant = db.query(Applicant).filter(Applicant.phone == phone).first()
            
            # Search by labor ID (secondary)
            if not applicant and labor_id:
                applicant = db.query(Applicant).filter(
                    Applicant.labor_id == labor_id
                ).first()
            
            if applicant:
                stats["existing_applicants"] += 1
            else:
                # Create new applicant
                applicant = Applicant(
                    full_name=full_name,
                    phone=phone,
                    labor_id=labor_id
                )
                db.add(applicant)
                db.commit()
                db.refresh(applicant)
                stats["new_applicants"] += 1
            
            # Add application record
            application = Application(
                applicant_id=applicant.id,
                position=position,
                application_date=app_date,
                source_file=file.filename
            )
            db.add(application)
            stats["applications_added"] += 1
        
        db.commit()
        
        return {
            "success": True,
            "message": "File processed successfully",
            "stats": stats,
            "filename": file.filename
        }
    
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Database error: {str(e)}")
    finally:
        db.close()

@app.post("/search")
async def search_applicants(
    position: str = Form(...),
    start_date: Optional[str] = Form(None),
    end_date: Optional[str] = Form(None),
    unique_only: bool = Form(False),
    output_format: str = Form("excel")
):
    """Search applicants by position and date range"""
    db = SessionLocal()
    
    try:
        # Build query
        query = db.query(Application, Applicant).join(Applicant)
        
        # Filter by position (case-insensitive contains)
        position_lower = position.lower().strip()
        query = query.filter(Application.position.contains(position_lower))
        
        # Filter by date range
        if start_date:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            query = query.filter(Application.application_date >= start)
        
        if end_date:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
            query = query.filter(Application.application_date <= end)
        
        # Get results
        results = query.order_by(Application.application_date.desc()).all()
        
        # Handle unique-only mode
        if unique_only:
            seen_applicants = set()
            unique_results = []
            for app, applicant in results:
                applicant_key = applicant.phone or applicant.labor_id or applicant.full_name
                if applicant_key not in seen_applicants:
                    seen_applicants.add(applicant_key)
                    unique_results.append((app, applicant))
            results = unique_results
        
        # Prepare response data
        if output_format == "json":
            data = []
            for app, applicant in results:
                data.append({
                    "full_name": applicant.full_name,
                    "phone": applicant.phone,
                    "labor_id": applicant.labor_id,
                    "position": app.position,
                    "application_date": app.application_date.isoformat(),
                    "source_file": app.source_file
                })
            
            return JSONResponse(content={
                "count": len(data),
                "position": position,
                "applicants": data
            })
        
        else:  # Excel format (default)
            # Create DataFrame
            records = []
            for app, applicant in results:
                records.append({
                    "ሙሉ ስም": applicant.full_name,
                    "ስልክ/ሞባይል": applicant.phone,
                    "የሰራተኛ መለያ ቁጥር": applicant.labor_id,
                    "የስራ መደብ": app.position,
                    "የመመዝገቢያ ቀን": app.application_date,
                    "የተመዘገበበት ፋይል": app.source_file
                })
            
            if not records:
                raise HTTPException(404, "No applicants found for this position")
            
            df = pd.DataFrame(records)
            
            # Save to Excel
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_position = "".join(c for c in position if c.isalnum())
            filename = f"applicants_{safe_position}_{timestamp}.xlsx"
            filepath = os.path.join(UPLOAD_DIR, filename)
            
            df.to_excel(filepath, index=False)
            
            return FileResponse(
                filepath,
                filename=filename,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    
    finally:
        db.close()

@app.get("/stats")
async def get_statistics():
    """Get overall statistics"""
    db = SessionLocal()
    
    try:
        # Basic counts
        total_applicants = db.query(Applicant).count()
        total_applications = db.query(Application).count()
        
        # Positions count
        positions_query = db.query(
            Application.position,
            db.func.count(Application.id)
        ).group_by(Application.position).all()
        
        positions = [
            {"name": pos, "count": count}
            for pos, count in positions_query
            if pos  # Skip empty positions
        ]
        
        # Recent activity
        recent_apps = db.query(Application).order_by(
            Application.application_date.desc()
        ).limit(10).all()
        
        recent_activity = []
        for app in recent_apps:
            applicant = db.query(Applicant).filter(
                Applicant.id == app.applicant_id
            ).first()
            recent_activity.append({
                "date": app.application_date,
                "applicant": applicant.full_name if applicant else "Unknown",
                "position": app.position
            })
        
        return {
            "total_applicants": total_applicants,
            "total_applications": total_applications,
            "positions": sorted(positions, key=lambda x: x["count"], reverse=True),
            "recent_activity": recent_activity
        }
    
    finally:
        db.close()

@app.get("/positions")
async def get_all_positions():
    """Get list of all unique positions"""
    db = SessionLocal()
    
    try:
        positions = db.query(Application.position).distinct().all()
        position_list = [p[0] for p in positions if p[0]]  # Remove empty strings
        return {"positions": sorted(set(position_list))}
    
    finally:
        db.close()

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Excel Data Pool System...")
    print("📊 Open http://localhost:8000 in your browser")
    uvicorn.run(app, host="0.0.0.0", port=8000)

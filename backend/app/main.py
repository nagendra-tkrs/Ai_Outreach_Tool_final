import os
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config.database import close_db, connect_db
from app.auth.middleware import AuthMiddleware
from app.auth.security import validate_auth_config_for_production
from app.routers.auth_routes import router as auth_router
from app.routers.company_routes import router as company_router
from app.routers.contact_routes import router as contact_router
from app.routers.crawl_routes import router as crawl_router
from app.routers.health import router as health_router
from app.routers.import_routes import router as import_router
from app.routers.outreach_routes import router as outreach_router
from app.routers.research_routes import router as research_router
from app.routers.settings_routes import router as settings_router
from app.routers.tracking_routes import router as tracking_router
from app.services.scheduler_service import start_scheduler, stop_scheduler

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_outreach")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: validate production auth configuration before initializing resources
    validate_auth_config_for_production()
    logger.info("Initializing application resources...")
    await connect_db()
    start_scheduler(60)
    yield
    # Shutdown
    logger.info("Cleaning up application resources...")
    stop_scheduler()
    await close_db()


app = FastAPI(
    title="AI Client Outreach API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS setup
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
origins = [
    frontend_url,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled Exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": str(exc) or "Internal server error"},
    )


# Mount routers matching Node backend endpoints
app.include_router(health_router, prefix="/api", tags=["Health"])
app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(import_router, prefix="/api/import", tags=["Import"])
app.include_router(company_router, prefix="/api/companies", tags=["Companies"])
app.include_router(crawl_router, prefix="/api", tags=["Crawler"])
app.include_router(research_router, prefix="/api", tags=["Research"])
app.include_router(contact_router, prefix="/api/contacts", tags=["Contacts"])
app.include_router(contact_router, prefix="/api", tags=["Company Contacts"])
app.include_router(outreach_router, prefix="/api/outreach", tags=["Outreach"])
app.include_router(outreach_router, prefix="/api", tags=["Company Outreach"])
app.include_router(settings_router, prefix="/api/settings", tags=["Settings"])
app.include_router(tracking_router, prefix="/api/track", tags=["Tracking"])

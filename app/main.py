from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.logger import use_logger
from app.env_validator import get_settings
from app.containers import AppContainers

from app.auth.endpoints import router as auth_router
from app.application.test import router as test_router
from app.student.endpoints import router as student_router
from app.bracket.endpoints import router as bracket_router

logger = use_logger("bootstrapper")
settings = get_settings()


def bootstrap() -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        logger.info("Starting application")
        motor_client = AsyncIOMotorClient(
            settings.MONGODB_URI, uuidRepresentation="standard"
        )
        await init_beanie(
            database=motor_client[settings.MONGODB_DATABASE],
            document_models=[
                "app.user.entities.User",
                "app.auth.entities.VerificationCode",
                "app.bracket.entities.Match",
            ],
        )
        application.container = container
        logger.info("Container Wiring started")
        container.wire(
            modules=[
                __name__,
                "app.auth.endpoints",
                "app.student.endpoints",
                "app.bracket.endpoints",
            ]
        )
        logger.info("Container Wiring complete")
        logger.info("Application started")
        yield
        motor_client.close()
        logger.info("Motor Client connections closed")
        logger.info("Application shutdown complete")

        
    origins = [
        "mixir-api.sunrin.kr",
        "mixir.sunrin.kr",
    ]
    app = FastAPI(
        title="Mixir Backend API",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        debug=settings.APP_ENV == "development" or settings.APP_ENV == "testing",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


container = AppContainers()
server = bootstrap()

server.include_router(auth_router)
server.include_router(test_router)
server.include_router(student_router)
server.include_router(bracket_router)

"""FastAPI application factory (ID-01). Routers are mounted as their tasks land."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    return FastAPI(title="CARDIO4Cities", version="0.1.0")


app = create_app()

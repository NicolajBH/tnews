from fastapi import APIRouter, Depends, Request, Response
from typing import Dict, Any

from src.core.degradation import HealthService
from src.api.dependencies import get_health_service


router = APIRouter()


@router.get("/", response_model=Dict[str, Any])
async def health_check(
    health_service: HealthService = Depends(get_health_service),
) -> Dict[str, Any]:
    """
    Get overall system health status

    Returns:
        Dict containing overall status, services, and unhealthy services
    """
    health_data = health_service.get_system_health()
    return health_data


@router.get("/services", response_model=Dict[str, Any])
async def service_health(
    health_service: HealthService = Depends(get_health_service),
) -> Dict[str, Any]:
    """
    Get detailed service health information for all services

    Returns:
        Dict containing health info for all services
    """
    return {"services": health_service.get_all_service_health()}


@router.get("/services/{service_name}", response_model=Dict[str, Any])
async def service_detail(
    service_name: str,
    health_service: HealthService = Depends(get_health_service),
) -> Dict[str, Any]:
    """
    Get detailed health information for a specific service

    Args:
        service_name: Name of the service to get information for

    Returns:
        Dict containing detailed health info for the specified service
    """
    service_health = health_service.get_service_health(service_name)
    if not service_health:
        return {"error": "Service not found", "service": service_name}

    return service_health.to_dict()


@router.get("/circuit-breakers", response_model=Dict[str, Any])
async def circuit_breakers(
    health_service: HealthService = Depends(get_health_service),
) -> Dict[str, Any]:
    """
    Get circuit breaker status information

    Returns:
        Dict containing status of all circuit breakers
    """
    services = health_service.get_all_service_health()
    circuit_data = {}

    for name, service in services.items():
        if "circuit" in service:
            circuit_data[name] = service["circuit"]

    return {"circuit_breakers": circuit_data}

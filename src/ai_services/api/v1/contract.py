"""GET /v1/contract: report the contract version being served."""

from fastapi import APIRouter, Request

from ai_services.schemas import ContractInfo

router = APIRouter(prefix="/v1")


@router.get("/contract", operation_id="getContract", openapi_extra={"security": []})
async def get_contract(request: Request) -> ContractInfo:
    return ContractInfo(version=request.app.state.contract_version)

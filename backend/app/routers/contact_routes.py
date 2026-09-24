import logging
from typing import Optional
from fastapi import APIRouter, Body, Query, status
from app.services.contact_service import (
    apply_pattern_to_contacts,
    create_contact,
    delete_contact,
    extract_contacts_from_website,
    get_company_contacts,
    get_company_email_pattern_info,
    update_contact,
    verify_contact_email,
)
from app.services.search.search_provider import get_active_search_provider_config

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/companies/{company_id}/contacts/pattern")
@router.get("/{company_id}/contacts/pattern")
@router.get("/pattern")
async def get_pattern_info(company_id: Optional[str] = None, companyId: Optional[str] = Query(None)):
    cid = company_id or companyId
    pattern_data = await get_company_email_pattern_info(cid)
    return {"success": True, "data": pattern_data}


@router.post("/companies/{company_id}/contacts/apply-pattern")
@router.post("/{company_id}/contacts/apply-pattern")
@router.post("/apply-pattern")
async def apply_pattern(
    company_id: Optional[str] = None,
    payload: dict = Body(...),
):
    cid = company_id or payload.get("companyId")
    pattern = payload.get("pattern")
    result = await apply_pattern_to_contacts(cid, pattern)
    return {
        "success": True,
        "message": "Email format applied to decision makers",
        "data": result,
    }


@router.get("/companies/{company_id}/contacts")
@router.get("/{company_id}/contacts")
@router.get("")
@router.get("/")
async def list_contacts(company_id: Optional[str] = None, companyId: Optional[str] = Query(None)):
    cid = company_id or companyId
    contacts = await get_company_contacts(cid) if cid else []
    return {"success": True, "data": contacts}


@router.post("/companies/{company_id}/contacts", status_code=status.HTTP_201_CREATED)
@router.post("/{company_id}/contacts", status_code=status.HTTP_201_CREATED)
@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_contact(
    company_id: Optional[str] = None,
    payload: dict = Body(...),
):
    cid = company_id or payload.get("companyId")
    contact = await create_contact(cid, payload)
    return {
        "success": True,
        "message": "Contact created successfully",
        "data": contact,
    }


@router.post("/companies/{company_id}/contacts/discover")
@router.post("/{company_id}/contacts/discover")
async def discover_contacts(company_id: str):
    contacts, diagnostics = await extract_contacts_from_website(company_id, return_diagnostics=True, enable_phase2=True)
    decision_makers = [
        c for c in contacts if c.get("roleCategory") != "general" and c.get("seniority") != "general"
    ]
    selected_dm = (
        next((c for c in decision_makers if c.get("isPrimaryDecisionMaker")), None)
        or (decision_makers[0] if decision_makers else None)
    )
    dm_status = selected_dm.get("decisionMakerStatus", "NOT_VERIFIED") if selected_dm else "NOT_VERIFIED"
    search_config = get_active_search_provider_config()

    return {
        "success": True,
        "message": "Contacts extracted successfully",
        "data": contacts,
        "decisionMakers": decision_makers,
        "selectedDecisionMaker": selected_dm,
        "decisionMakerStatus": dm_status,
        "discoveryMetadata": {
            "requested_count": 6,
            "verified_count": len(decision_makers),
            "status": "COMPLETE" if len(decision_makers) >= 6 else "PARTIAL",
        },
        "phase1Diagnostics": diagnostics,
        "searchDiagnostics": {
            "provider": search_config.get("providerName", "none"),
            "isConfigured": bool(search_config.get("isConfigured")),
            "reason": search_config.get("reason")
            or ("READY" if search_config.get("isConfigured") else "SEARCH_PROVIDER_NOT_CONFIGURED"),
        },
    }


@router.put("/companies/{company_id}/contacts/{contact_id}")
@router.put("/{company_id}/contacts/{contact_id}")
@router.put("/{contact_id}")
async def edit_contact(contact_id: str, payload: dict = Body(...), company_id: Optional[str] = None):
    contact = await update_contact(contact_id, payload)
    return {
        "success": True,
        "message": "Contact updated successfully",
        "data": contact,
    }


@router.delete("/companies/{company_id}/contacts/{contact_id}")
@router.delete("/{company_id}/contacts/{contact_id}")
@router.delete("/{contact_id}")
async def remove_contact(contact_id: str, company_id: Optional[str] = None):
    result = await delete_contact(contact_id)
    return {"success": True, "message": result.get("message", "Contact deleted")}


@router.post("/companies/{company_id}/contacts/{contact_id}/verify")
@router.post("/{company_id}/contacts/{contact_id}/verify")
@router.post("/{contact_id}/verify")
async def verify_contact(contact_id: str, company_id: Optional[str] = None):
    contact = await verify_contact_email(contact_id)
    return {
        "success": True,
        "message": "Contact email verified successfully",
        "data": contact,
    }

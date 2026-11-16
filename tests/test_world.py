"""Demo world: one fictional member shared by the allowlisted reads."""

from __future__ import annotations

import json
from pathlib import Path

from httpx2 import ASGITransport, AsyncClient

from pbm_mcp.mock.app import create_app

_REPO = Path(__file__).resolve().parents[1]
_WORLD = _REPO / "mocks" / "world"

_MEMBER_ID = "MBR100200300"
_CARRIER = "CAR100"
_ACCOUNT = "ACC200"
_GROUP = "GRP300"
_LIPITOR_CLAIM = "RX1002001"
_LIPITOR_FILL = "2026-10-02"
_LIPITOR_GPI = "39400010102001"
_HUMIRA_PRODUCT = "PROD-HUMIRA-40"
_PA_NUMBER = "PA-24011"


def _app(**kwargs):
    return create_app(
        specs_dir=_REPO / "specs",
        allowlists_dir=_REPO / "allowlists",
        fixtures_dir=kwargs.get("fixtures_dir", _REPO / "mocks" / "empty-fixtures"),
        world_dir=kwargs.get("world_dir", _WORLD),
    )


async def _operation(app, domain_id: str, operation_name: str, variables: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(
            f"/v1/{domain_id}/graphql",
            json={
                "query": f"query {operation_name} {{ {operation_name} }}",
                "operationName": operation_name,
                "variables": variables,
            },
        )


def _data(response, operation_name: str):
    assert response.status_code == 200, response.text
    body = response.json()
    assert "errors" not in body, body
    return body["data"][operation_name]


async def test_demo_identifiers_match_across_tools(tmp_path):
    app = _app(fixtures_dir=tmp_path)
    profile = _data(
        await _operation(app, "member-profile", "searchUserProfile", {}),
        "searchUserProfile",
    )
    assert profile["memberId"] == _MEMBER_ID
    assert profile["carrierId"] == _CARRIER
    assert profile["accountId"] == _ACCOUNT
    assert profile["groupId"] == _GROUP
    assert profile["demographics"]["firstName"] == "Jordan"
    assert profile["demographics"]["lastName"] == "Hale"

    claims = _data(
        await _operation(
            app,
            "claim-history",
            "claims",
            {
                "claimsRequest": {
                    "fromDate": "2020-01-01",
                    "thruDate": "2020-01-31",
                    "cagmi": {"memberId": _MEMBER_ID},
                }
            },
        ),
        "claims",
    )
    lipitor = next(
        claim
        for claim in claims["claimList"]
        if claim["general"]["claimNumber"] == _LIPITOR_CLAIM
    )
    assert lipitor["member"] == {"memberFirstName": "Jordan", "memberLastName": "Hale"}

    prescriber = _data(
        await _operation(
            app,
            "savings-center",
            "prescriberDetails",
            {"prescriberDetailsInput": {"rxClaimNumber": _LIPITOR_CLAIM}},
        ),
        "prescriberDetails",
    )
    assert prescriber["memberId"] == _MEMBER_ID
    assert prescriber["carrierId"] == _CARRIER
    assert prescriber["accountId"] == _ACCOUNT
    assert prescriber["groupId"] == _GROUP
    assert prescriber["claimNumber"] == _LIPITOR_CLAIM
    assert prescriber["prescriberFirstName"] == "Priya"
    assert prescriber["prescriberLastName"] == "Shah"

    recommendations = _data(
        await _operation(app, "savings-center", "recommendations", {}),
        "recommendations",
    )
    assert recommendations["recommendations"][0]["cagm"] == {
        "carrierId": _CARRIER,
        "accountId": _ACCOUNT,
        "groupId": _GROUP,
        "memberId": _MEMBER_ID,
    }

    consent = _data(
        await _operation(
            app,
            "member-consent",
            "memberConsentDetails",
            {"request": {"consentType": "MAIL"}},
        ),
        "memberConsentDetails",
    )
    assert consent[0]["memberId"] == _MEMBER_ID

    card = _data(await _operation(app, "id-card", "fetchIdCard", {}), "fetchIdCard")
    assert card["carrierId"] == _CARRIER
    assert card["accountId"] == _ACCOUNT
    assert card["groupId"] == _GROUP
    assert card["rxGrp"] == _GROUP

    history = _data(await _operation(app, "prior-auth", "history", {}), "history")
    assert history[0]["prescriberName"] == "Priya Shah"
    assert history[0]["productId"] == _HUMIRA_PRODUCT


async def test_statin_family_and_humira_prior_auth(tmp_path):
    app = _app(fixtures_dir=tmp_path)

    lipitor = _data(
        await _operation(
            app,
            "drug-search",
            "drugSearch",
            {"drugSearchRequest": {"queryType": "name", "queryTerm": "Lipitor"}},
        ),
        "drugSearch",
    )["drugs"]
    atorvastatin = _data(
        await _operation(
            app,
            "drug-search",
            "drugSearch",
            {"drugSearchRequest": {"queryType": "name", "queryTerm": "atorvastatin"}},
        ),
        "drugSearch",
    )["drugs"]
    humira = _data(
        await _operation(
            app,
            "drug-search",
            "drugSearch",
            {"drugSearchRequest": {"queryType": "name", "queryTerm": "Humira"}},
        ),
        "drugSearch",
    )["drugs"]

    lipitor_row = next(row for row in lipitor if "Lipitor" in row["productName"])
    generic_row = next(
        row for row in atorvastatin if "atorvastatin" in row["productName"].casefold()
    )
    humira_row = next(row for row in humira if row["productId"] == _HUMIRA_PRODUCT)
    assert lipitor_row["gpi10"] == generic_row["gpi10"]
    assert humira_row["gpi10"] != lipitor_row["gpi10"]

    details = _data(
        await _operation(
            app,
            "formulary",
            "drugDetails",
            {
                "drugDetailsRequest": {
                    "productId": _HUMIRA_PRODUCT,
                    "formularyCode": "DEMO-COMM-2026",
                }
            },
        ),
        "drugDetails",
    )
    assert details["productId"] == _HUMIRA_PRODUCT
    assert details["requiresPriorAuthorization"] is True
    assert details["requiresStepTherapy"] is True
    assert "methotrexate" in details["stepTherapyNote"].casefold()

    steps = _data(
        await _operation(
            app,
            "formulary",
            "stepTherapyRules",
            {
                "sTCriteriaRequest": {
                    "formularyId": "DEMO-COMM-2026",
                    "productId": _HUMIRA_PRODUCT,
                }
            },
        ),
        "stepTherapyRules",
    )
    assert steps["productId"] == _HUMIRA_PRODUCT
    assert any(
        group["groupName"] == "methotrexate" for group in steps["stepTherapyGroup"]
    )

    history = _data(await _operation(app, "prior-auth", "history", {}), "history")
    assert history[0]["priorAuthNumber"] == _PA_NUMBER
    assert history[0]["productId"] == _HUMIRA_PRODUCT
    assert history[0]["priorAuthStatus"] == "Pending"

    pricing = _data(
        await _operation(
            app,
            "drug-pricing",
            "drugPricing",
            {
                "drugPricingRequest": {
                    "medicationName": "Lipitor",
                    "ndc": "99999000120",
                }
            },
        ),
        "drugPricing",
    )
    assert pricing["topResult"]["priceAndPharmacyInfo"]["patientPayAmt"] == 47.0
    generic_price = pricing["genericDrugResults"][0]["priceAndPharmacyInfo"][0]
    assert generic_price["patientPayAmt"] == 12.0
    assert generic_price["preferredInd"] is True
    assert "35" in pricing["overallMessages"][0]["message"]


async def test_drug_search_hit_and_miss(tmp_path):
    app = _app(fixtures_dir=tmp_path)
    found = _data(
        await _operation(
            app,
            "drug-search",
            "drugSearch",
            {"drugSearchRequest": {"queryType": "name", "queryTerm": "atorvastatin"}},
        ),
        "drugSearch",
    )
    assert any(
        "atorvastatin" in drug["productName"].casefold() for drug in found["drugs"]
    )

    missing = _data(
        await _operation(
            app,
            "drug-search",
            "drugSearch",
            {
                "drugSearchRequest": {
                    "queryType": "name",
                    "queryTerm": "zzzz-not-a-drug",
                }
            },
        ),
        "drugSearch",
    )
    assert missing["drugs"] == []

    priced = _data(
        await _operation(
            app,
            "drug-pricing",
            "drugPricing",
            {"drugPricingRequest": {"medicationName": "zzzz-not-a-drug"}},
        ),
        "drugPricing",
    )
    assert priced["header"]["statusCd"] == "NO_RESULTS"
    assert priced["genericDrugResults"] == []
    assert priced["topResult"] is None


async def test_claim_details_requires_fill_gpi_and_number(tmp_path):
    app = _app(fixtures_dir=tmp_path)
    found = _data(
        await _operation(
            app,
            "claim-history",
            "claimDetails",
            {
                "claimDetailsRequest": {
                    "fillDate": _LIPITOR_FILL,
                    "gpi": _LIPITOR_GPI,
                    "rxClaimNumber": _LIPITOR_CLAIM,
                }
            },
        ),
        "claimDetails",
    )
    assert found["claimDetails"]["general"]["claimNumber"] == _LIPITOR_CLAIM
    assert found["claimDetails"]["drug"]["gpi"] == _LIPITOR_GPI
    assert found["claimDetails"]["payment"]["patientPaid"] == 47.0

    missing = await _operation(
        app,
        "claim-history",
        "claimDetails",
        {
            "claimDetailsRequest": {
                "fillDate": _LIPITOR_FILL,
                "gpi": _LIPITOR_GPI,
                "rxClaimNumber": "RX0000000",
            }
        },
    )
    assert missing.status_code == 200
    body = missing.json()
    assert body["data"] is None
    assert body["errors"][0]["message"] == "Claim not found."


async def test_other_member_is_not_returned(tmp_path):
    app = _app(fixtures_dir=tmp_path)
    profile = _data(
        await _operation(
            app,
            "member-profile",
            "userProfile",
            {"demographicSearchInput": {"memberId": "MBR000"}},
        ),
        "userProfile",
    )
    assert profile["__typename"] == "CustomError"
    assert profile["errorCode"] == "MEMBER_NOT_FOUND"

    claims = _data(
        await _operation(
            app,
            "claim-history",
            "claims",
            {
                "claimsRequest": {
                    "fromDate": "2026-01-01",
                    "thruDate": "2026-12-31",
                    "cagmi": {"memberId": "MBR000"},
                }
            },
        ),
        "claims",
    )
    assert claims["claimList"] == []


async def test_fixture_overrides_world(tmp_path):
    fixtures = tmp_path / "drug-pricing"
    fixtures.mkdir()
    (fixtures / "drugPricing.json").write_text(json.dumps({"source": "override"}))
    app = _app(fixtures_dir=tmp_path, world_dir=_WORLD)
    payload = _data(
        await _operation(app, "drug-pricing", "drugPricing", {}),
        "drugPricing",
    )
    assert payload == {"source": "override"}

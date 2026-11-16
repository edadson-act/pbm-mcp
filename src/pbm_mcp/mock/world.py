"""Compose allowlisted reads from the fictional demo world.

A fixture file still wins over this module. Operations this module does not
know are left to the schema generator. Date ranges are not filters.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_WORLD_DIR = Path("mocks/world")

_FILES = (
    "member.json",
    "drugs.json",
    "claims.json",
    "pharmacies.json",
    "coverage.json",
)

_MEMBER_IDS = frozenset({"memberId"})
_FIRST_NAMES = frozenset({"firstName", "memberFName"})
_LAST_NAMES = frozenset({"lastName", "memberLName"})
_UUIDS = frozenset({"uuid"})
_DOBS = frozenset({"dateOfBirth", "memberDOB"})
_DRUG_SCALARS = frozenset(
    {
        "queryTerm",
        "drugName",
        "medicationName",
        "ndc",
        "gpi",
        "gpi10",
        "gpi14",
        "productId",
        "productName",
    }
)
_DRUG_LISTS = frozenset({"drugs"})
_CLAIM_NOT_FOUND = "Claim not found."


class WorldError(ValueError):
    """Demo world files are present but cannot be used."""


@dataclass(frozen=True)
class World:
    """One fictional member, the demo catalog, and that member's claims."""

    member: dict[str, Any]
    drugs: tuple[dict[str, Any], ...]
    claims: tuple[dict[str, Any], ...]
    pharmacies: tuple[dict[str, Any], ...]
    coverage: dict[str, Any]

    def drug(self, drug_id: str) -> dict[str, Any]:
        for drug in self.drugs:
            if drug["id"] == drug_id:
                return drug
        raise WorldError(f"Demo world has no drug {drug_id}.")

    def pharmacy(self, pharmacy_id: str) -> dict[str, Any]:
        for pharmacy in self.pharmacies:
            if pharmacy["id"] == pharmacy_id:
                return pharmacy
        raise WorldError(f"Demo world has no pharmacy {pharmacy_id}.")

    def claim(self, claim_number: str) -> dict[str, Any] | None:
        folded = claim_number.casefold()
        for claim in self.claims:
            if str(claim["claimNumber"]).casefold() == folded:
                return claim
        return None


@dataclass(frozen=True)
class Composed:
    """One operation's demo payload, or a GraphQL error message."""

    handled: bool
    value: Any = None
    error: str | None = None


def load_world(world_dir: Path) -> World | None:
    """Read ``mocks/world``. ``None`` when the directory has no world files."""
    if not world_dir.is_dir():
        return None
    paths = [world_dir / name for name in _FILES]
    if not any(path.is_file() for path in paths):
        return None
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise WorldError("Demo world is missing " + ", ".join(missing) + ".")
    loaded = {path.name: json.loads(path.read_text()) for path in paths}
    _require(isinstance(loaded["member.json"], dict), "member.json must be an object.")
    _require(isinstance(loaded["drugs.json"], list), "drugs.json must be a list.")
    _require(isinstance(loaded["claims.json"], list), "claims.json must be a list.")
    _require(
        isinstance(loaded["pharmacies.json"], list),
        "pharmacies.json must be a list.",
    )
    _require(
        isinstance(loaded["coverage.json"], dict),
        "coverage.json must be an object.",
    )
    world = World(
        member=loaded["member.json"],
        drugs=tuple(loaded["drugs.json"]),
        claims=tuple(loaded["claims.json"]),
        pharmacies=tuple(loaded["pharmacies.json"]),
        coverage=loaded["coverage.json"],
    )
    _validate(world)
    return world


def compose_operation(
    operation_name: str,
    variables: dict[str, Any],
    world: World,
) -> Composed:
    """Build one allowlisted read. ``handled`` is false when this module skips it."""
    builder = _BUILDERS.get(operation_name)
    if builder is None:
        return Composed(handled=False)
    return builder(world, variables or {})


def _validate(world: World) -> None:
    drug_ids = {drug["id"] for drug in world.drugs}
    pharmacy_ids = {pharmacy["id"] for pharmacy in world.pharmacies}
    claim_numbers = {claim["claimNumber"] for claim in world.claims}
    for claim in world.claims:
        number = claim["claimNumber"]
        _require(claim["drugId"] in drug_ids, f"claim {number} uses an unknown drug.")
        _require(
            claim["pharmacyId"] in pharmacy_ids,
            f"claim {number} uses an unknown pharmacy.",
        )
    for drug in world.drugs:
        _require(
            drug["pharmacyId"] in pharmacy_ids,
            f"drug {drug['id']} uses an unknown pharmacy.",
        )
    coverage = world.coverage
    _require(coverage["priorAuth"]["drugId"] in drug_ids, "prior auth drug is unknown.")
    _require(
        coverage["opportunity"]["drugId"] in drug_ids,
        "opportunity drug is unknown.",
    )
    savings = coverage["savings"]
    _require(savings["fromDrugId"] in drug_ids, "savings source drug is unknown.")
    _require(savings["toDrugId"] in drug_ids, "savings target drug is unknown.")
    _require(
        savings["toPharmacyId"] in pharmacy_ids,
        "savings pharmacy is unknown.",
    )
    _require(
        savings["fromClaimNumber"] in claim_numbers,
        "savings claim is unknown.",
    )
    _require(
        world.member["defaultPharmacyId"] in pharmacy_ids,
        "default pharmacy is unknown.",
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WorldError("Demo world " + message)


def _ok(value: Any) -> Composed:
    return Composed(handled=True, value=value)


def _fail(message: str) -> Composed:
    return Composed(handled=True, error=message)


def _member_ok(world: World, variables: dict[str, Any]) -> bool:
    """True when every supplied identifier is Jordan's. Omitted means Jordan."""
    member = world.member
    checks = (
        (_MEMBER_IDS, member["memberId"]),
        (_FIRST_NAMES, member["firstName"]),
        (_LAST_NAMES, member["lastName"]),
        (_UUIDS, member["uuid"]),
        (_DOBS, member["dateOfBirth"]),
    )
    for keys, expected in checks:
        folded = expected.casefold()
        for value in _strings_for(variables, keys):
            if value.casefold() != folded:
                return False
    return True


def _strings_for(variables: dict[str, Any], keys: frozenset[str]) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys and isinstance(value, str) and value.strip():
                    found.append(value.strip())
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(variables)
    return found


def _string_lists_for(variables: dict[str, Any], keys: frozenset[str]) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys and isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item.strip():
                            found.append(item.strip())
                        else:
                            walk(item)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(variables)
    return found


def _drug_needles(variables: dict[str, Any]) -> list[str]:
    return _strings_for(variables, _DRUG_SCALARS) + _string_lists_for(
        variables, _DRUG_LISTS
    )


def _filter_drugs(
    world: World,
    variables: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    scalars = _strings_for(variables, _DRUG_SCALARS)
    listed = _string_lists_for(variables, _DRUG_LISTS)
    selected = list(world.drugs)
    for needle in scalars:
        selected = [drug for drug in selected if _matches_drug(drug, needle)]
    if listed:
        selected = [
            drug
            for drug in selected
            if any(_matches_drug(drug, needle) for needle in listed)
        ]
    return selected, bool(scalars or listed)


def _matches_drug(drug: dict[str, Any], needle: str) -> bool:
    folded = needle.casefold()
    blob = " ".join(
        str(drug[key])
        for key in (
            "id",
            "brandName",
            "genericName",
            "labelName",
            "gpi10",
            "gpi14",
            "ndc",
            "productId",
        )
    ).casefold()
    return folded in blob


def _best_drug(
    drugs: list[dict[str, Any]],
    needles: list[str],
) -> dict[str, Any]:
    def score(drug: dict[str, Any]) -> tuple[int, int]:
        best = 9
        for needle in needles:
            folded = needle.casefold()
            exact = {
                drug["brandName"].casefold(),
                drug["labelName"].casefold(),
                drug["productId"].casefold(),
                drug["ndc"].casefold(),
                drug["gpi14"].casefold(),
            }
            if folded in exact:
                best = min(best, 0)
            elif folded == drug["gpi10"].casefold():
                best = min(best, 1 if drug.get("isBrand") else 2)
            elif (
                folded in drug["brandName"].casefold()
                or folded in drug["labelName"].casefold()
            ):
                best = min(best, 1)
            elif folded in drug["genericName"].casefold():
                best = min(best, 0 if drug.get("isGeneric") else 2)
            else:
                best = min(best, 3)
        return best, 0 if drug.get("isBrand") else 1

    return sorted(drugs, key=score)[0]


def _same_day(left: str, right: str) -> bool:
    return left.strip()[:10] == right.strip()[:10]


def _page(count: int) -> dict[str, int]:
    return {
        "pageNumber": 1,
        "itemsPerPage": count,
        "totalPages": 1 if count else 0,
        "totalItems": count,
    }


def _display_name(drug: dict[str, Any]) -> str:
    if drug.get("isBrand"):
        return str(drug["brandName"])
    return str(drug["genericName"])


def _cagm(world: World) -> dict[str, str]:
    member = world.member
    return {
        "carrierId": member["carrierId"],
        "accountId": member["accountId"],
        "groupId": member["groupId"],
        "memberId": member["memberId"],
    }


def _message(text: str) -> dict[str, str]:
    return {
        "message": text,
        "messagePriorityCd": "1",
        "messageTypeCd": "INFO",
        "phoneNumber": "",
        "url": "",
    }


def _dollars(amount: float) -> str:
    if amount == int(amount):
        return f"${amount:.0f}"
    return f"${amount:.2f}"


def _coverage_note(world: World, drug: dict[str, Any]) -> str:
    prior = world.coverage["priorAuth"]
    return (
        f"Prior authorization {prior['number']} is {prior['status'].lower()}. "
        f"Step therapy with {prior['stepDrug']} is required before "
        f"{drug['brandName']} can be covered."
    )


def _savings_amount(world: World) -> float:
    savings = world.coverage["savings"]
    brand = world.drug(savings["fromDrugId"])
    generic = world.drug(savings["toDrugId"])
    return float(brand["patientPay"]) - float(generic["patientPay"])


def _profile(world: World) -> dict[str, Any]:
    member = world.member
    return {
        "__typename": "ProfileResponse",
        "uuid": member["uuid"],
        "eid": member["eid"],
        "patientId": member["patientId"],
        "partyId": member["partyId"],
        "status": member["status"],
        "demographics": {
            "firstName": member["firstName"],
            "middleName": "",
            "lastName": member["lastName"],
            "dateOfBirth": member["dateOfBirth"],
            "gender": member["gender"],
            "address1": member["address1"],
            "city": member["city"],
            "state": member["state"],
            "zip": member["zip"],
        },
        "population": member["population"],
        "carrierId": member["carrierId"],
        "accountId": member["accountId"],
        "groupId": member["groupId"],
        "memberId": member["memberId"],
        "familyId": member["familyId"],
        "planId": member["planId"],
        "planName": member["planName"],
        "memberEffectiveDate": member["memberEffectiveDate"],
        "memberEligibilityEndDate": member["memberEligibilityEndDate"],
        "planEffectiveDate": member["planEffectiveDate"],
        "relationshipCode": member["relationship"],
        "isPartD": member["isPartD"],
        "hasSpecialtyCoverage": member["hasSpecialtyCoverage"],
        "carrierName": member["carrierName"],
        "accountName": member["accountName"],
        "planType": member["planType"],
        "retailOnly": member["retailOnly"],
    }


def _not_found_member() -> dict[str, str]:
    return {
        "__typename": "CustomError",
        "errorCode": "MEMBER_NOT_FOUND",
        "errorMessage": "Member not found.",
        "errorDetails": "No demo member matches that identifier.",
        "requestId": "demo-request",
        "timestamp": "2026-11-12T00:00:00Z",
    }


def _user_profile(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok(_not_found_member())
    return _ok(_profile(world))


def _search_user_profile(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok(None)
    return _ok(_profile(world))


def _session(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok(None)
    supplied = _strings_for(variables, frozenset({"sessionId"}))
    session_id = supplied[0] if supplied else world.member["sessionId"]
    return _ok(
        {
            "id": session_id,
            "skylineToken": "demo-skyline-token",
            "profileToken": "demo-profile-token",
            "pspToken": "demo-psp-token",
        }
    )


def _drug_search_row(drug: dict[str, Any]) -> dict[str, str]:
    return {
        "productNameOverride": drug["brandName"],
        "productName": drug["labelName"],
        "gpi10": drug["gpi10"],
        "productId": drug["productId"],
    }


def _drug_search(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok({"drugs": []})
    selected, _active = _filter_drugs(world, variables)
    return _ok({"drugs": [_drug_search_row(drug) for drug in selected]})


def _drug_forms(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok({"gpi10": "", "forms": []})
    selected, active = _filter_drugs(world, variables)
    if not active or not selected:
        return _ok({"gpi10": "", "forms": []})
    target = _best_drug(selected, _drug_needles(variables))
    forms: list[dict[str, Any]] = []
    seen: set[str] = set()
    for drug in selected:
        if drug["gpi10"] != target["gpi10"]:
            continue
        form = str(drug["dosageForm"])
        if form in seen:
            continue
        seen.add(form)
        forms.append({"form": form, "isCommonForm": True, "products": []})
    return _ok({"gpi10": target["gpi10"], "forms": forms})


def _drug_info(world: World, variables: dict[str, Any]) -> Composed:
    empty = {
        "names": [],
        "commonUses": [],
        "instructions": [],
        "cautions": [],
        "sideEffects": [],
        "beforeUsing": [],
        "overdose": [],
        "additionalInfo": [],
    }
    if not _member_ok(world, variables):
        return _ok(empty)
    selected, active = _filter_drugs(world, variables)
    if not active or not selected:
        return _ok(empty)
    target = _best_drug(selected, _drug_needles(variables))
    family = [drug for drug in selected if drug["gpi10"] == target["gpi10"]]
    source = next((drug for drug in family if drug.get("isGeneric")), family[0])
    info = source.get("info") or {}
    names: list[str] = []
    for drug in family:
        for name in (drug["brandName"], drug["genericName"]):
            if name not in names:
                names.append(name)
    return _ok(
        {
            "names": names,
            "commonUses": list(info.get("commonUses") or []),
            "instructions": list(info.get("instructions") or []),
            "cautions": list(info.get("cautions") or []),
            "sideEffects": list(info.get("sideEffects") or []),
            "beforeUsing": list(info.get("beforeUsing") or []),
            "overdose": list(info.get("overdose") or []),
            "additionalInfo": list(info.get("additionalInfo") or []),
        }
    )


def _named_drugs(world: World, variables: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Catalog rows after member and drug filters. ``None`` hides the member."""
    if not _member_ok(world, variables):
        return None
    selected, _active = _filter_drugs(world, variables)
    letters = _strings_for(variables, frozenset({"alphabet"}))
    if letters:
        prefix = letters[0].casefold()
        selected = [
            drug
            for drug in selected
            if _display_name(drug).casefold().startswith(prefix)
        ]
    subclass = _strings_for(variables, frozenset({"therapeuticSubClass"}))
    if subclass:
        selected = [
            drug
            for drug in selected
            if any(
                needle.casefold() in drug["therapeuticSubClass"].casefold()
                for needle in subclass
            )
        ]
    return selected


def _drug_list(drugs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "items": [{"drugName": _display_name(drug)} for drug in drugs],
        "pageInfo": _page(len(drugs)),
    }


def _drugs_by_alphabet(world: World, variables: dict[str, Any]) -> Composed:
    drugs = _named_drugs(world, variables)
    return _ok(_drug_list([] if drugs is None else drugs))


def _drugs_by_name(world: World, variables: dict[str, Any]) -> Composed:
    return _drugs_by_alphabet(world, variables)


def _drug_result_row(drug: dict[str, Any]) -> dict[str, Any]:
    return {
        "productId": drug["productId"],
        "brandName": drug["brandName"],
        "genericName": drug["genericName"],
        "isBrandedDrug": bool(drug["isBrand"]),
        "drugStrength": drug["strength"],
        "formularyTier": drug["tier"],
        "requiresPriorAuthorization": bool(drug["requiresPriorAuthorization"]),
        "hasStepTherapy": bool(drug["requiresStepTherapy"]),
        "hasQuantityLimit": bool(drug["hasQuantityLimit"]),
        "isSpecialtyPharmacyDrug": bool(drug["isSpecialty"]),
        "cmsClassification": drug["cmsClassification"],
    }


def _drug_results(world: World, variables: dict[str, Any]) -> Composed:
    drugs = _named_drugs(world, variables)
    rows = [] if drugs is None else drugs
    return _ok(
        {
            "items": [_drug_result_row(drug) for drug in rows],
            "pageInfo": _page(len(rows)),
        }
    )


def _drug_details_body(world: World, drug: dict[str, Any]) -> dict[str, Any]:
    alternatives = [
        other["genericName"] if drug.get("isBrand") else other["brandName"]
        for other in world.drugs
        if other["id"] != drug["id"] and other["gpi10"] == drug["gpi10"]
    ]
    note = _coverage_note(world, drug) if drug["requiresPriorAuthorization"] else ""
    step = ""
    if drug["requiresStepTherapy"]:
        step = (
            f"{world.coverage['priorAuth']['stepDrug']} is required "
            "before this drug."
        )
    return {
        "productId": drug["productId"],
        "isBrandedDrug": bool(drug["isBrand"]),
        "brandName": drug["brandName"],
        "genericName": drug["genericName"],
        "drugStrength": drug["strength"],
        "drugStrengthDesc": drug["strength"],
        "drugStrengthFinal": drug["strength"],
        "hasQuantityLimit": bool(drug["hasQuantityLimit"]),
        "requiresPriorAuthorization": bool(drug["requiresPriorAuthorization"]),
        "priorAuthorizationNote": note,
        "priorAuthorizationFinalStatus": (
            world.coverage["priorAuth"]["status"]
            if drug["requiresPriorAuthorization"]
            else ""
        ),
        "memberNote": note,
        "requiresStepTherapy": bool(drug["requiresStepTherapy"]),
        "stepTherapyNote": step,
        "therapeuticClass": drug["therapeuticClass"],
        "therapeuticSubClass": drug["therapeuticSubClass"],
        "formularyTier": drug["tier"],
        "isSpecialtyDrug": bool(drug["isSpecialty"]),
        "specialtyDrugNote": "Specialty pharmacy drug." if drug["isSpecialty"] else "",
        "alternativeDrugs": alternatives,
        "isExcludedFromCoverage": False,
        "gpi14": drug["gpi14"],
        "productIdQualifer": "NDC",
    }


def _pick_drug(
    world: World,
    variables: dict[str, Any],
    *,
    fallback_id: str | None,
) -> dict[str, Any] | None:
    if not _member_ok(world, variables):
        return None
    selected, active = _filter_drugs(world, variables)
    if not active:
        if fallback_id is None:
            return None
        return world.drug(fallback_id)
    if not selected:
        return None
    return _best_drug(selected, _drug_needles(variables))


def _drug_details(world: World, variables: dict[str, Any]) -> Composed:
    drug = _pick_drug(world, variables, fallback_id=None)
    if drug is None:
        return _ok(None)
    return _ok(_drug_details_body(world, drug))


def _formulary(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok({"items": []})
    member = world.member
    return _ok(
        {
            "items": [
                {
                    "formularyCode": member["formularyCode"],
                    "formularyName": member["formularyName"],
                    "formularyType": member["formularyType"],
                    "use": "Pharmacy",
                    "type": member["formularyType"],
                    "status": "Active",
                }
            ]
        }
    )


def _therapeutic_classes(world: World, variables: dict[str, Any]) -> Composed:
    drugs = _named_drugs(world, variables)
    grouped: dict[str, list[str]] = {}
    for drug in drugs or []:
        subclasses = grouped.setdefault(drug["therapeuticClass"], [])
        if drug["therapeuticSubClass"] not in subclasses:
            subclasses.append(drug["therapeuticSubClass"])
    items = [
        {"therapeuticClass": name, "subClasses": subclasses}
        for name, subclasses in grouped.items()
    ]
    return _ok({"items": items, "pageInfo": _page(len(items))})


def _therapeutic_subclass_summary(world: World, variables: dict[str, Any]) -> Composed:
    drugs = _named_drugs(world, variables) or []
    summary = [
        {
            "brandName": drug["brandName"],
            "genericName": drug["genericName"],
            "isBrandedDrug": bool(drug["isBrand"]),
            "cmsClassification": drug["cmsClassification"],
        }
        for drug in drugs
    ]
    return _ok({"drugSummary": summary, "pageInfo": _page(len(summary))})


def _pa_criteria(world: World, variables: dict[str, Any]) -> Composed:
    drug = _pick_drug(world, variables, fallback_id="humira")
    if drug is None:
        return _ok({"pageInfo": _page(0), "paCriteria": None})
    groups: list[dict[str, Any]] = []
    if drug["requiresPriorAuthorization"]:
        prior = world.coverage["priorAuth"]
        groups.append(
            {
                "groupName": "Prior authorization",
                "authorizationCriteria": [
                    {
                        "description": "Prior authorization status",
                        "value": f"{prior['number']} is {prior['status']}.",
                    }
                ],
            }
        )
    return _ok(
        {
            "pageInfo": _page(1),
            "paCriteria": {
                "formularyCode": world.member["formularyCode"],
                "productId": drug["productId"],
                "brandName": drug["brandName"],
                "genericName": drug["genericName"],
                "dosageStrength": drug["strength"],
                "formularyTierDesc": drug["tierDesc"],
                "authorizationGroups": groups,
            },
        }
    )


def _step_therapy(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok(
            {
                "formularyCode": "",
                "productId": "",
                "brandName": "",
                "genericName": "",
                "dosageStrengthFinal": "",
                "formularyTierDesc": "",
                "stepTherapyGroup": [],
                "PageInfo": _page(0),
            }
        )
    drug = _pick_drug(world, variables, fallback_id="humira")
    groups: list[dict[str, Any]] = []
    if drug is not None and drug["requiresStepTherapy"]:
        prior = world.coverage["priorAuth"]
        groups = [
            {
                "stepNumber": "1",
                "groupName": prior["stepDrug"],
                "stepTherapyCriteria": [
                    {"description": "Required first", "value": prior["stepDrug"]}
                ],
            },
            {
                "stepNumber": "2",
                "groupName": drug["brandName"],
                "stepTherapyCriteria": [
                    {
                        "description": "Covered after the first step",
                        "value": drug["genericName"],
                    }
                ],
            },
        ]
    product = drug or {}
    return _ok(
        {
            "formularyCode": world.member["formularyCode"],
            "productId": product.get("productId", ""),
            "brandName": product.get("brandName", ""),
            "genericName": product.get("genericName", ""),
            "dosageStrengthFinal": product.get("strength", ""),
            "formularyTierDesc": product.get("tierDesc", ""),
            "stepTherapyGroup": groups,
            "PageInfo": _page(len(groups)),
        }
    )


def _claim_drug(drug: dict[str, Any]) -> dict[str, Any]:
    return {
        "gpi": drug["gpi14"],
        "productName": drug["labelName"],
        "strength": drug["strength"],
        "dosageForm": drug["dosageForm"],
        "brandName": drug["brandName"],
        "genericName": drug["genericName"],
        "multisourceCode": bool(drug["isGeneric"]),
        "productNameAbbrev": drug["labelName"],
        "productIdQualifier": "NDC",
    }


def _claim_pharmacy(pharmacy: dict[str, Any]) -> dict[str, str]:
    return {
        "pharmacyFullName": pharmacy["name"],
        "pharmacyAddress1": pharmacy["address1"],
        "pharmacyAddress2": "",
        "pharmacyCity": pharmacy["city"],
        "pharmacyState": pharmacy["state"],
        "pharmacyZip": pharmacy["zip"],
    }


def _claim_prescriber(world: World) -> dict[str, str]:
    prescriber = world.member["prescriber"]
    return {
        "prescriberFirstName": prescriber["firstName"],
        "prescriberLastName": prescriber["lastName"],
        "prescriberMiddleName": "",
        "prescriberAddress1": prescriber["address1"],
        "prescriberAddress2": "",
        "prescriberCity": prescriber["city"],
        "prescriberState": prescriber["state"],
        "prescriberZip": prescriber["zip"],
        "phoneNumber": prescriber["phone"],
        "prescriberId": prescriber["id"],
    }


def _reject(world: World, claim: dict[str, Any], drug: dict[str, Any]) -> dict[str, Any]:
    if not claim.get("rejected"):
        return {
            "rejectCode": [],
            "rejectCodeDescription": [],
            "rejectMessage": [],
        }
    code = str(claim.get("rejectCode") or "75")
    description = str(claim.get("rejectDescription") or "Prior authorization required")
    return {
        "rejectCode": [code],
        "rejectCodeDescription": [{"code": code, "description": description}],
        "rejectMessage": [
            {
                "messageSequence": 1,
                "message": _coverage_note(world, drug),
                "messageCode": code,
            }
        ],
    }


def _payment(claim: dict[str, Any]) -> dict[str, float]:
    patient = float(claim["patientPaid"])
    return {
        "patientPaid": patient,
        "planPaid": float(claim["planPaid"]),
        "amountBilled": float(claim["amountBilled"]),
        "productSelectAmount": 0.0,
        "exceedMaximum": 0.0,
        "taxCollected": 0.0,
        "flatCopayAmount": patient,
        "copayDiscount": 0.0,
        "costDiff": 0.0,
    }


def _product(drug: dict[str, Any]) -> dict[str, str]:
    route = "Oral" if drug["dosageForm"] == "tablet" else "Subcutaneous"
    return {
        "productId": drug["productId"],
        "productIdQualifier": "NDC",
        "productKey": drug["ndc"],
        "productNameAbbrev": drug["labelName"],
        "productNameExt": drug["labelName"],
        "gpi": drug["gpi14"],
        "multisourceCode": "Y" if drug["isGeneric"] else "N",
        "maintenanceIndicator": "N" if drug["isSpecialty"] else "Y",
        "routeOfAdmin": route.casefold(),
        "routeOfAdminDesc": route,
        "unitOfMeasure": "EA",
    }


def _claim_core(
    world: World,
    claim: dict[str, Any],
) -> dict[str, Any]:
    drug = world.drug(claim["drugId"])
    pharmacy = world.pharmacy(claim["pharmacyId"])
    return {
        "general": {
            "claimNumber": claim["claimNumber"],
            "processedDate": claim["processedDate"],
            "daysSupply": claim["daysSupply"],
            "isEspClaim": False,
            "isDiscounted": False,
            "claimSearchType": claim["status"],
            "isCostChange": False,
            "fillDate": claim["fillDate"],
            "quantityDispensed": claim["quantity"],
            "isPriceEdgeApplied": False,
            "rxNumber": claim["rxNumber"],
        },
        "drug": _claim_drug(drug),
        "prescription": {"rxNumber": claim["rxNumber"]},
        "payment": _payment(claim),
        "pharmacy": _claim_pharmacy(pharmacy),
        "prescriber": _claim_prescriber(world),
    }


def _history_claim(world: World, claim: dict[str, Any]) -> dict[str, Any]:
    drug = world.drug(claim["drugId"])
    body = _claim_core(world, claim)
    member = world.member
    body["member"] = {
        "memberFirstName": member["firstName"],
        "memberLastName": member["lastName"],
    }
    body["rejectInformation"] = _reject(world, claim, drug)
    return body


def _current_claim(world: World, claim: dict[str, Any]) -> dict[str, Any]:
    body = _claim_core(world, claim)
    body["product"] = _product(world.drug(claim["drugId"]))
    return body


def _selected_claims(
    world: World,
    variables: dict[str, Any],
) -> list[dict[str, Any]] | None:
    if not _member_ok(world, variables):
        return None
    selected, active = _filter_drugs(world, variables)
    if not active:
        return list(world.claims)
    ids = {drug["id"] for drug in selected}
    return [claim for claim in world.claims if claim["drugId"] in ids]


def _empty_claims() -> dict[str, Any]:
    return {
        "claimList": [],
        "pagination": {
            "totalItems": 0,
            "totalPatientPaid": 0.0,
            "showTotalPatientPaid": True,
        },
    }


def _claims(world: World, variables: dict[str, Any]) -> Composed:
    claims = _selected_claims(world, variables)
    if claims is None:
        return _ok(_empty_claims())
    paid = sum(float(claim["patientPaid"]) for claim in claims)
    return _ok(
        {
            "claimList": [_history_claim(world, claim) for claim in claims],
            "pagination": {
                "totalItems": len(claims),
                "totalPatientPaid": paid,
                "showTotalPatientPaid": True,
            },
        }
    )


def _current_prescriptions(world: World, variables: dict[str, Any]) -> Composed:
    claims = _selected_claims(world, variables)
    if not claims:
        return _ok({"claimList": []})
    return _ok({"claimList": [_current_claim(world, claim) for claim in claims]})


def _claim_details(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _fail(_CLAIM_NOT_FOUND)
    fills = _strings_for(variables, frozenset({"fillDate"}))
    gpis = _strings_for(variables, frozenset({"gpi", "gpi10", "gpi14"}))
    numbers = _strings_for(variables, frozenset({"rxClaimNumber", "claimNumber"}))
    if not fills or not gpis or not numbers:
        return _fail(_CLAIM_NOT_FOUND)
    for claim in world.claims:
        drug = world.drug(claim["drugId"])
        gpi_ok = gpis[0].casefold() in {
            str(drug["gpi14"]).casefold(),
            str(drug["gpi10"]).casefold(),
        }
        number_ok = numbers[0].casefold() == str(claim["claimNumber"]).casefold()
        if _same_day(fills[0], claim["fillDate"]) and gpi_ok and number_ok:
            return _ok({"claimDetails": _history_claim(world, claim)})
    return _fail(_CLAIM_NOT_FOUND)


def _product_search(world: World, variables: dict[str, Any]) -> Composed:
    drugs = _named_drugs(world, variables)
    if drugs is None:
        return _ok([])
    return _ok([_product(drug) for drug in drugs])


def _alternate_pharmacy(pharmacy: dict[str, Any]) -> dict[str, str]:
    return {
        "pharmacyId": pharmacy["npi"],
        "pharmacyName": pharmacy["name"],
        "ncpdp": pharmacy["ncpdp"],
        "address1": pharmacy["address1"],
        "address2": "",
        "city": pharmacy["city"],
        "county": pharmacy["county"],
        "state": pharmacy["state"],
        "zipCd": pharmacy["zip"],
        "phone": pharmacy["phone"],
        "directionsLink": "",
    }


def _recommendation(world: World) -> dict[str, Any]:
    savings = world.coverage["savings"]
    claim = world.claim(savings["fromClaimNumber"])
    if claim is None:
        raise WorldError("Demo world savings claim is unknown.")
    brand = world.drug(savings["fromDrugId"])
    generic = world.drug(savings["toDrugId"])
    pharmacy = world.pharmacy(claim["pharmacyId"])
    alternate = world.pharmacy(savings["toPharmacyId"])
    prescriber = world.member["prescriber"]
    save = _savings_amount(world)
    days = int(claim["daysSupply"]) or 1
    message = (
        f"Generic {generic['labelName']} at {alternate['name']} would cost "
        f"{_dollars(float(generic['patientPay']))}, about {_dollars(save)} less "
        f"than {brand['brandName']}."
    )
    return {
        "documentId": savings["documentId"],
        "recommendationId": savings["recommendationId"],
        "recommendationType": savings["recommendationType"],
        "trialTransactionMessages": [message],
        "claim": {
            "claimNumber": claim["claimNumber"],
            "claimSequenceNumber": "1",
            "rxNumber": claim["rxNumber"],
            "fillDate": claim["fillDate"],
            "sourceSystemCode": "demo",
            "sourceSystemInstance": "DEMO",
            "LOB": "Commercial",
        },
        "cagm": _cagm(world),
        "prescriber": {
            "prescriberId": prescriber["id"],
            "prescriberIdQualifier": "NPI",
            "prescriberFirstName": prescriber["firstName"],
            "prescriberLastName": prescriber["lastName"],
        },
        "pharmacy": {
            "pharmacyId": pharmacy["npi"],
            "pharmacyName": pharmacy["name"],
            "pharmacyIdQualifier": "NPI",
            "ncpdp": pharmacy["ncpdp"],
            "phone": pharmacy["phone"],
        },
        "product": {
            "labelName": brand["labelName"],
            "gpi": brand["gpi14"],
            "msc": "N" if brand.get("isBrand") else "Y",
            "ndc": brand["ndc"],
            "daysSupply": claim["daysSupply"],
            "quantityDispensed": claim["quantity"],
            "tierIdentifier": int(brand["tier"]),
        },
        "paidAmounts": {
            "patientPay": float(claim["patientPaid"]),
            "patientPayPerDay": round(float(claim["patientPaid"]) / days, 2),
            "planPay": float(claim["planPaid"]),
            "planPayPerDay": round(float(claim["planPaid"]) / days, 2),
        },
        "pharmacyDetails": [_pharmacy_detail(alternate)],
        "costSavings": [
            {
                "recommendationId": savings["recommendationId"],
                "recordIdentifier": "1",
                "priorityOrderNo": 1,
                "trialTransactionMessages": [message],
                "savingsOpportunityType": ["GENERIC"],
                "alternatePharmacy": _alternate_pharmacy(alternate),
                "alternateMedication": {
                    "labelName": generic["labelName"],
                    "gpi": generic["gpi14"],
                    "msc": "Y",
                    "ndc": generic["ndc"],
                    "daysSupply": claim["daysSupply"],
                    "quantityDispensed": claim["quantity"],
                },
                "alternatePaid": {
                    "patientPay": float(generic["patientPay"]),
                    "patientPayPerDay": round(float(generic["patientPay"]) / days, 2),
                    "planPay": float(generic["planPay"]),
                    "planPayPerDay": round(float(generic["planPay"]) / days, 2),
                },
                "alternateSavings": {
                    "patientSave": save,
                    "patientMonthlySave": save,
                    "patientSavePerDay": round(save / days, 2),
                    "planSave": float(brand["planPay"]) - float(generic["planPay"]),
                    "planSavePerDay": round(
                        (float(brand["planPay"]) - float(generic["planPay"])) / days,
                        2,
                    ),
                    "planMonthlySave": (
                        float(brand["planPay"]) - float(generic["planPay"])
                    ),
                },
            }
        ],
        "convenienceSavings": [],
    }


def _recommendations(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok({"recommendations": []})
    savings = world.coverage["savings"]
    selected, active = _filter_drugs(world, variables)
    if active:
        ids = {drug["id"] for drug in selected}
        if savings["fromDrugId"] not in ids and savings["toDrugId"] not in ids:
            return _ok({"recommendations": []})
    return _ok({"recommendations": [_recommendation(world)]})


def _prescriber_details(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok(None)
    numbers = _strings_for(variables, frozenset({"rxClaimNumber", "claimNumber"}))
    if numbers:
        claim = world.claim(numbers[0])
        if claim is None:
            return _ok(None)
    else:
        claim = world.claim(world.coverage["savings"]["fromClaimNumber"])
    if claim is None:
        return _ok(None)
    member = world.member
    prescriber = member["prescriber"]
    return _ok(
        {
            "claimNumber": claim["claimNumber"],
            "claimSequenceNumber": "1",
            "claimStatus": claim["status"],
            "carrierId": member["carrierId"],
            "accountId": member["accountId"],
            "groupId": member["groupId"],
            "memberId": member["memberId"],
            "prescriberId": prescriber["id"],
            "prescriberLastName": prescriber["lastName"],
            "prescriberFirstName": prescriber["firstName"],
            "prescriberAddress1": prescriber["address1"],
            "prescriberAddress2": "",
            "prescriberCity": prescriber["city"],
            "prescriberState": prescriber["state"],
            "prescriberZip": prescriber["zip"],
            "prescriberPhone1": prescriber["phone"],
            "rxNumber": claim["rxNumber"],
        }
    )


def _pharmacy_detail(pharmacy: dict[str, Any]) -> dict[str, Any]:
    return {
        "npi": pharmacy["npi"],
        "ncpdp": pharmacy["ncpdp"],
        "name": pharmacy["name"],
        "address1": pharmacy["address1"],
        "city": pharmacy["city"],
        "county": pharmacy["county"],
        "state": pharmacy["state"],
        "zipCd": pharmacy["zip"],
        "phoneNumber": pharmacy["phone"],
        "distance": pharmacy["distance"],
    }


def _pharmacy_row(pharmacy: dict[str, Any]) -> dict[str, Any]:
    preferred = bool(pharmacy["preferred"])
    return {
        "npi": pharmacy["npi"],
        "nabp": pharmacy["ncpdp"],
        "name": pharmacy["name"],
        "addressLine1": pharmacy["address1"],
        "addressLine2": "",
        "city": pharmacy["city"],
        "county": pharmacy["county"],
        "state": pharmacy["state"],
        "zip": pharmacy["zip"],
        "distance": pharmacy["distance"],
        "phone": pharmacy["phone"],
        "isInNetwork": True,
        "preferredPharmacy": preferred,
        "networkParticipation": "Preferred" if preferred else "In network",
        "open24Hours": False,
    }


def _matching_pharmacies(
    world: World,
    variables: dict[str, Any],
) -> list[dict[str, Any]]:
    names = [value.casefold() for value in _strings_for(variables, frozenset({"pharmacyName"}))]
    npis = {value.casefold() for value in _strings_for(variables, frozenset({"npi"}))}
    ncpdps = {value.casefold() for value in _strings_for(variables, frozenset({"ncpdp"}))}
    matched = []
    for pharmacy in world.pharmacies:
        if names and not any(name in pharmacy["name"].casefold() for name in names):
            continue
        if npis and pharmacy["npi"].casefold() not in npis:
            continue
        if ncpdps and pharmacy["ncpdp"].casefold() not in ncpdps:
            continue
        matched.append(pharmacy)
    return sorted(
        matched,
        key=lambda pharmacy: (not pharmacy["preferred"], pharmacy["distance"]),
    )


def _default_pharmacy(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok({"npi": None, "uuid": None})
    pharmacy = world.pharmacy(world.member["defaultPharmacyId"])
    return _ok({"npi": pharmacy["npi"], "uuid": world.member["uuid"]})


def _plans(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok([])
    member = world.member
    return _ok(
        [
            {
                "countyName": "Travis",
                "plans": [
                    {
                        "planId": 2026,
                        "planYear": 2026,
                        "planName": member["planName"],
                        "contract": "DEMO",
                        "pbp": "001",
                        "segment": "000",
                        "planEffectiveDate": member["planEffectiveDate"],
                    }
                ],
            }
        ]
    )


def _pharmacy_search(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        pharmacies: list[dict[str, Any]] = []
        message = "Member not found."
    else:
        pharmacies = [
            _pharmacy_row(pharmacy)
            for pharmacy in _matching_pharmacies(world, variables)
        ]
        message = ""
    return _ok(
        {
            "status": "SUCCESS",
            "message": message,
            "datasource": "demo",
            "pagination": {
                "totalItems": len(pharmacies),
                "itemsPerPage": len(pharmacies),
                "totalPages": 1 if pharmacies else 0,
                "pageNumber": 1,
                "sortOrder": "preferred",
            },
            "pharmacies": pharmacies,
        }
    )


def _accumulator_summary(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok(None)
    accumulators = world.coverage["accumulators"]
    return _ok(
        {
            "__typename": "CommSummary",
            "isIndividualExist": True,
            "isFamilyExist": False,
            "individual": {
                "phaseKey": accumulators["phaseKey"],
                "deductible": dict(accumulators["deductible"]),
                "outOfPocket": dict(accumulators["outOfPocket"]),
            },
            "family": None,
        }
    )


def _history(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok([])
    prior = world.coverage["priorAuth"]
    drug = world.drug(prior["drugId"])
    selected, active = _filter_drugs(world, variables)
    if active and drug["id"] not in {item["id"] for item in selected}:
        return _ok([])
    prescriber = world.member["prescriber"]
    return _ok(
        [
            {
                "sourceSystem": prior["sourceSystem"],
                "priorAuthNumber": prior["number"],
                "priorAuthStatus": prior["status"],
                "productId": drug["productId"],
                "productName": drug["labelName"],
                "requestDate": prior["requestDate"],
                "decisionDate": "",
                "expirationDate": "",
                "prescriberName": f"{prescriber['firstName']} {prescriber['lastName']}",
                "prescriberPhone": prescriber["phone"],
                "gpi14": drug["gpi14"],
            }
        ]
    )


def _contact_details(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok([])
    contact = world.coverage["priorAuthContact"]
    return _ok(
        [
            {
                "address1": contact["address1"],
                "address2": contact["address2"],
                "city": contact["city"],
                "state": contact["state"],
                "zip": contact["zip"],
                "phone": contact["phone"],
                "Email": contact["email"],
                "companyName": contact["companyName"],
                "contactType": contact["contactType"],
                "Department": contact["department"],
            }
        ]
    )


def _drug_info_block(drug: dict[str, Any]) -> dict[str, Any]:
    return {
        "gpi14": drug["gpi14"],
        "labelName": drug["labelName"],
        "productId": drug["productId"],
        "productIdQlfrCd": "NDC",
        "isGeneric": bool(drug["isGeneric"]),
        "tierValue": drug["tier"],
        "tierDesc": drug["tierDesc"],
        "attributes": [],
    }


def _price_row(
    world: World,
    drug: dict[str, Any],
    pharmacy: dict[str, Any],
) -> dict[str, Any]:
    rejected = drug["claimStatus"] == "Rejected"
    rejects = []
    if rejected:
        rejects.append(
            {"rejectCd": "75", "rejectDesc": "Prior authorization required"}
        )
    return {
        "gpi14": drug["gpi14"],
        "labelName": drug["labelName"],
        "productId": drug["productId"],
        "productIdQlfrCd": "NDC",
        "claimStatusCd": drug["claimStatus"],
        "daysSupply": drug["daysSupply"],
        "inNetworkInd": True,
        "multiSourceCd": "Y" if drug["isGeneric"] else "N",
        "ncpdpRejects": rejects,
        "patientPayAmt": float(drug["patientPay"]),
        "pharmacyName": pharmacy["name"],
        "pharmacyPhone": pharmacy["phone"],
        "pharmacyId": pharmacy["npi"],
        "ncpdp": pharmacy["ncpdp"],
        "pharmacyAddress": (
            f"{pharmacy['address1']}, {pharmacy['city']}, "
            f"{pharmacy['state']} {pharmacy['zip']}"
        ),
        "distance": pharmacy["distance"],
        "planPayAmt": float(drug["planPay"]),
        "preferredInd": bool(pharmacy["preferred"]),
        "quantity": float(drug["quantity"]),
    }


def _pricing_empty(message: str) -> dict[str, Any]:
    return {
        "header": {
            "correlationId": "demo-pricing",
            "statusCd": "NO_RESULTS",
            "txnId": "demo-txn",
        },
        "overallMessages": [_message(message)],
        "topResult": None,
        "searchedDrugResult": None,
        "genericDrugResults": [],
        "alternativeDrugResults": None,
    }


def _generic_sibling(world: World, drug: dict[str, Any]) -> dict[str, Any] | None:
    if drug.get("isGeneric"):
        return None
    for other in world.drugs:
        if other.get("isGeneric") and other["gpi10"] == drug["gpi10"]:
            return other
    return None


def _drug_pricing(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok(_pricing_empty("No pricing found for that member."))
    selected, active = _filter_drugs(world, variables)
    if not active or not selected:
        return _ok(_pricing_empty("No pricing found for that drug."))
    drug = _best_drug(selected, _drug_needles(variables))
    pharmacy = world.pharmacy(drug["pharmacyId"])
    price = _price_row(world, drug, pharmacy)
    messages = []
    generic_rows: list[dict[str, Any]] = []
    alternative = None
    sibling = _generic_sibling(world, drug)
    if sibling is not None:
        sibling_pharmacy = world.pharmacy(sibling["pharmacyId"])
        save = float(drug["patientPay"]) - float(sibling["patientPay"])
        messages.append(
            _message(
                f"Generic {sibling['labelName']} at {sibling_pharmacy['name']} "
                f"would cost {_dollars(float(sibling['patientPay']))}, about "
                f"{_dollars(save)} less than {drug['brandName']}."
            )
        )
        generic_rows.append(
            {
                "drugInfo": _drug_info_block(sibling),
                "priceAndPharmacyInfo": [
                    _price_row(world, sibling, sibling_pharmacy)
                ],
            }
        )
        alternative = {
            "priceInfo": {
                "minPrice": float(sibling["patientPay"]),
                "daysSupply": sibling["daysSupply"],
            },
            "alternativeDrugs": [],
        }
    elif drug["claimStatus"] == "Rejected":
        messages.append(_message(_coverage_note(world, drug)))
    else:
        messages.append(
            _message(
                f"{drug['labelName']} is {_dollars(float(drug['patientPay']))} "
                f"at {pharmacy['name']}."
            )
        )
    return _ok(
        {
            "header": {
                "correlationId": "demo-pricing",
                "statusCd": "OK",
                "txnId": "demo-txn",
            },
            "overallMessages": messages,
            "topResult": {
                "drugInfo": _drug_info_block(drug),
                "priceAndPharmacyInfo": price,
            },
            "searchedDrugResult": {
                "drugInfo": _drug_info_block(drug),
                "priceAndPharmacyInfo": [price],
            },
            "genericDrugResults": generic_rows,
            "alternativeDrugResults": alternative,
        }
    )


def _fetch_id_card(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok(None)
    member = world.member
    card = member["idCard"]
    return _ok(
        {
            "entityId": member["memberId"],
            "rxBin": card["rxBin"],
            "rxPcn": card["rxPcn"],
            "rxGrp": card["rxGrp"],
            "issuerName": card["issuerName"],
            "requestIdCardIndicator": False,
            "subscriberIdCardIndicator": True,
            "telephoneNumber": member["servicePhone"],
            "rxClaimPlatformId": card["rxClaimPlatformId"],
            "carrierId": member["carrierId"],
            "accountId": member["accountId"],
            "groupId": member["groupId"],
        }
    )


def _digital_id_card(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok(None)
    return _ok({"walletPassData": "demo-wallet-pass-jordan-hale"})


def _mail_service(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok(None)
    mail = world.coverage["mailService"]
    return _ok(
        {
            "intentionallyLeftBlank": False,
            "mailServiceProgram": mail["mailServiceProgram"],
            "mandatoryMailApply": mail["mandatoryMailApply"],
            "numberOfFills": mail["numberOfFills"],
            "numberOfDays": mail["numberOfDays"],
            "note": mail["note"],
            "portalOptOutInd": False,
            "effectiveDate": mail["effectiveDate"],
            "endDate": mail["endDate"],
        }
    )


def _member_consent(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok([])
    consent = world.coverage["consent"]
    requested = _strings_for(variables, frozenset({"consentType"}))
    if requested and consent["consentType"].casefold() not in {
        value.casefold() for value in requested
    }:
        return _ok([])
    return _ok(
        [
            {
                "consentType": consent["consentType"],
                "consent": consent["consent"],
                "fromDate": consent["fromDate"],
                "thruDate": consent["thruDate"],
                "status": consent["status"],
                "memberId": world.member["memberId"],
            }
        ]
    )


def _opportunities(world: World, variables: dict[str, Any]) -> Composed:
    if not _member_ok(world, variables):
        return _ok([])
    opportunity = world.coverage["opportunity"]
    drug = world.drug(opportunity["drugId"])
    selected, active = _filter_drugs(world, variables)
    if active and drug["id"] not in {item["id"] for item in selected}:
        return _ok([])
    claim = next(item for item in world.claims if item["drugId"] == drug["id"])
    pharmacy = world.pharmacy(claim["pharmacyId"])
    return _ok(
        [
            {
                "caseId": opportunity["caseId"],
                "productType": opportunity["productType"],
                "productSubType": opportunity["productSubType"],
                "caseStatus": opportunity["caseStatus"],
                "programName": opportunity["programName"],
                "status": opportunity["status"],
                "rxInfo": [
                    {
                        "drugName": drug["labelName"],
                        "gpi": drug["gpi14"],
                        "pharmacyName": pharmacy["name"],
                        "pharmacyPhoneNumber": pharmacy["phone"],
                        "rxNumber": int(claim["rxNumber"]),
                        "ndc": drug["ndc"],
                        "filledDate": claim["fillDate"],
                        "clinicalRationale": _coverage_note(world, drug),
                    }
                ],
            }
        ]
    )


_BUILDERS = {
    "opportunities": _opportunities,
    "userProfile": _user_profile,
    "searchUserProfile": _search_user_profile,
    "session": _session,
    "drugForms": _drug_forms,
    "drugSearch": _drug_search,
    "drugInfo": _drug_info,
    "drugsByAlphabet": _drugs_by_alphabet,
    "drugsByName": _drugs_by_name,
    "drugResults": _drug_results,
    "drugDetails": _drug_details,
    "formulary": _formulary,
    "therapeuticClasses": _therapeutic_classes,
    "therapeuticSubClassSummary": _therapeutic_subclass_summary,
    "pACriteria": _pa_criteria,
    "stepTherapyRules": _step_therapy,
    "claims": _claims,
    "claimDetails": _claim_details,
    "productSearch": _product_search,
    "currentPrescriptions": _current_prescriptions,
    "recommendations": _recommendations,
    "prescriberDetails": _prescriber_details,
    "defaultPharmacy": _default_pharmacy,
    "plans": _plans,
    "pharmacySearch": _pharmacy_search,
    "accumulatorSummary": _accumulator_summary,
    "history": _history,
    "contactDetails": _contact_details,
    "drugPricing": _drug_pricing,
    "fetchIdCard": _fetch_id_card,
    "digitalIdCard": _digital_id_card,
    "mailService": _mail_service,
    "memberConsentDetails": _member_consent,
}

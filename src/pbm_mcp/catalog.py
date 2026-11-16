"""The twelve Pharmacy Benefit Management APIs from the developer portal."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Domain:
    """One portal API. Tools are mounted under ``namespace``."""

    id: str
    title: str
    summary: str

    @property
    def namespace(self) -> str:
        return self.id.replace("-", "_")


CATALOG: tuple[Domain, ...] = (
    Domain(
        "health-opportunity",
        "Health Opportunity API",
        "Search for new health opportunities.",
    ),
    Domain(
        "member-profile",
        "Member Profile API",
        "Demographics, family details, and contact information.",
    ),
    Domain(
        "drug-search",
        "Drug Search API",
        "DrugForms, DrugSearch, and DrugInfo queries.",
    ),
    Domain(
        "formulary",
        "Formulary API",
        "Formulary-related queries.",
    ),
    Domain(
        "claim-history",
        "Claim History API",
        "ClaimList, ClaimDetails, and ProductSearch.",
    ),
    Domain(
        "savings-center",
        "Savings Center API",
        "Proactive savings alerts.",
    ),
    Domain(
        "pharmacy-search",
        "Pharmacy Search API",
        "PharmacySearch, Plans, and DefaultPharmacy. Writes stay off until allowlisted.",
    ),
    Domain(
        "accumulators",
        "Accumulators API",
        "Accumulator summary.",
    ),
    Domain(
        "prior-auth",
        "Prior Auth API",
        "Prior authorization operations.",
    ),
    Domain(
        "drug-pricing",
        "Drug Pricing API",
        "Drug pricing operations.",
    ),
    Domain(
        "id-card",
        "ID Card API",
        "ID card GraphQL queries.",
    ),
    Domain(
        "member-consent",
        "Member Consent API",
        "Member consent GraphQL queries.",
    ),
)

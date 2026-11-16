"""No upstream credential. Useful against a mock that does not check auth."""


def no_auth() -> None:
    """Selected by ``PBM_AUTH_MODE=none``. The HTTP client sends no credential."""
    return None

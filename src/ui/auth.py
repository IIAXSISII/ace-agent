import os
import chainlit as cl


def setup_auth():
    """
    Configure Chainlit authentication.
    No-op when CHAINLIT_AUTH_SECRET is unset (local dev).
    OAuth callback stub when set (production).
    """
    auth_secret = os.getenv("CHAINLIT_AUTH_SECRET")
    if not auth_secret:
        # Auth disabled for local development
        return None
    # Production: OAuth callback stub (AgentCore Identity integration in F02+)
    return auth_secret


# Only register the OAuth callback when CHAINLIT_AUTH_SECRET is set
if os.getenv("CHAINLIT_AUTH_SECRET"):

    @cl.oauth_callback
    def oauth_callback(
        provider_id: str,
        token: str,
        raw_user_data: dict,
        default_user: cl.User,
    ) -> cl.User:
        """OAuth callback stub for AgentCore Identity (production only)."""
        return default_user

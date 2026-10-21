"""Guarded remediation suggestions.

SignalForge proposes remediations (e.g. a rollback) but never executes an
infrastructure change itself. Acting on a proposal requires an explicit
operator decision, recorded on the incident timeline for audit.
"""

from app.schemas import Incident, RemediationProposal
from app.storage import store

# How far back to look for the deployment to roll back and its predecessor.
DEPLOYMENT_LOOKBACK_MINUTES = 24 * 60


def propose_rollback(incident: Incident) -> RemediationProposal:
    """Suggest rolling back the most recent deployment for the incident's service.

    Grounded in deployment telemetry: the newest deployment is the suspected
    bad change (from_version) and the one before it is the rollback target
    (to_version). With no recent deployment there is nothing to roll back, so
    the proposal falls back to manual investigation.
    """
    deployments = store.get_recent_deployments(
        incident.tenant_id, incident.service_name, window_minutes=DEPLOYMENT_LOOKBACK_MINUTES
    )
    if not deployments:
        return RemediationProposal(
            incident_id=incident.id,
            service_name=incident.service_name,
            action="investigate",
            summary=(
                f"No recent deployment found for {incident.service_name}; there is "
                "nothing to roll back. Investigate logs, dependencies, and infrastructure."
            ),
            requires_approval=False,
        )

    from_version = str(deployments[0].attributes.get("version", "unknown"))
    to_version = (
        str(deployments[1].attributes.get("version"))
        if len(deployments) > 1 and deployments[1].attributes.get("version") is not None
        else None
    )
    target = f"v{to_version}" if to_version else "the previously known-good version"
    summary = (
        f"Roll back {incident.service_name} from v{from_version} to {target}. "
        f"v{from_version} is the most recent deployment and the likely change behind "
        "this incident. Requires operator approval; SignalForge will not roll back "
        "automatically."
    )
    return RemediationProposal(
        incident_id=incident.id,
        service_name=incident.service_name,
        action="rollback",
        from_version=from_version,
        to_version=to_version,
        summary=summary,
        requires_approval=True,
    )

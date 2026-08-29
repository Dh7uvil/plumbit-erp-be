"""Tenant seed entry points.

``seed_on_tenant_create`` runs during provisioning. ``seed_required_masters`` and
``seed_common_data`` are the two seed bodies; the latter is also the CLI target.
"""

from app.db.seeds.common import seed_common_data
from app.db.seeds.required import seed_required_masters
from app.db.seeds.tenant_creation import seed_on_tenant_create

__all__ = [
    "seed_common_data",
    "seed_on_tenant_create",
    "seed_required_masters",
]

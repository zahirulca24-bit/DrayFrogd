"""FastAPI backend package."""

from app.order_identity_autopersist import install as _install_order_identity_autopersist
from app.execution_fill_evidence import install as _install_execution_fill_evidence

_install_order_identity_autopersist()
_install_execution_fill_evidence()

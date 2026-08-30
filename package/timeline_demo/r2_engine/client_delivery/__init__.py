"""Fail-closed client-delivery layer for litigation visualization S2."""

from .delivery_ir import build_delivery_ir
from .input_gate import GateError, load_inputs
from .verify import VerificationError, verify_html, verify_pptx

__all__ = [
    "GateError",
    "VerificationError",
    "build_delivery_ir",
    "load_inputs",
    "verify_html",
    "verify_pptx",
]

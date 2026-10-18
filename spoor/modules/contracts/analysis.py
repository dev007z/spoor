"""A contract's full analysis: static findings on its code plus its live ownership."""

from dataclasses import dataclass

from spoor.modules.contracts.checks import Finding, Severity, run_checks
from spoor.modules.contracts.models import Contract
from spoor.modules.contracts.onchain import read_ownership


@dataclass
class Analysis:
    logic: Contract  # the contract whose code runs: the implementation behind a proxy
    findings: list
    ownership: object  # onchain.Ownership, or None when there is no owner()


def implementation_of(contract):
    if not (contract.is_proxy and contract.implementation):
        return None
    return Contract.objects.filter(
        address__chain=contract.chain, address__address=contract.implementation.lower()
    ).first()


def analyze_contract(contract, adapter=None):
    implementation = implementation_of(contract)
    logic = implementation or contract
    findings = run_checks(contract) + (run_checks(implementation) if implementation else [])
    ownership = read_ownership(contract, abi_contract=logic, adapter=adapter)
    if ownership and ownership.owner:
        findings.append(ownership_finding(ownership, findings))
    findings.sort(key=lambda f: Severity.ORDER.index(f.severity))
    return Analysis(logic=logic, findings=findings, ownership=ownership)


def ownership_finding(ownership, findings):
    if ownership.renounced:
        return Finding(
            "ownership",
            "Ownership renounced",
            Severity.INFO,
            "owner() returns the zero address, so owner-only functions can no longer be called. "
            "Other roles, a proxy admin, or a reclaim mechanism can still hold power.",
        )
    powers = [f for f in findings if f.severity == Severity.HIGH]
    return Finding(
        "ownership",
        "Owner is active",
        Severity.MEDIUM if powers else Severity.LOW,
        f"owner() returns {ownership.owner}"
        + (", who can use the owner powers listed here." if powers else "."),
    )

"""Static checks on a token contract's verified source and ABI.

Each check is a rule that reads comment-stripped Solidity and the ABI and returns
findings: a severity, a plain explanation of what the contract lets its controllers
do, and the source lines it rests on. The checks describe powers, not intent: a
regulated stablecoin and a scam token can share a finding, and the explanation says
what the power means for a holder. Rules are registered in settings.SPOOR_CONTRACT_CHECKS.
"""

import re
from dataclasses import dataclass, field

from django.conf import settings
from django.utils.module_loading import import_string


class Severity:
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    ORDER = [HIGH, MEDIUM, LOW, INFO]


@dataclass
class Evidence:
    file: str
    line: int
    code: str


@dataclass
class Finding:
    check: str
    title: str
    severity: str
    explanation: str
    evidence: list = field(default_factory=list)


COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)


def strip_comments(code):
    """Blank out comments but keep line breaks, so line numbers still match the file."""
    return COMMENTS.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), code)


class Source:
    """A contract's files with comments removed, searchable with line numbers."""

    def __init__(self, files):
        self.files = {name: strip_comments(code) for name, code in files.items()}

    def find(self, pattern, flags=re.IGNORECASE):
        regex = re.compile(pattern, flags)
        hits = []
        for name, code in self.files.items():
            for match in regex.finditer(code):
                line = code.count("\n", 0, match.start()) + 1
                text = code.splitlines()[line - 1].strip()
                hits.append(Evidence(name, line, text[:200]))
        return hits

    def functions(self, name_pattern):
        """(declaration evidence, header up to the body) for functions whose name matches."""
        # Named groups: name patterns carry their own groups, which would shift numbering.
        regex = re.compile(
            rf"function\s+(?P<name>{name_pattern})\s*\((?P<args>[^)]*)\)(?P<header>[^{{;]*)",
            re.IGNORECASE,
        )
        found = []
        for name, code in self.files.items():
            for match in regex.finditer(code):
                line = code.count("\n", 0, match.start()) + 1
                header = match.group("header")
                body = function_body(code, match.end())
                found.append((Evidence(name, line, match.group(0).strip()[:200]), header, body))
        return found


def function_body(code, start):
    """The text of the brace-delimited body that begins at or after `start`."""
    opening = code.find("{", start)
    semicolon = code.find(";", start)
    if opening < 0 or (0 <= semicolon < opening):
        return ""
    depth = 0
    for index in range(opening, len(code)):
        if code[index] == "{":
            depth += 1
        elif code[index] == "}":
            depth -= 1
            if depth == 0:
                return code[opening : index + 1]
    return code[opening:]


PRIVILEGED = re.compile(
    r"\bonly[A-Z]\w*|require\s*\(\s*(_?msg\.sender|_msgSender\(\))\s*==|hasRole\s*\(", re.IGNORECASE
)


def is_privileged(header, body):
    return bool(PRIVILEGED.search(header) or PRIVILEGED.search(body[:400]))


def is_external(header):
    return bool(re.search(r"\b(public|external)\b", header))


class Check:
    key = ""

    def run(self, source, contract):
        raise NotImplementedError


class PrivilegedMint(Check):
    key = "privileged_mint"

    def run(self, source, contract):
        evidence = [
            declaration
            for declaration, header, body in source.functions(r"mint\w*|issue|createTokens")
            if is_external(header) and is_privileged(header, body)
        ]
        if not evidence:
            return []
        return [
            Finding(
                self.key,
                "Owner can create new tokens",
                Severity.HIGH,
                "A privileged account can mint tokens at will, diluting every holder. Legitimate "
                "for some issuers; in an unknown token it lets the deployer print and sell.",
                evidence,
            )
        ]


class TransferBlocklist(Check):
    key = "transfer_blocklist"

    def run(self, source, contract):
        evidence = source.find(
            r"\b\w*(black_?list|blocked|isBot|bots|frozen|freeze)\w*\b\s*\[|"
            r"function\s+\w*(black_?list|blocklist|freeze|addBot|setBot)\w*\s*\("
        )
        if not evidence:
            return []
        return [
            Finding(
                self.key,
                "Owner can block addresses",
                Severity.HIGH,
                "The contract keeps a list of addresses that cannot transfer, and a privileged "
                "account maintains it. Holders can be frozen; in scam tokens this is how buyers "
                "are stopped from selling.",
                evidence[:8],
            )
        ]


class ModifiableFees(Check):
    key = "modifiable_fees"

    def run(self, source, contract):
        setters = [
            (declaration, body)
            for declaration, header, body in source.functions(
                r"set\w*(fee|tax)\w*|update\w*(fee|tax)\w*"
            )
            if is_external(header) and is_privileged(header, body)
        ]
        if not setters:
            return []
        unbounded = [d for d, body in setters if not re.search(r"require\s*\([^;]*<=?", body)]
        return [
            Finding(
                self.key,
                "Owner can change transfer fees",
                Severity.HIGH if unbounded else Severity.MEDIUM,
                (
                    "Fees on transfers can be changed by a privileged account with no upper limit "
                    "in code: a sell tax can be raised until selling is pointless."
                    if unbounded
                    else "Fees on transfers can be changed by a privileged account, within a "
                    "limit enforced in code."
                ),
                [d for d, _ in setters],
            )
        ]


class TradingControls(Check):
    key = "trading_controls"

    def run(self, source, contract):
        switches = [
            d
            for d, header, body in source.functions(
                r"pause|unpause|\w*(enable|open|start|set)\w*trading\w*|set\w*swap\w*enabled"
            )
            if is_external(header) and is_privileged(header, body)
        ]
        limits = [
            d
            for d, header, body in source.functions(r"set\w*max\w*(tx|wallet|transaction)\w*")
            if is_external(header) and is_privileged(header, body)
        ]
        findings = []
        if switches:
            findings.append(
                Finding(
                    self.key,
                    "Owner can stop transfers",
                    Severity.HIGH,
                    "A privileged account can pause the token or switch trading on and off. "
                    "While off, holders cannot move or sell.",
                    switches,
                )
            )
        if limits:
            findings.append(
                Finding(
                    "transfer_limits",
                    "Owner can cap transfer sizes",
                    Severity.MEDIUM,
                    "A privileged account can set the largest transfer or wallet size, which can "
                    "be lowered to trap holders.",
                    limits,
                )
            )
        return findings


class Upgradeable(Check):
    key = "upgradeable"

    def run(self, source, contract):
        # Code evidence only: not delegatecall (libraries such as OpenZeppelin's Address use
        # it without upgrades), and not Etherscan's proxy flag, which it also sets on some
        # implementations.
        evidence = source.find(
            r"function\s+_?upgradeTo\w*\s*\(|IMPLEMENTATION_SLOT|"
            r"0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
        )
        if not evidence:
            return []
        return [
            Finding(
                self.key,
                "Logic can be replaced",
                Severity.MEDIUM,
                "This is an upgradeable proxy: whoever controls upgrades can swap the code behind "
                "the token, so any check here only holds until the next upgrade.",
                evidence[:4],
            )
        ]


class HiddenOwnership(Check):
    key = "hidden_ownership"

    def run(self, source, contract):
        reclaim = source.find(r"_previousOwner|function\s+unlock\s*\(|_lockTime")
        if not reclaim:
            return []
        return [
            Finding(
                self.key,
                "Ownership can be taken back",
                Severity.HIGH,
                "The contract remembers a previous owner and can hand ownership back after a "
                "lock period. Ownership can look renounced while the deployer keeps a way back.",
                reclaim[:6],
            )
        ]


def registered_checks():
    return [import_string(path)() for path in settings.SPOOR_CONTRACT_CHECKS]


def run_checks(contract):
    """Every registered check's findings, most serious first."""
    if not contract.is_verified:
        return []
    source = Source(contract.source_files)
    findings = [finding for check in registered_checks() for finding in check.run(source, contract)]
    return sorted(findings, key=lambda f: Severity.ORDER.index(f.severity))

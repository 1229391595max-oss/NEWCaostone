"""Select verification checks and fingerprint their complete code domains."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping


POLICY_SCHEMA = "bizpulse.verification-policy.v1"
EVIDENCE_SCHEMA = "bizpulse.development-evidence.v1"


class VerificationPolicyError(ValueError):
    """Raised when a path cannot be verified under the checked-in policy."""


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    argv: tuple[str, ...]
    reuse: str


@dataclass(frozen=True, slots=True)
class DomainPolicy:
    name: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    checks: tuple[str, ...]
    exclusive: bool = False

    def matches(self, path: str) -> bool:
        normalized = path.removeprefix("./")
        return any(fnmatchcase(normalized, item) for item in self.include) and not any(
            fnmatchcase(normalized, item) for item in self.exclude
        )


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    checks: tuple[Check, ...]
    domains: tuple[DomainPolicy, ...]
    schema_version: str = POLICY_SCHEMA

    def check(self, name: str) -> Check:
        for check in self.checks:
            if check.name == name:
                return check
        raise VerificationPolicyError(f"verification_policy_unknown_check:{name}")

    def domains_for_check(self, name: str) -> tuple[DomainPolicy, ...]:
        return tuple(domain for domain in self.domains if name in domain.checks)


def _string_list(value: object, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise VerificationPolicyError(f"verification_policy_invalid:{context}")
    return tuple(value)


def load_verification_policy(path: Path) -> VerificationPolicy:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationPolicyError(f"verification_policy_invalid:{path}") from error
    if not isinstance(payload, Mapping) or set(payload) != {
        "checks",
        "domains",
        "schema_version",
    }:
        raise VerificationPolicyError("verification_policy_invalid:root")
    if payload["schema_version"] != POLICY_SCHEMA:
        raise VerificationPolicyError("verification_policy_schema_invalid")

    raw_checks = payload["checks"]
    if not isinstance(raw_checks, Mapping) or not raw_checks:
        raise VerificationPolicyError("verification_policy_invalid:checks")
    checks: list[Check] = []
    for name, raw in raw_checks.items():
        if (
            not isinstance(name, str)
            or not isinstance(raw, Mapping)
            or set(raw) != {"argv", "reuse"}
            or raw["reuse"] not in {"development_only", "never"}
        ):
            raise VerificationPolicyError(f"verification_policy_invalid:check:{name}")
        argv = _string_list(raw["argv"], context=f"check:{name}:argv")
        if raw["reuse"] == "never" and name == "full_release_gate":
            argv = ()
        elif not argv:
            raise VerificationPolicyError(
                f"verification_policy_invalid:check:{name}:argv"
            )
        checks.append(Check(name=name, argv=argv, reuse=str(raw["reuse"])))

    raw_domains = payload["domains"]
    if not isinstance(raw_domains, list) or not raw_domains:
        raise VerificationPolicyError("verification_policy_invalid:domains")
    domains: list[DomainPolicy] = []
    known_checks = {item.name for item in checks}
    for index, raw in enumerate(raw_domains):
        if not isinstance(raw, Mapping) or set(raw) != {
            "checks",
            "exclude",
            "exclusive",
            "include",
            "name",
        }:
            raise VerificationPolicyError(
                f"verification_policy_invalid:domain:{index}"
            )
        names = _string_list(raw["checks"], context=f"domain:{index}:checks")
        if any(name not in known_checks for name in names):
            raise VerificationPolicyError(
                f"verification_policy_invalid:domain:{index}:checks"
            )
        if not isinstance(raw["name"], str) or not isinstance(raw["exclusive"], bool):
            raise VerificationPolicyError(
                f"verification_policy_invalid:domain:{index}"
            )
        domains.append(
            DomainPolicy(
                name=raw["name"],
                include=_string_list(
                    raw["include"], context=f"domain:{index}:include"
                ),
                exclude=_string_list(
                    raw["exclude"], context=f"domain:{index}:exclude"
                )
                if raw["exclude"]
                else (),
                checks=names,
                exclusive=raw["exclusive"],
            )
        )
    return VerificationPolicy(checks=tuple(checks), domains=tuple(domains))


def select_required_checks(
    paths: Iterable[str],
    policy: VerificationPolicy,
) -> tuple[Check, ...]:
    selected: list[str] = []
    for path in paths:
        matching = tuple(domain for domain in policy.domains if domain.matches(path))
        if not matching:
            raise VerificationPolicyError(f"verification_policy_unmapped_path:{path}")
        exclusive = tuple(domain for domain in matching if domain.exclusive)
        applicable = exclusive or matching
        for domain in applicable:
            for name in domain.checks:
                if name not in selected:
                    selected.append(name)
    return tuple(policy.check(name) for name in selected)


def _domain_files(repository_root: Path, domain: DomainPolicy) -> tuple[Path, ...]:
    files: list[Path] = []
    for path in repository_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(repository_root).as_posix()
        if domain.matches(relative):
            files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(repository_root).as_posix()))


def domain_fingerprint(repository_root: Path, domain: DomainPolicy) -> str:
    digest = hashlib.sha256()
    for path in _domain_files(repository_root, domain):
        relative = path.relative_to(repository_root).as_posix()
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
    return digest.hexdigest()


def can_reuse(
    evidence: Mapping[str, object],
    *,
    check: Check,
    fingerprint: str,
) -> bool:
    return (
        check.reuse == "development_only"
        and evidence.get("schema_version") == EVIDENCE_SCHEMA
        and evidence.get("check") == check.name
        and evidence.get("domain_fingerprint") == fingerprint
        and evidence.get("passed") is True
    )

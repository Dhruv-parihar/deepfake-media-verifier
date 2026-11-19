from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SEVERITY_WEIGHT = {"info": 0, "low": 8, "medium": 20, "high": 40}


@dataclass
class Finding:
    severity: str
    title: str
    detail: str
    weight: Optional[int] = None

    def score(self) -> int:
        if self.weight is not None:
            return self.weight
        return SEVERITY_WEIGHT.get(self.severity, 0)


@dataclass
class DetectorResult:
    name: str
    status: str = "ok"
    note: str = ""
    findings: List[Finding] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    def add(self, severity: str, title: str, detail: str, weight: Optional[int] = None) -> None:
        self.findings.append(Finding(severity, title, detail, weight))

    def risk(self) -> int:
        if self.status != "ok":
            return 0
        return min(100, sum(item.score() for item in self.findings))

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["risk"] = self.risk()
        return payload

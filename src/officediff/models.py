from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PageDiff:
    index: int
    status: str
    change_ratio: float
    base_image: Optional[str]
    current_image: Optional[str]
    diff_image: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentDiff:
    path: str
    kind: str
    status: str
    base_pages: int
    current_pages: int
    changed_pages: int
    text_diff: str
    pages: List[PageDiff] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunSummary:
    base_ref: str
    head_ref: str
    documents: List[DocumentDiff] = field(default_factory=list)
    render_engine: str = "LibreOffice + Poppler"

    @property
    def changed_pages(self) -> int:
        return sum(document.changed_pages for document in self.documents)

    @property
    def error_count(self) -> int:
        return sum(len(document.errors) for document in self.documents)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["totals"] = {
            "documents": len(self.documents),
            "changed_pages": self.changed_pages,
            "errors": self.error_count,
        }
        return payload

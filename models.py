"""
Data models for IPO Lock-in Processor
Simple dataclasses for structured data exchange between modules
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional
from enum import Enum


class RowStatus(Enum):
    """Lock-in row status"""
    LOCKED = "LOCKED"
    FREE = "FREE"


class LockBucket(Enum):
    """Lock-in duration buckets"""
    YEARS_3_PLUS = "3+YEARS"
    YEARS_2_PLUS = "2+YEARS"
    YEARS_1_PLUS = "1+YEAR"
    ANCHOR_90_DAYS = "ANCHOR_90DAYS"
    ANCHOR_30_DAYS = "ANCHOR_30DAYS"
    FREE = "FREE"


@dataclass
class LockinRow:
    """
    Single row from lock-in details extraction
    Represents one lock-in entry with shares and dates
    """
    shares: int
    distinctive_from: Optional[int] = None
    distinctive_to: Optional[int] = None
    security_type: Optional[str] = None
    lockin_date_from: Optional[date] = None
    lockin_date_to: Optional[date] = None
    share_form: Optional[str] = None
    status: RowStatus = RowStatus.FREE
    bucket: LockBucket = LockBucket.FREE

    def is_locked(self) -> bool:
        """Check if this row represents locked shares"""
        return self.status == RowStatus.LOCKED

    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion"""
        return {
            'shares': self.shares,
            'distinctive_from': self.distinctive_from,
            'distinctive_to': self.distinctive_to,
            'security_type': self.security_type,
            'lockin_date_from': self.lockin_date_from,
            'lockin_date_to': self.lockin_date_to,
            'share_form': self.share_form,
            'status': self.status.value,
            'bucket': self.bucket.value,
        }


@dataclass
class LockinData:
    """
    Complete lock-in details extraction result
    Contains all rows plus computed totals
    """
    rows: List[LockinRow] = field(default_factory=list)
    computed_total: int = 0
    locked_total: int = 0
    free_total: int = 0
    declared_total: Optional[int] = None  # From TOTAL line in PDF/TXT
    strategy: Optional[str] = None  # [STRATEGY-TRACKING 2026-03-09] Which parser strategy was used

    def compute_totals(self):
        """Calculate totals from rows"""
        self.computed_total = sum(row.shares for row in self.rows)
        self.locked_total = sum(row.shares for row in self.rows if row.is_locked())
        self.free_total = sum(row.shares for row in self.rows if not row.is_locked())

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'rows': [row.to_dict() for row in self.rows],
            'computed_total': self.computed_total,
            'locked_total': self.locked_total,
            'free_total': self.free_total,
            'declared_total': self.declared_total,
            'strategy': self.strategy,  # [STRATEGY-TRACKING 2026-03-09]
        }


@dataclass
class SHPData:
    """
    SHP (Shareholding Pattern) extraction result
    Contains promoter, public, others breakdown
    """
    total_shares: int
    locked_shares: int
    promoter_shares: int
    public_shares: int
    others_shares: int  # Sum of C1 + C2 + C3 + ...
    strategy_used: Optional[str] = None  # [STRATEGY-TRACKING 2026-03-09] Which SHP strategy was used

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'total_shares': self.total_shares,
            'locked_shares': self.locked_shares,
            'promoter_shares': self.promoter_shares,
            'public_shares': self.public_shares,
            'others_shares': self.others_shares,
            'strategy_used': self.strategy_used,  # [STRATEGY-TRACKING 2026-03-09]
        }


@dataclass
class ValidationResult:
    """
    Validation result for a single rule
    """
    rule_id: str  # e.g., "RULE1"
    passed: bool
    message: str
    expected: Optional[int] = None
    actual: Optional[int] = None
    can_override: bool = False  # Whether this rule can be manually overridden
    overridden: bool = False  # Whether this rule has been overridden
    override_reason: Optional[str] = None  # Reason for override

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'rule_id': self.rule_id,
            'passed': self.passed,
            'message': self.message,
            'expected': self.expected,
            'actual': self.actual,
            'can_override': self.can_override,
            'overridden': self.overridden,
            'override_reason': self.override_reason,
        }


@dataclass
class ProcessingStatus:
    """
    Overall processing status for a file
    """
    unique_symbol: str
    exchange: str
    file_name: str

    # Extraction results
    lockin_data: Optional[LockinData] = None
    shp_data: Optional[SHPData] = None

    # From sme_ipo_master
    allotment_date: Optional[date] = None
    declared_total: Optional[int] = None

    # Validation results
    validations: List[ValidationResult] = field(default_factory=list)
    all_rules_passed: bool = False

    # File paths
    lockin_pdf: Optional[str] = None
    shp_pdf: Optional[str] = None
    lockin_txt_java: Optional[str] = None
    shp_txt_java: Optional[str] = None
    lockin_png: Optional[str] = None

    def get_failed_rules(self) -> List[ValidationResult]:
        """Get list of failed validation rules"""
        return [v for v in self.validations if not v.passed]

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage"""
        return {
            'unique_symbol': self.unique_symbol,
            'exchange': self.exchange,
            'file_name': self.file_name,
            'lockin_data': self.lockin_data.to_dict() if self.lockin_data else None,
            'shp_data': self.shp_data.to_dict() if self.shp_data else None,
            'allotment_date': self.allotment_date,
            'declared_total': self.declared_total,
            'validations': [v.to_dict() for v in self.validations],
            'all_rules_passed': self.all_rules_passed,
            'lockin_pdf': self.lockin_pdf,
            'shp_pdf': self.shp_pdf,
            'lockin_txt_java': self.lockin_txt_java,
            'shp_txt_java': self.shp_txt_java,
            'lockin_png': self.lockin_png,
        }

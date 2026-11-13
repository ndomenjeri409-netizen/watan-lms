from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Trim, Upper

from apps.accounts.roles import Role
from common.models import BaseModel
from common.scoping import UnitScopedQuerySet

from .permissions import finance_unit_ids


class Account(BaseModel):
    class Type(models.TextChoices):
        ASSET = "ASSET", "Asset"
        LIABILITY = "LIABILITY", "Liability"
        EQUITY = "EQUITY", "Equity"
        INCOME = "INCOME", "Income"
        EXPENSE = "EXPENSE", "Expense"

    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=10, choices=Type.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("code",)

    def __str__(self):
        return f"{self.code} — {self.name}"


class CashAccount(BaseModel):
    class Kind(models.TextChoices):
        DRAWER = "DRAWER", "Drawer"
        MPESA_AGENT = "MPESA_AGENT", "M-Pesa agent"
        BANK = "BANK", "Bank"

    account = models.OneToOneField(
        Account, on_delete=models.PROTECT, related_name="cash_account"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    name = models.CharField(max_length=80)
    custody_unit = models.ForeignKey(
        "org.BusinessUnit", on_delete=models.PROTECT, related_name="cash_accounts"
    )
    custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="custodied_cash_accounts",
    )
    imprest_limit = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    is_active = models.BooleanField(default=True)

    def clean(self):
        if self.account_id and self.account.type != Account.Type.ASSET:
            raise ValidationError(
                {"account": "A cash account must map to an asset account."}
            )
        if self.imprest_limit is not None and self.imprest_limit < 0:
            raise ValidationError(
                {"imprest_limit": "The imprest limit cannot be negative."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AccountingPeriod(BaseModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    start = models.DateField()
    end = models.DateField()
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.OPEN)

    class Meta:
        ordering = ("-start",)
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(end__gte=models.F("start")),
                name="finance_period_dates_valid",
            )
        ]

    def clean(self):
        if self.start and self.end and self.end < self.start:
            raise ValidationError(
                {"end": "The period end must be on or after its start."}
            )
        overlaps = AccountingPeriod.objects.filter(
            start__lte=self.end, end__gte=self.start
        ).exclude(pk=self.pk)
        if overlaps.exists():
            raise ValidationError("Accounting periods may not overlap.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class FeeStructureQuerySet(UnitScopedQuerySet):
    pass


class FeeStructure(BaseModel):
    unit = models.ForeignKey(
        "org.BusinessUnit", on_delete=models.PROTECT, related_name="fee_structures"
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    receivable_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="fee_receivables"
    )
    income_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="fee_income"
    )
    discount_account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fee_discounts",
    )
    refund_account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fee_refunds",
    )
    is_active = models.BooleanField(default=True)

    objects = FeeStructureQuerySet.as_manager()

    class Meta:
        ordering = ("unit__code", "code")
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("unit", "code"), name="finance_fee_code_per_unit"
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="finance_fee_amount_positive"
            ),
        ]

    def clean(self):
        if (
            self.receivable_account_id
            and self.receivable_account.type != Account.Type.ASSET
        ):
            raise ValidationError(
                {"receivable_account": "Receivables must use an asset account."}
            )
        if self.income_account_id and self.income_account.type != Account.Type.INCOME:
            raise ValidationError(
                {"income_account": "Fee income must use an income account."}
            )
        if (
            self.discount_account_id
            and self.discount_account.type != Account.Type.EXPENSE
        ):
            raise ValidationError(
                {"discount_account": "Discounts must use an expense account."}
            )
        if self.refund_account_id and self.refund_account.type != Account.Type.INCOME:
            raise ValidationError(
                {"refund_account": "Refunds must use a contra-income account."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.unit.code}: {self.name}"


class InvoiceQuerySet(UnitScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_global_read():
            return self
        if user.has_role(Role.STUDENT):
            return self.filter(student__user=user)
        unit_ids = finance_unit_ids(user)
        return self.filter(unit_id__in=unit_ids) if unit_ids else self.none()


class Invoice(BaseModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PARTIAL = "PARTIAL", "Partially paid"
        PAID = "PAID", "Paid"
        VOID = "VOID", "Void"

    number = models.CharField(max_length=40, unique=True)
    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="invoices"
    )
    unit = models.ForeignKey(
        "org.BusinessUnit", on_delete=models.PROTECT, related_name="invoices"
    )
    fee_structure = models.ForeignKey(
        FeeStructure, on_delete=models.PROTECT, related_name="invoices"
    )
    idempotency_key = models.CharField(
        max_length=64, unique=True, null=True, blank=True
    )
    issue_date = models.DateField()
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_due = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    journal_entry = models.OneToOneField(
        "JournalEntry", on_delete=models.PROTECT, related_name="invoice"
    )

    objects = InvoiceQuerySet.as_manager()

    class Meta:
        ordering = ("-issue_date", "-created_at")
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="finance_invoice_amount_positive"
            ),
            models.CheckConstraint(
                condition=Q(balance_due__gte=0)
                & Q(balance_due__lte=models.F("amount")),
                name="finance_invoice_balance_valid",
            ),
            models.CheckConstraint(
                condition=Q(due_date__gte=models.F("issue_date")),
                name="finance_invoice_dates_valid",
            ),
        ]

    def clean(self):
        if (
            self.fee_structure_id
            and self.unit_id
            and self.fee_structure.unit_id != self.unit_id
        ):
            raise ValidationError(
                {"fee_structure": "The fee structure belongs to another unit."}
            )
        if (
            self.student_id
            and self.unit_id
            and self.student.department.unit_id != self.unit_id
        ):
            raise ValidationError(
                {"student": "The student does not belong to this unit."}
            )


class JournalEntryQuerySet(models.QuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_global_read() or user.has_group_bursar_assignment():
            return self
        unit_ids = finance_unit_ids(user)
        if not unit_ids:
            return self.none()
        return self.filter(lines__unit_id__in=unit_ids).distinct()


class JournalEntry(BaseModel):
    class SourceType(models.TextChoices):
        INVOICE = "INVOICE", "Invoice"
        PAYMENT = "PAYMENT", "Payment"
        REFUND = "REFUND", "Refund"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"
        REVERSAL = "REVERSAL", "Reversal"

    class Status(models.TextChoices):
        POSTED = "POSTED", "Posted"

    date = models.DateField()
    memo = models.CharField(max_length=255)
    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    source_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(
        max_length=6, choices=Status.choices, default=Status.POSTED
    )
    reverses = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reversal_entries",
    )
    reversal_reason = models.CharField(max_length=255, blank=True)
    idempotency_key = models.CharField(
        max_length=64, unique=True, null=True, blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="finance_entries",
    )

    objects = JournalEntryQuerySet.as_manager()

    class Meta:
        ordering = ("-date", "-created_at")

    def save(self, *args, **kwargs):
        if self.pk and JournalEntry.objects.filter(pk=self.pk).exists():
            raise ValidationError("Journal entries are append-only.")
        if self.reverses_id and not self.reversal_reason.strip():
            raise ValidationError({"reversal_reason": "A reversal requires a reason."})
        if self.reverses_id and self.source_type != self.SourceType.REVERSAL:
            raise ValidationError(
                {"source_type": "A reversal entry must use source type REVERSAL."}
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Journal entries are append-only.")


class JournalLineQuerySet(UnitScopedQuerySet):
    pass


class JournalLine(BaseModel):
    entry = models.ForeignKey(
        JournalEntry, on_delete=models.PROTECT, related_name="lines"
    )
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="journal_lines"
    )
    unit = models.ForeignKey(
        "org.BusinessUnit", on_delete=models.PROTECT, related_name="journal_lines"
    )
    cash_account = models.ForeignKey(
        CashAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    student = models.ForeignKey(
        "people.Student",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )

    objects = JournalLineQuerySet.as_manager()

    class Meta:
        ordering = ("created_at", "id")
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=(Q(debit__gt=0, credit=0) | Q(credit__gt=0, debit=0)),
                name="finance_journal_line_one_sided_positive",
            ),
        ]

    def clean(self):
        if (
            self.account_id
            and self.cash_account_id
            and self.cash_account.account_id != self.account_id
        ):
            raise ValidationError(
                {"cash_account": "Cash account must map to the journal account."}
            )

    def save(self, *args, **kwargs):
        if self.pk and JournalLine.objects.filter(pk=self.pk).exists():
            raise ValidationError("Journal lines are append-only.")
        if self.entry_id and self.entry.status != JournalEntry.Status.POSTED:
            raise ValidationError("Journal lines can only be added to posted entries.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Journal lines are append-only.")


class Payment(BaseModel):
    class Channel(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA_AGENT = "MPESA_AGENT", "M-Pesa agent"
        BANK = "BANK", "Bank"

    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="payments"
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    channel = models.CharField(max_length=12, choices=Channel.choices)
    mpesa_code = models.CharField(max_length=32, null=True, blank=True)
    payer_phone = models.CharField(max_length=32, blank=True)
    received_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=64, unique=True)
    journal_entry = models.OneToOneField(
        JournalEntry, on_delete=models.PROTECT, related_name="payment"
    )

    class Meta:
        ordering = ("-received_at",)
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="finance_payment_amount_positive"
            ),
            models.CheckConstraint(
                condition=Q(mpesa_code__isnull=True)
                | Q(mpesa_code=Upper(Trim("mpesa_code"))),
                name="finance_mpesa_code_normalized",
            ),
            models.UniqueConstraint(
                fields=("mpesa_code",),
                condition=Q(mpesa_code__isnull=False) & ~Q(mpesa_code=""),
                name="finance_mpesa_code_unique",
            ),
        ]

    @staticmethod
    def normalize_mpesa_code(value):
        return (value or "").strip().upper() or None

    def save(self, *args, **kwargs):
        self.mpesa_code = self.normalize_mpesa_code(self.mpesa_code)
        return super().save(*args, **kwargs)


class Receipt(BaseModel):
    number = models.CharField(max_length=48, unique=True)
    payment = models.OneToOneField(
        Payment, on_delete=models.PROTECT, related_name="receipt"
    )
    issued_at = models.DateTimeField()
    generated_file = models.OneToOneField(
        "files.StoredFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="receipt",
    )


class Adjustment(BaseModel):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        POSTED = "POSTED", "Posted"
        REVERSED = "REVERSED", "Reversed"

    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="adjustments"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.CharField(max_length=255)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_finance_adjustments",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_finance_adjustments",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.REQUESTED
    )
    journal_entry = models.OneToOneField(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="adjustment",
    )

    class Meta:
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="finance_adjustment_amount_positive"
            )
        ]


class Refund(BaseModel):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        POSTED = "POSTED", "Posted"
        REVERSED = "REVERSED", "Reversed"

    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, related_name="refunds"
    )
    cash_account = models.ForeignKey(
        CashAccount, on_delete=models.PROTECT, related_name="refunds"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.CharField(max_length=255)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_finance_refunds",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_finance_refunds",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.REQUESTED
    )
    journal_entry = models.OneToOneField(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="refund",
    )

    class Meta:
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="finance_refund_amount_positive"
            )
        ]

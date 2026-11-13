from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.enrollment.models import Enrollment
from common.audit import get_object_unit, record_audit

from .models import (
    AccountingPeriod,
    Adjustment,
    CashAccount,
    FeeStructure,
    Invoice,
    JournalEntry,
    JournalLine,
    Payment,
    Receipt,
    Refund,
)


def _money(value):
    return Decimal(value).quantize(Decimal("0.01"))


def _require_open_period(entry_date):
    period = (
        AccountingPeriod.objects.select_for_update()
        .filter(start__lte=entry_date, end__gte=entry_date)
        .first()
    )
    if period is None:
        raise ValidationError({"date": "No accounting period covers this date."})
    if period.status != AccountingPeriod.Status.OPEN:
        raise ValidationError({"date": "This accounting period is closed."})
    return period


def _require_different_actor(actor, maker, action):
    if actor.pk == maker.pk:
        raise ValidationError(
            {"approved_by": f"The person who recorded this {action} cannot reverse it."}
        )


@transaction.atomic
def post_journal_entry(
    *,
    entry_date,
    memo,
    source_type,
    source_id,
    actor,
    lines,
    idempotency_key=None,
    reverses=None,
    reversal_reason="",
):
    _require_open_period(entry_date)
    normalized_lines = []
    debit_total = Decimal("0.00")
    credit_total = Decimal("0.00")
    for line in lines:
        debit = _money(line.get("debit", 0))
        credit = _money(line.get("credit", 0))
        if (debit > 0) == (credit > 0):
            raise ValidationError(
                "Each journal line must have either a debit or a credit."
            )
        debit_total += debit
        credit_total += credit
        normalized_lines.append({**line, "debit": debit, "credit": credit})
    if not normalized_lines or debit_total <= 0 or debit_total != credit_total:
        raise ValidationError(
            "Journal entry debits and credits must be equal and non-zero."
        )

    entry = JournalEntry.objects.create(
        date=entry_date,
        memo=memo,
        source_type=source_type,
        source_id=source_id,
        created_by=actor,
        idempotency_key=idempotency_key,
        reverses=reverses,
        reversal_reason=reversal_reason,
    )
    JournalLine.objects.bulk_create(
        [JournalLine(entry=entry, **line) for line in normalized_lines]
    )
    entry_unit = get_object_unit(entry)
    record_audit(
        actor=actor,
        action="finance_journal_posted",
        obj=entry,
        unit=entry_unit,
        group_level=entry_unit is None,
        after={
            "date": entry.date,
            "memo": entry.memo,
            "source_type": entry.source_type,
            "debit_total": debit_total,
            "credit_total": credit_total,
        },
    )
    return entry


@transaction.atomic
def create_invoice(
    *, student, fee_structure, issue_date, due_date, actor, idempotency_key
):
    def get_existing_invoice():
        existing = Invoice.objects.filter(idempotency_key=idempotency_key).first()
        if existing and (
            existing.student_id != student.pk
            or existing.fee_structure_id != fee_structure.pk
            or existing.issue_date != issue_date
            or existing.due_date != due_date
        ):
            raise ValidationError(
                {
                    "idempotency_key": (
                        "This key was already used for a different invoice."
                    )
                }
            )
        return existing

    existing = get_existing_invoice()
    if existing:
        return existing

    try:
        with transaction.atomic():
            fee_structure = FeeStructure.objects.select_related(
                "unit", "receivable_account", "income_account"
            ).get(pk=fee_structure.pk, is_active=True)
            is_visible_to_unit = (
                student.home_unit_id == fee_structure.unit_id
                or Enrollment.objects.filter(
                    student=student, unit_id=fee_structure.unit_id
                ).exists()
                or Invoice.objects.filter(
                    student=student, unit_id=fee_structure.unit_id
                ).exists()
            )
            if not is_visible_to_unit:
                raise ValidationError(
                    {"student": "The student does not belong to this unit."}
                )
            if due_date < issue_date:
                raise ValidationError(
                    {"due_date": "The due date cannot precede the issue date."}
                )
            invoice_id = Invoice._meta.pk.default()
            number = f"INV-{invoice_id.hex[:16].upper()}"
            entry = post_journal_entry(
                entry_date=issue_date,
                memo=f"Invoice {number}",
                source_type=JournalEntry.SourceType.INVOICE,
                source_id=invoice_id,
                actor=actor,
                lines=(
                    {
                        "account": fee_structure.receivable_account,
                        "unit": fee_structure.unit,
                        "student": student,
                        "debit": fee_structure.amount,
                    },
                    {
                        "account": fee_structure.income_account,
                        "unit": fee_structure.unit,
                        "student": student,
                        "credit": fee_structure.amount,
                    },
                ),
            )
            invoice = Invoice.objects.create(
                id=invoice_id,
                number=number,
                student=student,
                unit=fee_structure.unit,
                fee_structure=fee_structure,
                idempotency_key=idempotency_key,
                issue_date=issue_date,
                due_date=due_date,
                amount=fee_structure.amount,
                balance_due=fee_structure.amount,
                journal_entry=entry,
            )
            record_audit(
                actor=actor,
                action="finance_invoice_created",
                obj=invoice,
                unit=get_object_unit(invoice),
                after={
                    "number": number,
                    "amount": invoice.amount,
                    "unit_id": invoice.unit_id,
                },
            )
            return invoice
    except IntegrityError:
        existing = get_existing_invoice()
        if existing:
            return existing
        raise


@transaction.atomic
def record_payment(
    *,
    invoice_id,
    cash_account_id,
    amount,
    channel,
    received_at,
    actor,
    idempotency_key,
    mpesa_code=None,
    payer_phone="",
):
    amount = _money(amount)
    mpesa_code = Payment.normalize_mpesa_code(mpesa_code)
    existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if (
            existing.invoice_id != invoice_id
            or existing.amount != amount
            or existing.cash_account_id != cash_account_id
            or existing.channel != channel
            or existing.mpesa_code != mpesa_code
        ):
            raise ValidationError(
                {
                    "idempotency_key": "This key was already used for a different payment."
                }
            )
        return existing
    if mpesa_code and Payment.objects.filter(mpesa_code=mpesa_code).exists():
        raise ValidationError(
            {"mpesa_code": "This M-Pesa transaction code has already been recorded."}
        )

    invoice = (
        Invoice.objects.select_for_update(of=("self",))
        .select_related("unit", "student", "fee_structure__receivable_account")
        .get(pk=invoice_id)
    )
    cash_account = CashAccount.objects.select_related("account").get(
        pk=cash_account_id, is_active=True
    )
    if amount <= 0 or amount > invoice.balance_due:
        raise ValidationError(
            {"amount": "Payment must be positive and no greater than the balance due."}
        )
    expected_kind = {
        Payment.Channel.CASH: CashAccount.Kind.DRAWER,
        Payment.Channel.MPESA_AGENT: CashAccount.Kind.MPESA_AGENT,
        Payment.Channel.BANK: CashAccount.Kind.BANK,
    }[channel]
    if cash_account.kind != expected_kind:
        raise ValidationError(
            {
                "cash_account": "The cash account kind does not match the payment channel."
            }
        )
    if channel == Payment.Channel.MPESA_AGENT and not mpesa_code:
        raise ValidationError({"mpesa_code": "An M-Pesa transaction code is required."})
    if channel != Payment.Channel.MPESA_AGENT and mpesa_code:
        raise ValidationError(
            {"mpesa_code": "M-Pesa codes are only accepted for M-Pesa payments."}
        )
    entry_date = received_at.date()
    if timezone.is_aware(received_at):
        entry_date = timezone.localtime(received_at).date()
    payment_id = Payment._meta.pk.default()
    entry = post_journal_entry(
        entry_date=entry_date,
        memo=f"Payment for invoice {invoice.number}",
        source_type=JournalEntry.SourceType.PAYMENT,
        source_id=payment_id,
        actor=actor,
        idempotency_key=f"payment:{idempotency_key}",
        lines=(
            {
                "account": cash_account.account,
                "unit": invoice.unit,
                "cash_account": cash_account,
                "student": invoice.student,
                "debit": amount,
            },
            {
                "account": invoice.fee_structure.receivable_account,
                "unit": invoice.unit,
                "student": invoice.student,
                "credit": amount,
            },
        ),
    )
    payment = Payment.objects.create(
        id=payment_id,
        invoice=invoice,
        cash_account=cash_account,
        amount=amount,
        channel=channel,
        mpesa_code=mpesa_code,
        payer_phone=payer_phone,
        received_at=received_at,
        idempotency_key=idempotency_key,
        journal_entry=entry,
    )
    invoice.balance_due -= amount
    invoice.status = (
        Invoice.Status.PAID if invoice.balance_due == 0 else Invoice.Status.PARTIAL
    )
    invoice.save(update_fields=("balance_due", "status", "updated_at"))
    receipt = Receipt.objects.create(
        payment=payment,
        number=f"RCT-{invoice.unit.code}-{payment.id.hex[:16].upper()}",
        issued_at=timezone.now(),
    )
    record_audit(
        actor=actor,
        action="finance_payment_recorded",
        obj=payment,
        unit=get_object_unit(payment),
        after={
            "invoice_id": invoice.id,
            "amount": amount,
            "channel": channel,
            "receipt": receipt.number,
        },
    )
    return payment


@transaction.atomic
def request_adjustment(*, invoice_id, amount, reason, actor):
    amount = _money(amount)
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.status == Invoice.Status.VOID:
        raise ValidationError({"invoice": "A voided invoice cannot be adjusted."})
    if amount <= 0 or amount > invoice.balance_due:
        raise ValidationError(
            {
                "amount": "Adjustment must be positive and no greater than the balance due."
            }
        )
    adjustment = Adjustment.objects.create(
        invoice=invoice, amount=amount, reason=reason, requested_by=actor
    )
    record_audit(
        actor=actor,
        action="finance_adjustment_requested",
        obj=adjustment,
        unit=get_object_unit(adjustment),
    )
    return adjustment


@transaction.atomic
def approve_adjustment(*, adjustment_id, actor):
    adjustment = (
        Adjustment.objects.select_for_update(of=("self",))
        .select_related(
            "invoice__fee_structure__discount_account",
            "invoice__fee_structure__receivable_account",
            "invoice__student",
            "invoice__unit",
        )
        .get(pk=adjustment_id)
    )
    if adjustment.status != Adjustment.Status.REQUESTED:
        raise ValidationError({"status": "Only requested adjustments may be approved."})
    if adjustment.requested_by_id == actor.pk:
        raise ValidationError(
            {"approved_by": "The requester cannot approve their adjustment."}
        )
    invoice = Invoice.objects.select_for_update().get(pk=adjustment.invoice_id)
    if invoice.status == Invoice.Status.VOID:
        raise ValidationError({"invoice": "A voided invoice cannot be adjusted."})
    if invoice.status == Invoice.Status.VOID:
        raise ValidationError({"invoice": "A voided invoice cannot be adjusted."})
    if adjustment.amount > invoice.balance_due:
        raise ValidationError(
            {"amount": "The adjustment exceeds the current balance due."}
        )
    fee = invoice.fee_structure
    if fee.discount_account is None:
        raise ValidationError(
            {
                "fee_structure": "A discount account must be configured before approving waivers."
            }
        )
    entry = post_journal_entry(
        entry_date=timezone.localdate(),
        memo=f"Adjustment for invoice {invoice.number}: {adjustment.reason}",
        source_type=JournalEntry.SourceType.ADJUSTMENT,
        source_id=adjustment.id,
        actor=actor,
        lines=(
            {
                "account": fee.discount_account,
                "unit": invoice.unit,
                "student": invoice.student,
                "debit": adjustment.amount,
            },
            {
                "account": fee.receivable_account,
                "unit": invoice.unit,
                "student": invoice.student,
                "credit": adjustment.amount,
            },
        ),
    )
    invoice.balance_due -= adjustment.amount
    invoice.status = (
        Invoice.Status.PAID
        if invoice.balance_due == 0
        else (
            Invoice.Status.PARTIAL
            if invoice.balance_due < invoice.amount
            else Invoice.Status.OPEN
        )
    )
    invoice.save(update_fields=("balance_due", "status", "updated_at"))
    adjustment.status = Adjustment.Status.POSTED
    adjustment.approved_by = actor
    adjustment.journal_entry = entry
    adjustment.save(
        update_fields=("status", "approved_by", "journal_entry", "updated_at")
    )
    record_audit(
        actor=actor,
        action="finance_adjustment_approved",
        obj=adjustment,
        unit=get_object_unit(adjustment),
        after={"amount": adjustment.amount, "journal_entry_id": entry.id},
    )
    return adjustment


@transaction.atomic
def request_refund(*, payment_id, cash_account_id, amount, reason, actor):
    amount = _money(amount)
    payment = (
        Payment.objects.select_for_update()
        .select_related("invoice__fee_structure")
        .get(pk=payment_id)
    )
    if payment.journal_entry.reversal_entries.exists():
        raise ValidationError({"payment": "A reversed payment cannot be refunded."})
    cash_account = CashAccount.objects.get(pk=cash_account_id, is_active=True)
    previously_refunded = payment.refunds.filter(
        status__in=(Refund.Status.REQUESTED, Refund.Status.POSTED)
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    if amount <= 0 or previously_refunded + amount > payment.amount:
        raise ValidationError({"amount": "Refunds cannot exceed the payment amount."})
    if cash_account.kind != payment.cash_account.kind:
        raise ValidationError(
            {"cash_account": "Refunds must use the original payment channel."}
        )
    refund = Refund.objects.create(
        payment=payment,
        cash_account=cash_account,
        amount=amount,
        reason=reason,
        requested_by=actor,
    )
    record_audit(
        actor=actor,
        action="finance_refund_requested",
        obj=refund,
        unit=get_object_unit(refund),
    )
    return refund


@transaction.atomic
def approve_refund(*, refund_id, actor):
    refund = (
        Refund.objects.select_for_update(of=("self",))
        .select_related(
            "payment__invoice__fee_structure__refund_account",
            "payment__invoice__unit",
            "payment__invoice__student",
            "cash_account__account",
        )
        .get(pk=refund_id)
    )
    if refund.status != Refund.Status.REQUESTED:
        raise ValidationError({"status": "Only requested refunds may be approved."})
    if refund.requested_by_id == actor.pk:
        raise ValidationError(
            {"approved_by": "The requester cannot approve their refund."}
        )
    payment = (
        Payment.objects.select_for_update(of=("self",))
        .select_related("journal_entry")
        .get(pk=refund.payment_id)
    )
    if payment.journal_entry.reversal_entries.exists():
        raise ValidationError({"payment": "A reversed payment cannot be refunded."})
    fee = refund.payment.invoice.fee_structure
    if fee.refund_account is None:
        raise ValidationError(
            {
                "fee_structure": "A refund account must be configured before approving refunds."
            }
        )
    entry = post_journal_entry(
        entry_date=timezone.localdate(),
        memo=f"Refund for invoice {refund.payment.invoice.number}: {refund.reason}",
        source_type=JournalEntry.SourceType.REFUND,
        source_id=refund.id,
        actor=actor,
        lines=(
            {
                "account": fee.refund_account,
                "unit": refund.payment.invoice.unit,
                "student": refund.payment.invoice.student,
                "debit": refund.amount,
            },
            {
                "account": refund.cash_account.account,
                "unit": refund.payment.invoice.unit,
                "cash_account": refund.cash_account,
                "student": refund.payment.invoice.student,
                "credit": refund.amount,
            },
        ),
    )
    refund.status = Refund.Status.POSTED
    refund.approved_by = actor
    refund.journal_entry = entry
    refund.save(update_fields=("status", "approved_by", "journal_entry", "updated_at"))
    record_audit(
        actor=actor,
        action="finance_refund_approved",
        obj=refund,
        unit=get_object_unit(refund),
        after={"amount": refund.amount, "journal_entry_id": entry.id},
    )
    return refund


@transaction.atomic
def reverse_journal_entry(*, entry_id, reason, actor):
    original = JournalEntry.objects.select_for_update().get(pk=entry_id)
    if original.reversal_entries.exists():
        raise ValidationError(
            {"entry": "This journal entry has already been reversed."}
        )
    original_lines = list(
        original.lines.select_related("account", "unit", "cash_account", "student")
    )
    reversal = post_journal_entry(
        entry_date=timezone.localdate(),
        memo=f"Reversal of {original.memo}",
        source_type=JournalEntry.SourceType.REVERSAL,
        source_id=original.id,
        actor=actor,
        reverses=original,
        reversal_reason=reason,
        lines=[
            {
                "account": line.account,
                "unit": line.unit,
                "cash_account": line.cash_account,
                "student": line.student,
                "debit": line.credit,
                "credit": line.debit,
            }
            for line in original_lines
        ],
    )
    reversal_unit = get_object_unit(reversal)
    record_audit(
        actor=actor,
        action="finance_journal_reversed",
        obj=reversal,
        unit=reversal_unit,
        group_level=reversal_unit is None,
        after={"reverses_id": original.id, "reason": reason},
    )
    return reversal


@transaction.atomic
def void_invoice(*, invoice_id, reason, actor):
    invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
    if invoice.status == Invoice.Status.VOID:
        raise ValidationError({"status": "This invoice has already been voided."})
    _require_different_actor(actor, invoice.journal_entry.created_by, "invoice")
    if invoice.payments.filter(journal_entry__reversal_entries__isnull=True).exists():
        raise ValidationError(
            {"invoice": "Reverse its payments before voiding this invoice."}
        )
    if invoice.adjustments.filter(
        status=Adjustment.Status.POSTED,
        journal_entry__reversal_entries__isnull=True,
    ).exists():
        raise ValidationError(
            {"invoice": "Reverse its adjustments before voiding this invoice."}
        )

    reversal = reverse_journal_entry(
        entry_id=invoice.journal_entry_id, reason=reason, actor=actor
    )
    invoice.status = Invoice.Status.VOID
    invoice.balance_due = Decimal("0.00")
    invoice.save(update_fields=("status", "balance_due", "updated_at"))
    record_audit(
        actor=actor,
        action="finance_invoice_voided",
        obj=invoice,
        unit=get_object_unit(invoice),
        after={"reversal_entry_id": reversal.id, "reason": reason},
    )
    return invoice


@transaction.atomic
def reverse_payment(*, payment_id, reason, actor):
    payment = (
        Payment.objects.select_for_update(of=("self",))
        .select_related("journal_entry")
        .get(pk=payment_id)
    )
    if payment.journal_entry.reversal_entries.exists():
        raise ValidationError({"payment": "This payment has already been reversed."})
    _require_different_actor(actor, payment.journal_entry.created_by, "payment")
    if payment.refunds.exclude(status=Refund.Status.REVERSED).exists():
        raise ValidationError(
            {"payment": "Reverse or resolve its refunds before reversing this payment."}
        )

    invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    if invoice.status == Invoice.Status.VOID:
        raise ValidationError({"invoice": "A voided invoice cannot be changed."})
    if invoice.balance_due + payment.amount > invoice.amount:
        raise ValidationError(
            {"payment": "Reversing this payment would overstate the balance."}
        )
    reversal = reverse_journal_entry(
        entry_id=payment.journal_entry_id, reason=reason, actor=actor
    )
    invoice.balance_due += payment.amount
    invoice.status = (
        Invoice.Status.PAID
        if invoice.balance_due == 0
        else Invoice.Status.OPEN
        if invoice.balance_due == invoice.amount
        else Invoice.Status.PARTIAL
    )
    invoice.save(update_fields=("balance_due", "status", "updated_at"))
    record_audit(
        actor=actor,
        action="finance_payment_reversed",
        obj=payment,
        unit=get_object_unit(payment),
        after={"reversal_entry_id": reversal.id, "reason": reason},
    )
    return payment


@transaction.atomic
def reverse_adjustment(*, adjustment_id, reason, actor):
    adjustment = (
        Adjustment.objects.select_for_update(of=("self",))
        .select_related("invoice", "journal_entry")
        .get(pk=adjustment_id)
    )
    if adjustment.status != Adjustment.Status.POSTED:
        raise ValidationError({"status": "Only posted adjustments may be reversed."})
    if adjustment.journal_entry.reversal_entries.exists():
        raise ValidationError(
            {"adjustment": "This adjustment has already been reversed."}
        )
    _require_different_actor(actor, adjustment.requested_by, "adjustment")
    _require_different_actor(actor, adjustment.journal_entry.created_by, "adjustment")

    invoice = Invoice.objects.select_for_update().get(pk=adjustment.invoice_id)
    if invoice.status == Invoice.Status.VOID:
        raise ValidationError({"invoice": "A voided invoice cannot be changed."})
    if invoice.balance_due + adjustment.amount > invoice.amount:
        raise ValidationError(
            {"adjustment": "Reversing this adjustment would overstate the balance."}
        )
    reversal = reverse_journal_entry(
        entry_id=adjustment.journal_entry_id, reason=reason, actor=actor
    )
    invoice.balance_due += adjustment.amount
    invoice.status = (
        Invoice.Status.PAID
        if invoice.balance_due == 0
        else Invoice.Status.OPEN
        if invoice.balance_due == invoice.amount
        else Invoice.Status.PARTIAL
    )
    invoice.save(update_fields=("balance_due", "status", "updated_at"))
    adjustment.status = Adjustment.Status.REVERSED
    adjustment.save(update_fields=("status", "updated_at"))
    record_audit(
        actor=actor,
        action="finance_adjustment_reversed",
        obj=adjustment,
        unit=get_object_unit(adjustment),
        after={"reversal_entry_id": reversal.id, "reason": reason},
    )
    return adjustment


@transaction.atomic
def reverse_refund(*, refund_id, reason, actor):
    refund = (
        Refund.objects.select_for_update(of=("self",))
        .select_related("journal_entry")
        .get(pk=refund_id)
    )
    if refund.status != Refund.Status.POSTED:
        raise ValidationError({"status": "Only posted refunds may be reversed."})
    if refund.journal_entry.reversal_entries.exists():
        raise ValidationError({"refund": "This refund has already been reversed."})
    _require_different_actor(actor, refund.journal_entry.created_by, "refund")

    reversal = reverse_journal_entry(
        entry_id=refund.journal_entry_id, reason=reason, actor=actor
    )
    refund.status = Refund.Status.REVERSED
    refund.save(update_fields=("status", "updated_at"))
    record_audit(
        actor=actor,
        action="finance_refund_reversed",
        obj=refund,
        unit=get_object_unit(refund),
        after={"reversal_entry_id": reversal.id, "reason": reason},
    )
    return refund


def validate_period(period):
    try:
        period.full_clean()
    except DjangoValidationError as exc:
        raise ValidationError(
            exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        ) from exc

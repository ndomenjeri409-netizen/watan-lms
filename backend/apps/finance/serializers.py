from decimal import Decimal

from rest_framework import serializers

from apps.accounts.roles import ADMIN_ROLES, Role

from .models import (
    Account,
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


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ("id", "code", "name", "type", "parent", "is_active")
        read_only_fields = fields


class CashAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashAccount
        fields = (
            "id",
            "account",
            "kind",
            "name",
            "custody_unit",
            "custodian",
            "imprest_limit",
            "is_active",
        )
        read_only_fields = fields


class FeeStructureSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeStructure
        fields = (
            "id",
            "unit",
            "code",
            "name",
            "amount",
            "receivable_account",
            "income_account",
            "discount_account",
            "refund_account",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        instance = self.instance
        accounts = {
            "receivable_account": attrs.get(
                "receivable_account",
                getattr(instance, "receivable_account", None),
            ),
            "income_account": attrs.get(
                "income_account", getattr(instance, "income_account", None)
            ),
            "discount_account": attrs.get(
                "discount_account", getattr(instance, "discount_account", None)
            ),
            "refund_account": attrs.get(
                "refund_account", getattr(instance, "refund_account", None)
            ),
        }
        expected = {
            "receivable_account": Account.Type.ASSET,
            "income_account": Account.Type.INCOME,
            "discount_account": Account.Type.EXPENSE,
            "refund_account": Account.Type.INCOME,
        }
        errors = {
            field: "Select an account of the required type."
            for field, account in accounts.items()
            if account is not None and account.type != expected[field]
        }
        if errors:
            raise serializers.ValidationError(errors)
        unit = attrs.get("unit", getattr(instance, "unit", None))
        if unit is None:
            raise serializers.ValidationError({"unit": "A business unit is required."})
        if not unit.is_active:
            raise serializers.ValidationError(
                {"unit": "Select an active business unit."}
            )
        return attrs


class InvoiceSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_registration_number = serializers.CharField(
        source="student.registration_number", read_only=True
    )

    class Meta:
        model = Invoice
        fields = (
            "id",
            "number",
            "student",
            "student_name",
            "student_registration_number",
            "unit",
            "fee_structure",
            "issue_date",
            "due_date",
            "amount",
            "balance_due",
            "status",
            "journal_entry",
            "created_at",
        )
        read_only_fields = fields

    def get_student_name(self, obj) -> str:
        return f"{obj.student.first_name} {obj.student.last_name}"


class InvoiceCreateSerializer(serializers.Serializer):
    student = serializers.UUIDField()
    fee_structure = serializers.UUIDField()
    issue_date = serializers.DateField()
    due_date = serializers.DateField()
    idempotency_key = serializers.CharField(max_length=64)


class ReceiptSerializer(serializers.ModelSerializer):
    pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = ("id", "number", "issued_at", "pdf_url")
        read_only_fields = fields

    def get_pdf_url(self, obj) -> str:
        return f"/api/v1/receipts/{obj.pk}/pdf/"


class PaymentSerializer(serializers.ModelSerializer):
    receipt = ReceiptSerializer(read_only=True)
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    student_name = serializers.SerializerMethodField()
    student_registration_number = serializers.CharField(
        source="invoice.student.registration_number", read_only=True
    )

    class Meta:
        model = Payment
        fields = (
            "id",
            "invoice",
            "invoice_number",
            "student_name",
            "student_registration_number",
            "cash_account",
            "amount",
            "channel",
            "mpesa_code",
            "payer_phone",
            "received_at",
            "receipt",
            "journal_entry",
            "created_at",
        )
        read_only_fields = fields

    def get_student_name(self, obj) -> str:
        return f"{obj.invoice.student.first_name} {obj.invoice.student.last_name}"


class PaymentCreateSerializer(serializers.Serializer):
    invoice = serializers.UUIDField()
    cash_account = serializers.UUIDField()
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    channel = serializers.ChoiceField(choices=Payment.Channel.choices)
    received_at = serializers.DateTimeField()
    idempotency_key = serializers.CharField(max_length=64)
    mpesa_code = serializers.CharField(max_length=32, required=False, allow_blank=True)
    payer_phone = serializers.CharField(max_length=32, required=False, allow_blank=True)


class AdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Adjustment
        fields = (
            "id",
            "invoice",
            "amount",
            "reason",
            "requested_by",
            "approved_by",
            "status",
            "journal_entry",
            "created_at",
        )
        read_only_fields = fields


class AdjustmentCreateSerializer(serializers.Serializer):
    invoice = serializers.UUIDField()
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    reason = serializers.CharField(max_length=255, allow_blank=False)


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = (
            "id",
            "payment",
            "cash_account",
            "amount",
            "reason",
            "requested_by",
            "approved_by",
            "status",
            "journal_entry",
            "created_at",
        )
        read_only_fields = fields


class RefundCreateSerializer(serializers.Serializer):
    payment = serializers.UUIDField()
    cash_account = serializers.UUIDField()
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    reason = serializers.CharField(max_length=255, allow_blank=False)


class ReversalRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, allow_blank=False)


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)

    class Meta:
        model = JournalLine
        fields = (
            "id",
            "account",
            "account_code",
            "unit",
            "unit_code",
            "cash_account",
            "debit",
            "credit",
            "student",
        )
        read_only_fields = fields


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)

    class Meta:
        model = JournalEntry
        fields = (
            "id",
            "date",
            "memo",
            "source_type",
            "source_id",
            "status",
            "reverses",
            "reversal_reason",
            "lines",
            "created_at",
        )
        read_only_fields = fields


class StudentStatementLineSerializer(serializers.ModelSerializer):
    date = serializers.DateField(source="entry.date", read_only=True)
    memo = serializers.CharField(source="entry.memo", read_only=True)
    account_code = serializers.CharField(source="account.code", read_only=True)

    class Meta:
        model = JournalLine
        fields = ("id", "date", "memo", "account_code", "debit", "credit")
        read_only_fields = fields


class StudentStatementSerializer(serializers.Serializer):
    student = serializers.UUIDField()
    registration_number = serializers.CharField()
    balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    lines = StudentStatementLineSerializer(many=True)


def may_read_all_finance(user):
    return user.has_global_read() or user.has_group_bursar_assignment()


def may_read_unit_finance(user, unit_id):
    return may_read_all_finance(user) or unit_id in user.unit_ids()


def may_approve_finance(user):
    return user.has_role(*ADMIN_ROLES, Role.UNIT_MANAGER)

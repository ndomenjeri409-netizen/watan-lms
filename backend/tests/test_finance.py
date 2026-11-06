import json
import uuid
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.audit.models import AuditLog
from apps.files.models import StoredFile
from apps.finance.admin import PaymentAdmin
from apps.finance.models import (
    Account,
    AccountingPeriod,
    CashAccount,
    FeeStructure,
    Invoice,
    JournalEntry,
    JournalLine,
    Payment,
    Receipt,
)
from apps.finance.services import post_journal_entry
from apps.org.models import BusinessUnit, Department
from apps.people.models import Student
from tests.helpers import postgres_only


class FinanceFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.department = Department.objects.create(
            unit=self.unit, name="ICT", code="ICT"
        )
        self.bursar = User.objects.create_user(
            "bursar", role=Role.BURSAR, unit=self.unit
        )
        self.approver = User.objects.create_user("admin", role=Role.ADMIN)
        student_user = User.objects.create_user("student")
        self.student = Student.objects.create(
            user=student_user,
            department=self.department,
            registration_number="ICT-2026-0001",
            first_name="Amina",
            last_name="Njeri",
            email="amina@example.test",
            admission_year=2026,
        )
        self.student_user = student_user

        self.receivable_account = self.create_account(
            "1100", "Student receivables", Account.Type.ASSET
        )
        self.cash_account_record = self.create_account(
            "1010", "M-Pesa agent float", Account.Type.ASSET
        )
        self.income_account = self.create_account(
            "4000", "Student fee income", Account.Type.INCOME
        )
        self.discount_account = self.create_account(
            "4900", "Fee discounts", Account.Type.EXPENSE
        )
        self.refund_account = self.create_account(
            "4100", "Fee refunds", Account.Type.INCOME
        )
        self.cash_account = CashAccount.objects.create(
            account=self.cash_account_record,
            kind=CashAccount.Kind.MPESA_AGENT,
            name="Agent float",
            custody_unit=self.unit,
            custodian=self.bursar,
        )
        self.drawer_account = self.create_account(
            "1020", "Unit cash drawer", Account.Type.ASSET
        )
        self.drawer = CashAccount.objects.create(
            account=self.drawer_account,
            kind=CashAccount.Kind.DRAWER,
            name="Unit cash drawer",
            custody_unit=self.unit,
            custodian=self.bursar,
        )
        self.fee_structure = FeeStructure.objects.create(
            unit=self.unit,
            code="TUITION",
            name="Tuition",
            amount=Decimal("1000.00"),
            receivable_account=self.receivable_account,
            income_account=self.income_account,
            discount_account=self.discount_account,
            refund_account=self.refund_account,
        )
        AccountingPeriod.objects.create(start=date(2026, 1, 1), end=date(2026, 12, 31))

    @staticmethod
    def create_account(code, name, account_type):
        return Account.objects.create(code=code, name=name, type=account_type)

    def create_invoice(
        self, idempotency_key=None, *, student=None, fee_structure=None, actor=None
    ):
        self.client.force_authenticate(actor or self.bursar)
        response = self.client.post(
            "/api/v1/invoices/",
            {
                "student": str((student or self.student).pk),
                "fee_structure": str((fee_structure or self.fee_structure).pk),
                "issue_date": "2026-11-01",
                "due_date": "2026-11-30",
                "idempotency_key": idempotency_key or f"invoice-{uuid.uuid4().hex}",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def record_mpesa_payment(
        self,
        invoice_id,
        amount="500.00",
        code="QX12345678",
        *,
        cash_account=None,
        actor=None,
    ):
        self.client.force_authenticate(actor or self.bursar)
        return self.client.post(
            "/api/v1/payments/",
            {
                "invoice": invoice_id,
                "cash_account": str((cash_account or self.cash_account).pk),
                "amount": amount,
                "channel": Payment.Channel.MPESA_AGENT,
                "received_at": timezone.now().isoformat(),
                "idempotency_key": f"payment-{code}",
                "mpesa_code": code,
            },
            format="json",
        )

    @patch("apps.finance.views.get_storage_client")
    def test_invoice_payment_receipt_and_student_statement_are_scoped(
        self, get_storage_client
    ):
        storage = get_storage_client.return_value
        storage.get_object.side_effect = lambda **kwargs: {
            "Body": BytesIO(storage.put_object.call_args.kwargs["Body"])
        }
        invoice = self.create_invoice()
        invoice_record = Invoice.objects.get(pk=invoice["id"])
        invoice_lines = list(invoice_record.journal_entry.lines.all())
        self.assertEqual(
            sum((line.debit for line in invoice_lines), Decimal("0.00")),
            Decimal("1000.00"),
        )
        self.assertEqual(
            sum((line.credit for line in invoice_lines), Decimal("0.00")),
            Decimal("1000.00"),
        )

        payment_response = self.record_mpesa_payment(invoice["id"])
        self.assertEqual(payment_response.status_code, 201, payment_response.content)
        self.assertTrue(payment_response.json()["receipt"]["number"])

        self.client.force_authenticate(self.student_user)
        response = self.client.get("/api/v1/invoices/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            [row["id"] for row in response.json()["results"]], [invoice["id"]]
        )
        statement = self.client.get(f"/api/v1/students/{self.student.pk}/statement/")
        self.assertEqual(statement.status_code, 200, statement.content)
        self.assertEqual(Decimal(str(statement.json()["balance"])), Decimal("500.00"))
        receipt_id = payment_response.json()["receipt"]["id"]
        receipt_pdf = self.client.get(f"/api/v1/receipts/{receipt_id}/pdf/")
        self.assertEqual(receipt_pdf.status_code, 200, receipt_pdf.content)
        self.assertEqual(receipt_pdf["Content-Type"], "application/pdf")
        self.assertTrue(receipt_pdf.content.startswith(b"%PDF"))
        stored_receipt = Receipt.objects.get(pk=receipt_id)
        self.assertEqual(
            stored_receipt.generated_file.purpose, StoredFile.Purpose.GENERATED
        )
        self.assertEqual(stored_receipt.generated_file.status, StoredFile.Status.READY)
        self.assertEqual(storage.put_object.call_count, 1)

        repeated_pdf = self.client.get(f"/api/v1/receipts/{receipt_id}/pdf/")
        self.assertEqual(repeated_pdf.status_code, 200, repeated_pdf.content)
        self.assertEqual(repeated_pdf.content, receipt_pdf.content)
        self.assertEqual(storage.put_object.call_count, 1)

        other_user = User.objects.create_user("other-student")
        other_student = Student.objects.create(
            user=other_user,
            department=self.department,
            registration_number="ICT-2026-0002",
            first_name="Juma",
            last_name="Otieno",
            email="juma@example.test",
            admission_year=2026,
        )
        denied = self.client.get(f"/api/v1/students/{other_student.pk}/statement/")
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(other_user)
        denied_receipt = self.client.get(f"/api/v1/receipts/{receipt_id}/pdf/")
        self.assertEqual(denied_receipt.status_code, 403)

    def test_journal_student_balance_matches_invoices_across_units_and_posting_orders(
        self,
    ):
        second_unit = BusinessUnit.objects.create(
            code="WTC", name="Watan Technical College", kind=BusinessUnit.Kind.ACADEMIC
        )
        second_department = Department.objects.create(
            unit=second_unit, name="Engineering", code="ENG"
        )
        second_bursar = User.objects.create_user(
            "second-bursar", role=Role.BURSAR, unit=second_unit
        )
        second_manager = User.objects.create_user(
            "second-manager", role=Role.UNIT_MANAGER, unit=second_unit
        )
        second_cash_account_record = self.create_account(
            "1011", "Second unit M-Pesa float", Account.Type.ASSET
        )
        second_cash_account = CashAccount.objects.create(
            account=second_cash_account_record,
            kind=CashAccount.Kind.MPESA_AGENT,
            name="Second unit agent float",
            custody_unit=second_unit,
            custodian=second_bursar,
        )
        second_fee_structure = FeeStructure.objects.create(
            unit=second_unit,
            code="TUITION",
            name="Tuition",
            amount=Decimal("800.00"),
            receivable_account=self.receivable_account,
            income_account=self.income_account,
            discount_account=self.discount_account,
            refund_account=self.refund_account,
        )

        def create_student(suffix):
            user = User.objects.create_user(
                f"balance-student-{suffix}", role=Role.STUDENT
            )
            return Student.objects.create(
                user=user,
                department=self.department,
                registration_number=f"ICT-2026-000{suffix}",
                first_name="Balance",
                last_name=f"Student {suffix}",
                email=f"balance-{suffix}@example.test",
                admission_year=2026,
            )

        def run_scenario(student, suffix, second_unit_events_first):
            invoice_a = self.create_invoice(
                student=student, fee_structure=self.fee_structure, actor=self.bursar
            )
            student.department = second_department
            student.save(update_fields=("department",))
            invoice_b = self.create_invoice(
                student=student,
                fee_structure=second_fee_structure,
                actor=second_bursar,
            )

            def post_adjustment():
                self.client.force_authenticate(self.bursar)
                response = self.client.post(
                    "/api/v1/adjustments/",
                    {
                        "invoice": invoice_a["id"],
                        "amount": "100.00",
                        "reason": "Balance parity test adjustment",
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 201, response.content)
                self.client.force_authenticate(self.approver)
                approved = self.client.post(
                    f"/api/v1/adjustments/{response.json()['id']}/approve/",
                    {},
                    format="json",
                )
                self.assertEqual(approved.status_code, 200, approved.content)

            def post_first_unit_payment():
                response = self.record_mpesa_payment(
                    invoice_a["id"],
                    amount="200.00",
                    code=f"A{suffix}12345678",
                    actor=self.bursar,
                )
                self.assertEqual(response.status_code, 201, response.content)

            def post_and_reverse_second_unit_payment():
                payment = self.record_mpesa_payment(
                    invoice_b["id"],
                    amount="100.00",
                    code=f"B{suffix}12345678",
                    cash_account=second_cash_account,
                    actor=second_bursar,
                )
                self.assertEqual(payment.status_code, 201, payment.content)
                self.client.force_authenticate(second_bursar)
                refund_response = self.client.post(
                    "/api/v1/refunds/",
                    {
                        "payment": payment.json()["id"],
                        "cash_account": str(second_cash_account.pk),
                        "amount": "50.00",
                        "reason": "Balance parity test refund",
                    },
                    format="json",
                )
                self.assertEqual(
                    refund_response.status_code, 201, refund_response.content
                )
                refund_id = refund_response.json()["id"]
                self.client.force_authenticate(self.approver)
                approval = self.client.post(
                    f"/api/v1/refunds/{refund_id}/approve/", {}, format="json"
                )
                self.assertEqual(approval.status_code, 200, approval.content)
                self.client.force_authenticate(second_manager)
                refund_reversal = self.client.post(
                    f"/api/v1/refunds/{refund_id}/reverse/",
                    {"reason": "Balance parity test refund reversal"},
                    format="json",
                )
                self.assertEqual(
                    refund_reversal.status_code, 200, refund_reversal.content
                )
                payment_reversal = self.client.post(
                    f"/api/v1/payments/{payment.json()['id']}/reverse/",
                    {"reason": "Balance parity test payment reversal"},
                    format="json",
                )
                self.assertEqual(
                    payment_reversal.status_code, 200, payment_reversal.content
                )

            if second_unit_events_first:
                post_and_reverse_second_unit_payment()
                post_first_unit_payment()
                post_adjustment()
            else:
                post_adjustment()
                post_first_unit_payment()
                post_and_reverse_second_unit_payment()

            invoice_balance = sum(
                Invoice.objects.filter(student=student).values_list(
                    "balance_due", flat=True
                ),
                Decimal("0.00"),
            )
            self.assertEqual(
                set(
                    Invoice.objects.filter(student=student).values_list(
                        "unit_id", flat=True
                    )
                ),
                {self.unit.pk, second_unit.pk},
            )
            receivable_lines = JournalLine.objects.filter(
                student=student,
                unit__in=(self.unit, second_unit),
                account__fee_receivables__unit__in=(self.unit, second_unit),
            ).distinct()
            journal_balance = sum(
                (line.debit - line.credit for line in receivable_lines),
                Decimal("0.00"),
            )
            self.client.force_authenticate(student.user)
            statement = self.client.get(f"/api/v1/students/{student.pk}/statement/")
            self.assertEqual(statement.status_code, 200, statement.content)
            statement_balance = Decimal(str(statement.json()["balance"]))

            self.assertEqual(invoice_balance, Decimal("1500.00"))
            self.assertEqual(journal_balance, invoice_balance)
            self.assertEqual(statement_balance, journal_balance)
            return statement_balance

        first_balance = run_scenario(create_student("2"), "2", False)
        second_balance = run_scenario(create_student("3"), "3", True)
        self.assertEqual(first_balance, second_balance)

    def test_payment_is_idempotent_and_mpesa_code_is_globally_unique(self):
        first_invoice = self.create_invoice()
        first = self.record_mpesa_payment(first_invoice["id"], code="  qx12345678 \t")
        replay = self.record_mpesa_payment(first_invoice["id"], code="  qx12345678 \t")
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(replay.status_code, 201, replay.content)
        self.assertEqual(first.json()["id"], replay.json()["id"])
        self.assertEqual(first.json()["mpesa_code"], "QX12345678")
        self.assertEqual(Payment.objects.count(), 1)

        second_invoice = self.create_invoice()
        self.client.force_authenticate(self.bursar)
        duplicate_code = self.client.post(
            "/api/v1/payments/",
            {
                "invoice": second_invoice["id"],
                "cash_account": str(self.cash_account.pk),
                "amount": "100.00",
                "channel": Payment.Channel.MPESA_AGENT,
                "received_at": timezone.now().isoformat(),
                "idempotency_key": "different-payment",
                "mpesa_code": " \t QX12345678 \n",
            },
            format="json",
        )
        self.assertEqual(duplicate_code.status_code, 400, duplicate_code.content)
        self.assertEqual(Payment.objects.count(), 1)

    def test_cash_payment_normalizes_blank_mpesa_code_to_null(self):
        invoice = self.create_invoice()
        self.client.force_authenticate(self.bursar)
        response = self.client.post(
            "/api/v1/payments/",
            {
                "invoice": invoice["id"],
                "cash_account": str(self.drawer.pk),
                "amount": "100.00",
                "channel": Payment.Channel.CASH,
                "received_at": timezone.now().isoformat(),
                "idempotency_key": "cash-payment-no-mpesa-code",
                "mpesa_code": "   ",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        payment = Payment.objects.get(pk=response.json()["id"])
        self.assertIsNone(payment.mpesa_code)

    def test_payment_model_and_admin_normalize_mpesa_code_before_save(self):
        invoice = self.create_invoice()
        response = self.record_mpesa_payment(invoice["id"], code="QX12345678")
        self.assertEqual(response.status_code, 201, response.content)
        payment = Payment.objects.get(pk=response.json()["id"])

        payment.mpesa_code = "  qx12345678 "
        payment.save(update_fields=("mpesa_code",))
        self.assertEqual(payment.mpesa_code, "QX12345678")

        payment.mpesa_code = "  qx12345678 "
        PaymentAdmin(Payment, admin.site).save_model(None, payment, None, True)
        payment.refresh_from_db()
        self.assertEqual(payment.mpesa_code, "QX12345678")

    def test_invoice_is_idempotent_and_rejects_key_reuse_for_different_request(self):
        self.client.force_authenticate(self.bursar)
        payload = {
            "student": str(self.student.pk),
            "fee_structure": str(self.fee_structure.pk),
            "issue_date": "2026-11-01",
            "due_date": "2026-11-30",
            "idempotency_key": "invoice-retry-1",
        }
        first = self.client.post("/api/v1/invoices/", payload, format="json")
        replay = self.client.post("/api/v1/invoices/", payload, format="json")

        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(replay.status_code, 201, replay.content)
        self.assertEqual(first.json()["id"], replay.json()["id"])
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(JournalEntry.objects.count(), 1)
        invoice_audit = AuditLog.objects.get(
            action="finance_invoice_created", object_id=first.json()["id"]
        )
        journal_audit = AuditLog.objects.get(
            action="finance_journal_posted",
            object_id=first.json()["journal_entry"],
        )
        self.assertEqual(invoice_audit.unit, self.unit)
        self.assertEqual(journal_audit.unit, self.unit)

        changed_payload = {**payload, "due_date": "2026-12-01"}
        conflict = self.client.post("/api/v1/invoices/", changed_payload, format="json")
        self.assertEqual(conflict.status_code, 400, conflict.content)
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(JournalEntry.objects.count(), 1)

    def test_invoice_creation_enforces_role_and_unit_scope(self):
        payload = {
            "student": str(self.student.pk),
            "fee_structure": str(self.fee_structure.pk),
            "issue_date": "2026-11-01",
            "due_date": "2026-11-30",
            "idempotency_key": "invoice-wrong-unit",
        }
        other_unit = BusinessUnit.objects.create(
            code="WTA",
            name="Watan Technical Academy",
            kind=BusinessUnit.Kind.ACADEMIC,
        )
        other_bursar = User.objects.create_user(
            "other-bursar", role=Role.BURSAR, unit=other_unit
        )

        self.client.force_authenticate(other_bursar)
        wrong_unit_response = self.client.post(
            "/api/v1/invoices/", payload, format="json"
        )
        self.assertEqual(wrong_unit_response.status_code, 403)

        self.client.force_authenticate(self.student_user)
        wrong_role_response = self.client.post(
            "/api/v1/invoices/", payload, format="json"
        )
        self.assertEqual(wrong_role_response.status_code, 403)
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_adjustment_and_refund_require_separate_approval(self):
        invoice = self.create_invoice()
        self.client.force_authenticate(self.bursar)
        adjustment_response = self.client.post(
            "/api/v1/adjustments/",
            {
                "invoice": invoice["id"],
                "amount": "100.00",
                "reason": "Approved fee waiver",
            },
            format="json",
        )
        self.assertEqual(
            adjustment_response.status_code, 201, adjustment_response.content
        )
        adjustment = adjustment_response.json()

        self.client.force_authenticate(self.bursar)
        self.assertEqual(
            self.client.post(
                f"/api/v1/adjustments/{adjustment['id']}/approve/", {}, format="json"
            ).status_code,
            403,
        )
        self.client.force_authenticate(self.approver)
        self.assertEqual(
            self.client.post(
                f"/api/v1/adjustments/{adjustment['id']}/approve/", {}, format="json"
            ).status_code,
            200,
        )
        invoice_record = Invoice.objects.get(pk=invoice["id"])
        self.assertEqual(invoice_record.balance_due, Decimal("900.00"))

        payment = self.record_mpesa_payment(invoice["id"], amount="500.00")
        self.assertEqual(payment.status_code, 201, payment.content)
        self.client.force_authenticate(self.bursar)
        refund_response = self.client.post(
            "/api/v1/refunds/",
            {
                "payment": payment.json()["id"],
                "cash_account": str(self.cash_account.pk),
                "amount": "100.00",
                "reason": "Approved refund",
            },
            format="json",
        )
        self.assertEqual(refund_response.status_code, 201, refund_response.content)
        refund = refund_response.json()
        self.client.force_authenticate(self.approver)
        approved_refund = self.client.post(
            f"/api/v1/refunds/{refund['id']}/approve/", {}, format="json"
        )
        self.assertEqual(approved_refund.status_code, 200, approved_refund.content)
        self.assertEqual(approved_refund.json()["status"], "POSTED")

    def test_reversals_restore_balances_and_preserve_original_entries(self):
        invoice = self.create_invoice()
        self.client.force_authenticate(self.bursar)
        adjustment_response = self.client.post(
            "/api/v1/adjustments/",
            {
                "invoice": invoice["id"],
                "amount": "100.00",
                "reason": "Fee waiver",
            },
            format="json",
        )
        self.assertEqual(adjustment_response.status_code, 201)
        adjustment_id = adjustment_response.json()["id"]

        self.client.force_authenticate(self.approver)
        self.assertEqual(
            self.client.post(
                f"/api/v1/adjustments/{adjustment_id}/approve/", {}, format="json"
            ).status_code,
            200,
        )
        payment = self.record_mpesa_payment(invoice["id"], amount="500.00")
        self.assertEqual(payment.status_code, 201, payment.content)

        self.client.force_authenticate(self.bursar)
        refund_response = self.client.post(
            "/api/v1/refunds/",
            {
                "payment": payment.json()["id"],
                "cash_account": str(self.cash_account.pk),
                "amount": "100.00",
                "reason": "Refund",
            },
            format="json",
        )
        self.assertEqual(refund_response.status_code, 201, refund_response.content)
        refund_id = refund_response.json()["id"]
        self.client.force_authenticate(self.approver)
        self.assertEqual(
            self.client.post(
                f"/api/v1/refunds/{refund_id}/approve/", {}, format="json"
            ).status_code,
            200,
        )

        unit_manager = User.objects.create_user(
            "manager", role=Role.UNIT_MANAGER, unit=self.unit
        )
        self.client.force_authenticate(unit_manager)
        refund_reverse = self.client.post(
            f"/api/v1/refunds/{refund_id}/reverse/",
            {"reason": "Refund entered in error"},
            format="json",
        )
        self.assertEqual(refund_reverse.status_code, 200, refund_reverse.content)
        self.assertEqual(refund_reverse.json()["status"], "REVERSED")

        payment_reverse = self.client.post(
            f"/api/v1/payments/{payment.json()['id']}/reverse/",
            {"reason": "Payment entered in error"},
            format="json",
        )
        self.assertEqual(payment_reverse.status_code, 200, payment_reverse.content)
        invoice_record = Invoice.objects.get(pk=invoice["id"])
        self.assertEqual(invoice_record.balance_due, Decimal("900.00"))

        adjustment_reverse = self.client.post(
            f"/api/v1/adjustments/{adjustment_id}/reverse/",
            {"reason": "Waiver entered in error"},
            format="json",
        )
        self.assertEqual(
            adjustment_reverse.status_code, 200, adjustment_reverse.content
        )
        self.assertEqual(adjustment_reverse.json()["status"], "REVERSED")
        invoice_record.refresh_from_db()
        self.assertEqual(invoice_record.balance_due, Decimal("1000.00"))
        self.assertEqual(JournalEntry.objects.filter(reverses__isnull=False).count(), 3)

    def test_void_invoice_uses_reversal_and_disallows_bursar_self_approval(self):
        invoice = self.create_invoice()
        self.client.force_authenticate(self.bursar)
        denied = self.client.post(
            f"/api/v1/invoices/{invoice['id']}/void/",
            {"reason": "Duplicate invoice"},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)

        self.client.force_authenticate(self.approver)
        response = self.client.post(
            f"/api/v1/invoices/{invoice['id']}/void/",
            {"reason": "Duplicate invoice"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Invoice.Status.VOID)
        self.assertEqual(
            Invoice.objects.get(pk=invoice["id"]).balance_due, Decimal("0.00")
        )

    def test_journal_entries_and_lines_are_append_only_and_period_checked(self):
        self.client.force_authenticate(self.bursar)
        invoice = self.create_invoice()
        entry = Invoice.objects.get(pk=invoice["id"]).journal_entry
        entry.memo = "Changed"
        with self.assertRaises(DjangoValidationError):
            entry.save()
        with self.assertRaises(DjangoValidationError):
            entry.delete()

        line = JournalLine.objects.filter(entry=entry).first()
        line.debit = Decimal("999.00")
        with self.assertRaises(DjangoValidationError):
            line.save()
        with self.assertRaises(DjangoValidationError):
            line.delete()

        AccountingPeriod.objects.update(status=AccountingPeriod.Status.CLOSED)
        with self.assertRaises(ValidationError):
            post_journal_entry(
                entry_date=date(2026, 11, 6),
                memo="Must not post",
                source_type=JournalEntry.SourceType.ADJUSTMENT,
                source_id=None,
                actor=self.bursar,
                lines=(
                    {
                        "account": self.discount_account,
                        "unit": self.unit,
                        "debit": Decimal("1.00"),
                    },
                    {
                        "account": self.receivable_account,
                        "unit": self.unit,
                        "credit": Decimal("1.00"),
                    },
                ),
            )
        self.assertEqual(JournalEntry.objects.count(), 1)

    @postgres_only
    def test_database_rejects_journal_updates(self):
        invoice = self.create_invoice()
        entry_id = invoice["journal_entry"]
        with self.assertRaises(DatabaseError), transaction.atomic():
            JournalEntry.objects.filter(pk=entry_id).update(memo="Tampered")
        line_id = (
            JournalLine.objects.filter(entry_id=entry_id)
            .values_list("id", flat=True)
            .first()
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            JournalLine.objects.filter(pk=line_id).update(debit=Decimal("999.00"))

    @postgres_only
    def test_database_rejects_unbalanced_journal_entries(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            JournalEntry.objects.create(
                date=date(2026, 11, 6),
                memo="Unbalanced",
                source_type=JournalEntry.SourceType.ADJUSTMENT,
                created_by=self.bursar,
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET CONSTRAINTS finance_journal_entry_balanced IMMEDIATE"
                )

    @postgres_only
    def test_database_enforces_partial_mpesa_code_uniqueness(self):
        first_invoice = self.create_invoice()
        first_payment = self.record_mpesa_payment(first_invoice["id"])
        self.assertEqual(first_payment.status_code, 201, first_payment.content)
        second_invoice = self.create_invoice()
        entry = post_journal_entry(
            entry_date=date(2026, 11, 6),
            memo="Duplicate M-Pesa code constraint test",
            source_type=JournalEntry.SourceType.PAYMENT,
            source_id=uuid.uuid4(),
            actor=self.bursar,
            idempotency_key="mpesa-constraint-test-entry",
            lines=(
                {
                    "account": self.cash_account_record,
                    "unit": self.unit,
                    "cash_account": self.cash_account,
                    "student": self.student,
                    "debit": Decimal("100.00"),
                },
                {
                    "account": self.receivable_account,
                    "unit": self.unit,
                    "student": self.student,
                    "credit": Decimal("100.00"),
                },
            ),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Payment.objects.create(
                invoice_id=second_invoice["id"],
                cash_account=self.cash_account,
                amount=Decimal("100.00"),
                channel=Payment.Channel.MPESA_AGENT,
                mpesa_code=first_payment.json()["mpesa_code"],
                received_at=timezone.now(),
                idempotency_key="duplicate-mpesa-code-test",
                journal_entry=entry,
            )

    @postgres_only
    def test_database_rejects_non_normalized_mpesa_codes(self):
        invoice = self.create_invoice()
        response = self.record_mpesa_payment(invoice["id"], code="QX12345678")
        self.assertEqual(response.status_code, 201, response.content)
        payment = Payment.objects.get(pk=response.json()["id"])

        for invalid_code in ("qx12345678", " QX12345678 "):
            with (
                self.subTest(mpesa_code=invalid_code),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                Payment.objects.filter(pk=payment.pk).update(mpesa_code=invalid_code)


class FinanceAccountSeedTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.chart_file = Path(self.directory.name) / "chart.json"

    def tearDown(self):
        self.directory.cleanup()

    def seed(self, rows):
        self.chart_file.write_text(json.dumps(rows), encoding="utf-8")
        call_command(
            "seed_finance_accounts",
            file=self.chart_file,
            stdout=StringIO(),
        )

    def test_seed_is_idempotent_and_creates_parent_accounts_first(self):
        self.seed(
            [
                {
                    "code": "1110",
                    "name": "Student receivables",
                    "type": "ASSET",
                    "parent": "1100",
                },
                {"code": "1100", "name": "Receivables", "type": "ASSET"},
            ]
        )
        self.seed(
            [
                {
                    "code": "1110",
                    "name": "Student receivables",
                    "type": "ASSET",
                    "parent": "1100",
                },
                {"code": "1100", "name": "Receivables", "type": "ASSET"},
            ]
        )

        child = Account.objects.get(code="1110")
        self.assertEqual(child.parent.code, "1100")
        self.assertEqual(Account.objects.count(), 2)

    def test_chart_conflict_rolls_back_without_overwriting_existing_accounts(self):
        Account.objects.create(
            code="1000", name="Existing cash", type=Account.Type.ASSET
        )
        with self.assertRaises(CommandError):
            self.seed(
                [
                    {"code": "2000", "name": "New account", "type": "ASSET"},
                    {"code": "1000", "name": "Different name", "type": "ASSET"},
                ]
            )

        self.assertEqual(Account.objects.count(), 1)
        self.assertEqual(Account.objects.get(code="1000").name, "Existing cash")

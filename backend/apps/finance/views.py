from io import BytesIO
from uuid import uuid4
from xml.sax.saxutils import escape

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import Role
from apps.files.models import StoredFile
from apps.files.storage import StorageNotConfigured, get_storage_client
from apps.people.models import Student
from common.scoping import ScopedViewSetMixin

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
from .permissions import FinancePermission, can_manage_unit
from .serializers import (
    AccountSerializer,
    AdjustmentCreateSerializer,
    AdjustmentSerializer,
    CashAccountSerializer,
    FeeStructureSerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    JournalEntrySerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
    RefundCreateSerializer,
    RefundSerializer,
    ReversalRequestSerializer,
    StudentStatementLineSerializer,
    StudentStatementSerializer,
    may_approve_finance,
    may_read_all_finance,
    may_read_unit_finance,
)
from .services import (
    approve_adjustment,
    approve_refund,
    create_invoice,
    record_payment,
    request_adjustment,
    request_refund,
    reverse_adjustment,
    reverse_payment,
    reverse_refund,
    void_invoice,
)


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    permission_classes = (FinancePermission,)
    search_fields = ("code", "name")
    ordering_fields = ("code", "name", "type")


class CashAccountViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CashAccount.objects.select_related("account", "custody_unit").all()
    serializer_class = CashAccountSerializer
    permission_classes = (FinancePermission,)
    filterset_fields = ("kind", "custody_unit", "is_active")

    def get_queryset(self):
        queryset = super().get_queryset()
        if may_read_all_finance(self.request.user):
            return queryset
        return queryset.filter(custody_unit_id__in=self.request.user.unit_ids())


class FeeStructureViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = FeeStructure.objects.select_related(
        "unit",
        "receivable_account",
        "income_account",
        "discount_account",
        "refund_account",
    ).all()
    serializer_class = FeeStructureSerializer
    permission_classes = (FinancePermission,)
    search_fields = ("code", "name", "unit__code")
    filterset_fields = ("unit", "is_active")
    ordering_fields = ("code", "name", "amount", "created_at")

    def perform_create(self, serializer):
        unit = serializer.validated_data["unit"]
        if not can_manage_unit(self.request.user, unit):
            raise PermissionDenied("You may not manage fees for this unit.")
        serializer.save()

    def perform_update(self, serializer):
        unit = serializer.validated_data.get("unit", serializer.instance.unit)
        if not can_manage_unit(self.request.user, unit):
            raise PermissionDenied("You may not manage fees for this unit.")
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_unit(self.request.user, instance.unit):
            raise PermissionDenied("You may not manage fees for this unit.")
        instance.is_active = False
        instance.save(update_fields=("is_active", "updated_at"))


class InvoiceViewSet(
    ScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    student_read_only = True
    queryset = Invoice.objects.select_related(
        "student", "unit", "fee_structure", "journal_entry"
    ).all()
    serializer_class = InvoiceSerializer
    permission_classes = (FinancePermission,)
    search_fields = (
        "number",
        "student__registration_number",
        "student__first_name",
        "student__last_name",
    )
    filterset_fields = ("unit", "student", "status", "issue_date", "due_date")
    ordering_fields = ("number", "issue_date", "due_date", "amount", "balance_due")

    def get_serializer_class(self):
        if self.action == "create":
            return InvoiceCreateSerializer
        return super().get_serializer_class()

    @extend_schema(
        request=InvoiceCreateSerializer,
        responses={status.HTTP_201_CREATED: InvoiceSerializer},
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = get_object_or_404(
            Student.objects.select_related("department"),
            pk=serializer.validated_data["student"],
        )
        fee_structure = get_object_or_404(
            FeeStructure.objects.select_related("unit"),
            pk=serializer.validated_data["fee_structure"],
        )
        if not can_manage_unit(request.user, fee_structure.unit):
            raise PermissionDenied("You may not issue invoices for this unit.")
        invoice = create_invoice(
            student=student,
            fee_structure=fee_structure,
            issue_date=serializer.validated_data["issue_date"],
            due_date=serializer.validated_data["due_date"],
            actor=request.user,
            idempotency_key=serializer.validated_data["idempotency_key"],
        )
        output = InvoiceSerializer(invoice, context=self.get_serializer_context())
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=("post",))
    def void(self, request, pk=None):
        invoice = self.get_object()
        if not may_approve_finance(request.user):
            raise PermissionDenied("You may not void finance invoices.")
        if not can_manage_unit(request.user, invoice.unit):
            raise PermissionDenied("You may not void invoices for this unit.")
        serializer = ReversalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = void_invoice(
            invoice_id=invoice.pk,
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        return Response(InvoiceSerializer(invoice).data)


class PaymentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    student_read_only = True
    queryset = (
        Payment.objects.select_related(
            "invoice__unit", "invoice__student", "cash_account", "journal_entry"
        )
        .select_related("receipt")
        .all()
    )
    serializer_class = PaymentSerializer
    permission_classes = (FinancePermission,)
    filterset_fields = ("invoice", "channel", "received_at")
    ordering_fields = ("received_at", "amount", "created_at")

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if may_read_all_finance(user):
            return queryset
        if user.has_role(Role.STUDENT):
            return queryset.filter(invoice__student__user=user)
        return queryset.filter(invoice__unit_id__in=user.unit_ids())

    @extend_schema(
        request=PaymentCreateSerializer,
        responses={status.HTTP_201_CREATED: PaymentSerializer},
    )
    def create(self, request, *args, **kwargs):
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        invoice = get_object_or_404(
            Invoice.objects.select_related("unit"), pk=data["invoice"]
        )
        if not can_manage_unit(request.user, invoice.unit):
            raise PermissionDenied("You may not record payments for this unit.")
        payment = record_payment(
            invoice_id=invoice.pk,
            cash_account_id=data["cash_account"],
            amount=data["amount"],
            channel=data["channel"],
            received_at=data["received_at"],
            actor=request.user,
            idempotency_key=data["idempotency_key"],
            mpesa_code=data.get("mpesa_code"),
            payer_phone=data.get("payer_phone", ""),
        )
        return Response(
            PaymentSerializer(payment, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=("post",))
    def reverse(self, request, pk=None):
        payment = self.get_object()
        if not may_approve_finance(request.user):
            raise PermissionDenied("You may not reverse finance payments.")
        if not can_manage_unit(request.user, payment.invoice.unit):
            raise PermissionDenied("You may not reverse payments for this unit.")
        serializer = ReversalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = reverse_payment(
            payment_id=payment.pk,
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        return Response(PaymentSerializer(payment).data)


class AdjustmentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Adjustment.objects.select_related(
        "invoice__unit", "invoice__student", "requested_by", "approved_by"
    ).all()
    serializer_class = AdjustmentSerializer
    permission_classes = (FinancePermission,)
    filterset_fields = ("invoice", "status")

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if may_read_all_finance(user):
            return queryset
        return queryset.filter(invoice__unit_id__in=user.unit_ids())

    def create(self, request, *args, **kwargs):
        serializer = AdjustmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        invoice = get_object_or_404(
            Invoice.objects.select_related("unit"), pk=data["invoice"]
        )
        if not can_manage_unit(request.user, invoice.unit):
            raise PermissionDenied("You may not request adjustments for this unit.")
        adjustment = request_adjustment(
            invoice_id=invoice.pk,
            amount=data["amount"],
            reason=data["reason"],
            actor=request.user,
        )
        return Response(
            AdjustmentSerializer(adjustment).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=("post",))
    def approve(self, request, pk=None):
        adjustment = self.get_object()
        if not may_approve_finance(request.user):
            raise PermissionDenied("You may not approve finance adjustments.")
        if not can_manage_unit(request.user, adjustment.invoice.unit):
            raise PermissionDenied("You may not approve adjustments for this unit.")
        adjustment = approve_adjustment(adjustment_id=adjustment.pk, actor=request.user)
        return Response(AdjustmentSerializer(adjustment).data)

    @action(detail=True, methods=("post",))
    def reverse(self, request, pk=None):
        adjustment = self.get_object()
        if not may_approve_finance(request.user):
            raise PermissionDenied("You may not reverse finance adjustments.")
        if not can_manage_unit(request.user, adjustment.invoice.unit):
            raise PermissionDenied("You may not reverse adjustments for this unit.")
        serializer = ReversalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        adjustment = reverse_adjustment(
            adjustment_id=adjustment.pk,
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        return Response(AdjustmentSerializer(adjustment).data)


class RefundViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Refund.objects.select_related(
        "payment__invoice__unit",
        "payment__invoice__student",
        "requested_by",
        "approved_by",
        "cash_account",
    ).all()
    serializer_class = RefundSerializer
    permission_classes = (FinancePermission,)
    filterset_fields = ("payment", "status")

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if may_read_all_finance(user):
            return queryset
        return queryset.filter(payment__invoice__unit_id__in=user.unit_ids())

    def create(self, request, *args, **kwargs):
        serializer = RefundCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payment = get_object_or_404(
            Payment.objects.select_related("invoice__unit"), pk=data["payment"]
        )
        if not can_manage_unit(request.user, payment.invoice.unit):
            raise PermissionDenied("You may not request refunds for this unit.")
        refund = request_refund(
            payment_id=payment.pk,
            cash_account_id=data["cash_account"],
            amount=data["amount"],
            reason=data["reason"],
            actor=request.user,
        )
        return Response(RefundSerializer(refund).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=("post",))
    def approve(self, request, pk=None):
        refund = self.get_object()
        if not may_approve_finance(request.user):
            raise PermissionDenied("You may not approve finance refunds.")
        if not can_manage_unit(request.user, refund.payment.invoice.unit):
            raise PermissionDenied("You may not approve refunds for this unit.")
        refund = approve_refund(refund_id=refund.pk, actor=request.user)
        return Response(RefundSerializer(refund).data)

    @action(detail=True, methods=("post",))
    def reverse(self, request, pk=None):
        refund = self.get_object()
        if not may_approve_finance(request.user):
            raise PermissionDenied("You may not reverse finance refunds.")
        if not can_manage_unit(request.user, refund.payment.invoice.unit):
            raise PermissionDenied("You may not reverse refunds for this unit.")
        serializer = ReversalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refund = reverse_refund(
            refund_id=refund.pk,
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        return Response(RefundSerializer(refund).data)


class JournalEntryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JournalEntry.objects.prefetch_related(
        Prefetch(
            "lines",
            queryset=JournalLine.objects.select_related(
                "account", "unit", "cash_account", "student"
            ),
        )
    ).all()
    serializer_class = JournalEntrySerializer
    permission_classes = (FinancePermission,)
    filterset_fields = ("date", "source_type", "status")
    ordering_fields = ("date", "created_at")

    def get_queryset(self):
        queryset = super().get_queryset().for_user(self.request.user)
        selected_unit = self.request.query_params.get("unit")
        if selected_unit is not None:
            queryset = queryset.filter(lines__unit_id=selected_unit).distinct()
        return queryset


class ReceiptPdfView(APIView):
    student_read_only = True
    permission_classes = (FinancePermission,)

    @extend_schema(responses={(200, "application/pdf"): bytes})
    def get(self, request, receipt_id):
        with transaction.atomic():
            receipt = get_object_or_404(
                Receipt.objects.select_for_update().select_related(
                    "generated_file",
                    "payment__journal_entry__created_by",
                    "payment__invoice__student__department__unit",
                    "payment__invoice__student__user",
                    "payment__invoice__unit",
                    "payment__cash_account",
                ),
                pk=receipt_id,
            )
            payment = receipt.payment
            student = payment.invoice.student
            is_student_owner = (
                request.user.has_role(Role.STUDENT)
                and student.user_id == request.user.pk
            )
            if not is_student_owner and not may_read_unit_finance(
                request.user, payment.invoice.unit_id
            ):
                raise PermissionDenied("You may not view this receipt.")

            storage = get_storage_client()
            generated_file = receipt.generated_file
            if (
                generated_file is not None
                and generated_file.status == StoredFile.Status.READY
            ):
                object_key = generated_file.object_key
                pdf_content = None
            else:
                pdf_content = self._render_pdf(receipt)
                object_key = f"generated/receipts/{receipt.pk.hex}/{uuid4().hex}.pdf"
                try:
                    storage.put_object(
                        Bucket=settings.R2_BUCKET,
                        Key=object_key,
                        Body=pdf_content,
                        ContentType="application/pdf",
                        ContentDisposition=(
                            f'attachment; filename="receipt-{receipt.pk.hex}.pdf"'
                        ),
                    )
                except (BotoCoreError, ClientError) as exc:
                    raise StorageNotConfigured(
                        "Could not store the generated receipt."
                    ) from exc

                try:
                    with transaction.atomic():
                        generated_file = StoredFile.objects.create(
                            purpose=StoredFile.Purpose.GENERATED,
                            owner_user=payment.journal_entry.created_by,
                            object_key=object_key,
                            original_name=f"receipt-{receipt.pk.hex}.pdf",
                            content_type="application/pdf",
                            size_bytes=len(pdf_content),
                            status=StoredFile.Status.READY,
                        )
                        receipt.generated_file = generated_file
                        receipt.save(update_fields=("generated_file", "updated_at"))
                except DatabaseError:
                    try:
                        storage.delete_object(Bucket=settings.R2_BUCKET, Key=object_key)
                    except (BotoCoreError, ClientError) as exc:
                        raise StorageNotConfigured(
                            "The receipt file was uploaded but could not be linked or cleaned up."
                        ) from exc
                    raise

        if pdf_content is None:
            try:
                stored_object = storage.get_object(
                    Bucket=settings.R2_BUCKET, Key=object_key
                )
                body = stored_object["Body"]
                try:
                    pdf_content = body.read()
                finally:
                    body.close()
            except (BotoCoreError, ClientError) as exc:
                raise StorageNotConfigured(
                    "Could not retrieve the stored receipt."
                ) from exc

        response = HttpResponse(pdf_content, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="receipt-{receipt.pk.hex}.pdf"'
        )
        response["Cache-Control"] = "private, no-store"
        return response

    @staticmethod
    def _render_pdf(receipt):
        payment = receipt.payment
        student = payment.invoice.student
        styles = getSampleStyleSheet()
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=48,
            leftMargin=48,
            topMargin=48,
            bottomMargin=48,
        )
        rows = [
            ["Receipt", escape(receipt.number)],
            ["Business unit", escape(payment.invoice.unit.name)],
            ["Student", escape(f"{student.first_name} {student.last_name}")],
            ["Registration number", escape(student.registration_number)],
            ["Invoice", escape(payment.invoice.number)],
            [
                "Amount received",
                f"{payment.invoice.unit.currency} {payment.amount:.2f}",
            ],
            ["Payment channel", escape(payment.get_channel_display())],
            ["Transaction code", escape(payment.mpesa_code or "—")],
            ["Received at", payment.received_at.strftime("%Y-%m-%d %H:%M %Z")],
            ["Issued at", receipt.issued_at.strftime("%Y-%m-%d %H:%M %Z")],
        ]
        table = Table(rows, colWidths=(150, 330))
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("PADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story = [
            Paragraph("Watan LMS — Payment Receipt", styles["Title"]),
            Spacer(1, 18),
            table,
        ]
        document.build(story)
        return buffer.getvalue()


class StudentStatementView(APIView):
    student_read_only = True
    permission_classes = (FinancePermission,)

    @extend_schema(responses=StudentStatementSerializer)
    def get(self, request, student_id):
        student = get_object_or_404(
            Student.objects.select_related("department__unit"), pk=student_id
        )
        is_student_owner = (
            request.user.has_role(Role.STUDENT) and student.user_id == request.user.pk
        )
        receivable_lines = JournalLine.objects.filter(
            student=student, account__fee_receivables__isnull=False
        )
        student_unit_ids = set(
            receivable_lines.values_list("unit_id", flat=True).distinct()
        )
        student_unit_ids.add(student.department.unit_id)
        if is_student_owner or may_read_all_finance(request.user):
            visible_unit_ids = student_unit_ids
        else:
            visible_unit_ids = student_unit_ids.intersection(request.user.unit_ids())
            if not visible_unit_ids:
                raise PermissionDenied("You may not view this student's statement.")
        lines = list(
            receivable_lines.filter(
                unit_id__in=visible_unit_ids,
                account__fee_receivables__unit_id__in=visible_unit_ids,
            )
            .distinct()
            .select_related("entry", "account")
            .order_by("entry__date", "entry__created_at", "created_at")
        )
        balance = 0
        statement = []
        for line in lines:
            balance += line.debit - line.credit
            statement.append(
                {
                    **StudentStatementLineSerializer(line).data,
                    "balance": f"{balance:.2f}",
                }
            )
        return Response(
            {
                "student": str(student.pk),
                "registration_number": student.registration_number,
                "balance": f"{balance:.2f}",
                "lines": statement,
            }
        )

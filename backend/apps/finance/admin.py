from django.contrib import admin

from .models import (
    Account,
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


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "type", "parent", "is_active")
    list_filter = ("type", "is_active")
    search_fields = ("code", "name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(AccountingPeriod)
class AccountingPeriodAdmin(admin.ModelAdmin):
    list_display = ("start", "end", "status")
    list_filter = ("status",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(CashAccount)
class CashAccountAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "account", "custody_unit", "custodian", "is_active")
    list_filter = ("kind", "custody_unit", "is_active")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "unit", "amount", "is_active")
    list_filter = ("unit", "is_active")
    search_fields = ("code", "name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "student", "unit", "amount", "balance_due", "status")
    list_filter = ("unit", "status")
    search_fields = ("number", "student__registration_number")
    readonly_fields = ("id", "created_at", "updated_at")


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0
    can_delete = False
    readonly_fields = (
        "account",
        "unit",
        "cash_account",
        "debit",
        "credit",
        "student",
    )


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("date", "memo", "source_type", "status", "created_by")
    list_filter = ("status", "source_type", "date")
    search_fields = ("memo", "idempotency_key")
    readonly_fields = (
        "id",
        "date",
        "memo",
        "source_type",
        "source_id",
        "status",
        "reverses",
        "reversal_reason",
        "idempotency_key",
        "created_by",
        "created_at",
        "updated_at",
    )
    inlines = (JournalLineInline,)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        obj.mpesa_code = Payment.normalize_mpesa_code(obj.mpesa_code)
        super().save_model(request, obj, form, change)


for model in (Adjustment, Receipt, Refund):
    admin.site.register(model)

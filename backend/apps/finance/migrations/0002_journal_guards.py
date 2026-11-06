from django.db import migrations


def install_journal_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    statements = (
        """
        CREATE FUNCTION finance_reject_journal_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% records are append-only', TG_TABLE_NAME
                USING ERRCODE = '23000';
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE TRIGGER finance_journal_entry_immutable
        BEFORE UPDATE OR DELETE ON finance_journalentry
        FOR EACH ROW EXECUTE FUNCTION finance_reject_journal_mutation();
        """,
        """
        CREATE TRIGGER finance_journal_line_immutable
        BEFORE UPDATE OR DELETE ON finance_journalline
        FOR EACH ROW EXECUTE FUNCTION finance_reject_journal_mutation();
        """,
        """
        CREATE FUNCTION finance_assert_journal_entry_balanced()
        RETURNS trigger AS $$
        DECLARE
            target_entry_id uuid;
            debit_total numeric;
            credit_total numeric;
        BEGIN
            IF TG_TABLE_NAME = 'finance_journalentry' THEN
                target_entry_id := NEW.id;
            ELSE
                target_entry_id := NEW.entry_id;
            END IF;

            SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
            INTO debit_total, credit_total
            FROM finance_journalline
            WHERE entry_id = target_entry_id;

            IF debit_total <= 0 OR debit_total <> credit_total THEN
                RAISE EXCEPTION 'Journal entry % must have equal, non-zero debits and credits',
                    target_entry_id
                    USING ERRCODE = '23000';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE CONSTRAINT TRIGGER finance_journal_entry_balanced
        AFTER INSERT ON finance_journalentry
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION finance_assert_journal_entry_balanced();
        """,
        """
        CREATE CONSTRAINT TRIGGER finance_journal_line_balanced
        AFTER INSERT ON finance_journalline
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION finance_assert_journal_entry_balanced();
        """,
    )
    for statement in statements:
        schema_editor.execute(statement)


def remove_journal_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    statements = (
        """
        DROP TRIGGER IF EXISTS finance_journal_entry_immutable ON finance_journalentry;
        """,
        """
        DROP TRIGGER IF EXISTS finance_journal_line_immutable ON finance_journalline;
        """,
        """
        DROP TRIGGER IF EXISTS finance_journal_entry_balanced ON finance_journalentry;
        """,
        """
        DROP TRIGGER IF EXISTS finance_journal_line_balanced ON finance_journalline;
        """,
        """
        DROP FUNCTION IF EXISTS finance_reject_journal_mutation();
        """,
        """
        DROP FUNCTION IF EXISTS finance_assert_journal_entry_balanced();
        """,
    )
    for statement in statements:
        schema_editor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]

    operations = [
        migrations.RunPython(install_journal_guards, remove_journal_guards),
    ]

from django.db import migrations


def install_unit_consistency_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    statements = (
        """
        CREATE FUNCTION org_check_department_unit_change()
        RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM org_program
                WHERE department_id = NEW.id
                    AND unit_id IS DISTINCT FROM NEW.unit_id
            ) OR EXISTS (
                SELECT 1
                FROM academics_course
                WHERE department_id = NEW.id
                    AND unit_id IS DISTINCT FROM NEW.unit_id
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'Department unit conflicts with existing programs or courses',
                    ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE TRIGGER org_department_unit_consistency
        BEFORE UPDATE OF unit_id ON org_department
        FOR EACH ROW EXECUTE FUNCTION org_check_department_unit_change();
        """,
        """
        CREATE FUNCTION org_check_program_unit()
        RETURNS trigger AS $$
        DECLARE
            expected_unit_id uuid;
        BEGIN
            SELECT unit_id INTO expected_unit_id
            FROM org_department
            WHERE id = NEW.department_id;

            IF NEW.unit_id IS DISTINCT FROM expected_unit_id THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'Program unit must match its department unit',
                    ERRCODE = '23514';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM academics_course
                WHERE program_id = NEW.id
                    AND (
                        department_id IS DISTINCT FROM NEW.department_id
                        OR unit_id IS DISTINCT FROM NEW.unit_id
                    )
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'Program change conflicts with existing courses',
                    ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE TRIGGER org_program_unit_consistency
        BEFORE INSERT OR UPDATE OF department_id, unit_id ON org_program
        FOR EACH ROW EXECUTE FUNCTION org_check_program_unit();
        """,
        """
        CREATE FUNCTION academics_check_course_unit()
        RETURNS trigger AS $$
        DECLARE
            expected_unit_id uuid;
        BEGIN
            SELECT unit_id INTO expected_unit_id
            FROM org_department
            WHERE id = NEW.department_id;

            IF NEW.unit_id IS DISTINCT FROM expected_unit_id THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'Course unit must match its department unit',
                    ERRCODE = '23514';
            END IF;

            IF NEW.program_id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                FROM org_program
                WHERE id = NEW.program_id
                    AND department_id = NEW.department_id
                    AND unit_id = NEW.unit_id
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'Course program must belong to its department and unit',
                    ERRCODE = '23514';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM enrollment_enrollment
                WHERE course_id = NEW.id
                    AND unit_id IS DISTINCT FROM NEW.unit_id
            ) OR EXISTS (
                SELECT 1
                FROM scheduling_timetableslot AS slot
                JOIN scheduling_classgroup AS class_group
                    ON class_group.id = slot.class_group_id
                WHERE class_group.course_id = NEW.id
                    AND slot.unit_id IS DISTINCT FROM NEW.unit_id
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'Course unit conflicts with existing enrollments or timetable slots',
                    ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE TRIGGER academics_course_unit_consistency
        BEFORE INSERT OR UPDATE OF department_id, program_id, unit_id
        ON academics_course
        FOR EACH ROW EXECUTE FUNCTION academics_check_course_unit();
        """,
        """
        CREATE FUNCTION enrollment_check_enrollment_unit()
        RETURNS trigger AS $$
        DECLARE
            expected_unit_id uuid;
        BEGIN
            SELECT unit_id INTO expected_unit_id
            FROM academics_course
            WHERE id = NEW.course_id;

            IF NEW.unit_id IS DISTINCT FROM expected_unit_id THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'Enrollment unit must match its course unit',
                    ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE TRIGGER enrollment_unit_consistency
        BEFORE INSERT OR UPDATE OF course_id, unit_id ON enrollment_enrollment
        FOR EACH ROW EXECUTE FUNCTION enrollment_check_enrollment_unit();
        """,
        """
        CREATE FUNCTION scheduling_check_class_group_course_unit()
        RETURNS trigger AS $$
        DECLARE
            expected_unit_id uuid;
        BEGIN
            SELECT unit_id INTO expected_unit_id
            FROM academics_course
            WHERE id = NEW.course_id;

            IF EXISTS (
                SELECT 1
                FROM scheduling_timetableslot
                WHERE class_group_id = NEW.id
                    AND unit_id IS DISTINCT FROM expected_unit_id
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'Class-group course change conflicts with timetable slots',
                    ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE TRIGGER scheduling_class_group_unit_consistency
        BEFORE UPDATE OF course_id ON scheduling_classgroup
        FOR EACH ROW EXECUTE FUNCTION scheduling_check_class_group_course_unit();
        """,
        """
        CREATE FUNCTION scheduling_check_timetable_slot_unit()
        RETURNS trigger AS $$
        DECLARE
            expected_unit_id uuid;
        BEGIN
            SELECT course.unit_id INTO expected_unit_id
            FROM scheduling_classgroup AS class_group
            JOIN academics_course AS course ON course.id = class_group.course_id
            WHERE class_group.id = NEW.class_group_id;

            IF NEW.unit_id IS DISTINCT FROM expected_unit_id THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'Timetable-slot unit must match its course unit',
                    ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        CREATE TRIGGER scheduling_timetable_slot_unit_consistency
        BEFORE INSERT OR UPDATE OF class_group_id, unit_id
        ON scheduling_timetableslot
        FOR EACH ROW EXECUTE FUNCTION scheduling_check_timetable_slot_unit();
        """,
    )
    for statement in statements:
        schema_editor.execute(statement)


def remove_unit_consistency_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    statements = (
        "DROP TRIGGER IF EXISTS scheduling_timetable_slot_unit_consistency ON scheduling_timetableslot;",
        "DROP TRIGGER IF EXISTS scheduling_class_group_unit_consistency ON scheduling_classgroup;",
        "DROP TRIGGER IF EXISTS enrollment_unit_consistency ON enrollment_enrollment;",
        "DROP TRIGGER IF EXISTS academics_course_unit_consistency ON academics_course;",
        "DROP TRIGGER IF EXISTS org_program_unit_consistency ON org_program;",
        "DROP TRIGGER IF EXISTS org_department_unit_consistency ON org_department;",
        "DROP FUNCTION IF EXISTS scheduling_check_timetable_slot_unit();",
        "DROP FUNCTION IF EXISTS scheduling_check_class_group_course_unit();",
        "DROP FUNCTION IF EXISTS enrollment_check_enrollment_unit();",
        "DROP FUNCTION IF EXISTS academics_check_course_unit();",
        "DROP FUNCTION IF EXISTS org_check_program_unit();",
        "DROP FUNCTION IF EXISTS org_check_department_unit_change();",
    )
    for statement in statements:
        schema_editor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ("enrollment", "0003_enrollment_unit"),
        ("org", "0006_a4_unit_ownership"),
        ("scheduling", "0002_timetable_slot_unit"),
    ]

    operations = [
        migrations.RunPython(
            install_unit_consistency_guards,
            remove_unit_consistency_guards,
        ),
    ]

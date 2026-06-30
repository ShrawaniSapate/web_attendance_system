from __future__ import annotations

from collections import defaultdict
from datetime import date, time, timedelta

from sqlalchemy import or_

from attendance_system.models import Attendance, Student, Timetable, TemporaryTimetableAdjustment
from attendance_system.services.external_attendance_service import get_external_attendance_for_roll, summarize_external_attendance_for_students


WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_TO_INDEX = {day.lower(): index for index, day in enumerate(WEEKDAY_ORDER)}
LOW_ATTENDANCE_THRESHOLD = 75
BREAK_SLOT = (time(hour=12, minute=40), time(hour=13, minute=0))


def count_day_occurrences(day_name: str, start_date: date, end_date: date) -> int:
    if start_date > end_date:
        return 0

    target_weekday = WEEKDAY_TO_INDEX.get(day_name.strip().lower())
    if target_weekday is None:
        return 0

    delta = (target_weekday - start_date.weekday()) % 7
    first_occurrence = start_date + timedelta(days=delta)
    if first_occurrence > end_date:
        return 0

    return ((end_date - first_occurrence).days // 7) + 1


def count_slot_lectures(slot: Timetable, start_date: date, end_date: date) -> int:
    slot_start = max(start_date, slot.created_at.date())
    return count_day_occurrences(slot.day, slot_start, end_date)


def group_timetable_entries(timetable_entries):
    grouped = defaultdict(list)
    for entry in timetable_entries:
        grouped[entry.day].append(entry)

    day_groups = []
    for day in WEEKDAY_ORDER:
        slots = sorted(grouped.get(day, []), key=lambda row: row.start_time)
        if slots:
            day_groups.append({"day": day, "slots": slots})

    return day_groups


def _build_matrix_columns(timetable_entries):
    boundaries = {BREAK_SLOT[0], BREAK_SLOT[1]}
    for entry in timetable_entries:
        boundaries.add(entry.start_time)
        boundaries.add(entry.end_time)

    ordered = sorted(boundaries)
    columns = []
    for start, end in zip(ordered, ordered[1:]):
        is_break = (start, end) == BREAK_SLOT
        has_overlap = any(entry.start_time <= start and entry.end_time >= end for entry in timetable_entries)
        if not has_overlap and not is_break:
            continue
        columns.append(
            {
                "start": start,
                "end": end,
                "label": f"{start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}",
                "key": f"{start.strftime('%H:%M')}_{end.strftime('%H:%M')}",
                "is_break": is_break,
            }
        )
    return columns


def build_timetable_matrix(timetable_entries):
    columns = _build_matrix_columns(timetable_entries)

    rows = []
    for day in WEEKDAY_ORDER:
        day_entries = [entry for entry in timetable_entries if entry.day == day]
        cells = []
        has_content = False

        for column in columns:
            items = [
                entry
                for entry in day_entries
                if entry.start_time <= column["start"] and entry.end_time >= column["end"]
            ]
            if items:
                has_content = True

            same_as_previous = (
                cells
                and items
                and cells[-1].get("entries")
                and not cells[-1].get("is_break")
                and len(items) == 1
                and len(cells[-1]["entries"]) == 1
                and cells[-1]["entries"][0].id == items[0].id
            )

            if same_as_previous:
                cells[-1]["colspan"] += 1
                continue

            cells.append(
                {
                    "entries": items,
                    "is_break": column["is_break"],
                    "label": column["label"],
                    "colspan": 1,
                }
            )

        if has_content:
            rows.append({"day": day, "cells": cells})

    return {"columns": columns, "rows": rows}


def slot_matches_student(student: Student, slot) -> bool:
    if getattr(slot, "institute_id", None) and slot.institute_id != student.institute_id:
        return False

    if getattr(slot, "course_id", None):
        if student.course_id != slot.course_id:
            return False
    elif getattr(slot, "course", None) and (student.course or "").strip().lower() != (slot.course or "").strip().lower():
        return False

    if getattr(slot, "classroom_id", None) and student.classroom_id != getattr(slot, "classroom_id", None):
        return False

    return True


def get_student_weekly_slots(student: Student):
    slots = (
        Timetable.query.filter_by(institute_id=student.institute_id)
        .order_by(Timetable.day, Timetable.start_time)
        .all()
    )
    return [slot for slot in slots if slot_matches_student(student, slot)]


def get_student_temporary_adjustments(student: Student, include_past: bool = True):
    query = TemporaryTimetableAdjustment.query.filter_by(institute_id=student.institute_id)
    if not include_past:
        query = query.filter(TemporaryTimetableAdjustment.adjustment_date >= date.today())
    slots = query.order_by(TemporaryTimetableAdjustment.adjustment_date, TemporaryTimetableAdjustment.start_time).all()
    return [slot for slot in slots if slot_matches_student(student, slot)]


def _slot_course_label(slot) -> str:
    if getattr(slot, "course_record", None):
        return slot.course_record.name
    return getattr(slot, "course", "-") or "-"


def _slot_classroom_label(slot) -> str:
    classroom = getattr(slot, "classroom", None)
    if not classroom:
        return "-"
    if classroom.display_division:
        return f"{classroom.name} ({classroom.display_division})"
    return classroom.name


def build_student_attendance_report(student, timetable_entries, temporary_entries=None, end_date: date | None = None):
    if end_date is None:
        end_date = date.today()
    if temporary_entries is None:
        temporary_entries = []

    relevant_weekly = [slot for slot in timetable_entries if slot_matches_student(student, slot)]
    relevant_temporary = [
        slot for slot in temporary_entries
        if slot_matches_student(student, slot) and student.created_at.date() <= slot.adjustment_date <= end_date
    ]

    subject_summary = defaultdict(lambda: {"present": 0, "total": 0})
    monthly_summary = defaultdict(lambda: {"present": 0, "total": 0})
    attendance_rows = sorted(student.attendance_records, key=lambda row: (row.date, row.time), reverse=True)

    for row in attendance_rows:
        month_key = row.date.strftime("%Y-%m")
        if row.status == "present":
            subject_summary[row.subject]["present"] += 1
            monthly_summary[month_key]["present"] += 1

    for slot in relevant_weekly:
        conducted = count_slot_lectures(slot, student.created_at.date(), end_date)
        if conducted <= 0:
            continue

        subject_summary[slot.subject]["total"] += conducted

        baseline = max(student.created_at.date(), slot.created_at.date())
        pointer = date(baseline.year, baseline.month, 1)
        end_pointer = date(end_date.year, end_date.month, 1)

        while pointer <= end_pointer:
            month_start = max(baseline, pointer)
            if pointer.month == 12:
                next_month = date(pointer.year + 1, 1, 1)
            else:
                next_month = date(pointer.year, pointer.month + 1, 1)

            month_end = min(end_date, next_month - timedelta(days=1))
            total_in_month = count_day_occurrences(slot.day, month_start, month_end)
            if total_in_month:
                monthly_summary[pointer.strftime("%Y-%m")]["total"] += total_in_month

            pointer = next_month

    for slot in relevant_temporary:
        subject_summary[slot.subject]["total"] += 1
        monthly_summary[slot.adjustment_date.strftime("%Y-%m")]["total"] += 1

    subject_rows = []
    total_present = 0
    total_lectures = 0

    for subject, values in sorted(subject_summary.items()):
        percentage = round((values["present"] / values["total"]) * 100, 2) if values["total"] else 0
        subject_rows.append(
            {
                "subject": subject,
                "present": values["present"],
                "total": values["total"],
                "percentage": percentage,
                "is_low": percentage < LOW_ATTENDANCE_THRESHOLD,
            }
        )
        total_present += values["present"]
        total_lectures += values["total"]

    overall_percentage = round((total_present / total_lectures) * 100, 2) if total_lectures else 0
    internal_monthly_rows = [
        {
            "month": datetime.strptime(month, "%Y-%m").strftime("%b %Y") if "-" in month else month,
            "present": values["present"],
            "total": values["total"],
            "percentage": round((values["present"] / values["total"]) * 100, 2) if values["total"] else 0,
        }
        for month, values in sorted(monthly_summary.items(), reverse=True)
    ]
    warning_rows = [row for row in subject_rows if row["is_low"]]

    external_monthly = get_external_attendance_for_roll(student.roll_number)
    monthly_rows = internal_monthly_rows
    monthly_source = "system"
    monthly_match_name = ""
    monthly_match_roll = ""
    monthly_imported_present = 0
    monthly_imported_total = 0
    monthly_imported_percentage = 0

    if external_monthly and external_monthly.get("monthly_rows"):
        monthly_rows = external_monthly["monthly_rows"]
        monthly_source = "excel"
        monthly_match_name = external_monthly.get("name", "")
        monthly_match_roll = student.roll_number
        monthly_imported_present = external_monthly.get("total_present", 0)
        monthly_imported_total = external_monthly.get("total_lectures", 0)
        monthly_imported_percentage = external_monthly.get("overall_percentage", 0)

    return {
        "records": attendance_rows,
        "subject_rows": subject_rows,
        "monthly_rows": monthly_rows,
        "monthly_source": monthly_source,
        "monthly_match_name": monthly_match_name,
        "monthly_match_roll": monthly_match_roll,
        "monthly_imported_present": monthly_imported_present,
        "monthly_imported_total": monthly_imported_total,
        "monthly_imported_percentage": monthly_imported_percentage,
        "chart_labels": [row["subject"] for row in subject_rows],
        "chart_values": [row["percentage"] for row in subject_rows],
        "overall_percentage": overall_percentage,
        "total_present": total_present,
        "total_lectures": total_lectures,
        "warning_rows": warning_rows,
        "is_low": overall_percentage < LOW_ATTENDANCE_THRESHOLD,
        "grouped_timetable": group_timetable_entries(relevant_weekly),
        "timetable_matrix": build_timetable_matrix(relevant_weekly),
        "weekly_slots": relevant_weekly,
        "temporary_slots": relevant_temporary,
    }

def build_admin_attendance_overview(students, timetable_entries, temporary_entries=None):
    if temporary_entries is None:
        temporary_entries = []

    student_rows = []
    subject_summary = defaultdict(lambda: {"present": 0, "total": 0})

    for student in students:
        report = build_student_attendance_report(student, timetable_entries, temporary_entries)

        student_rows.append(
            {
                "student": student,
                "present": report["total_present"],
                "total": report["total_lectures"],
                "percentage": report["overall_percentage"],
                "is_low": report["overall_percentage"] < LOW_ATTENDANCE_THRESHOLD,
            }
        )

        for row in report["subject_rows"]:
            subject_summary[row["subject"]]["present"] += row["present"]
            subject_summary[row["subject"]]["total"] += row["total"]

    subject_rows = []
    for subject, values in sorted(subject_summary.items()):
        percentage = round((values["present"] / values["total"]) * 100, 2) if values["total"] else 0
        subject_rows.append(
            {
                "subject": subject,
                "present": values["present"],
                "total": values["total"],
                "percentage": percentage,
                "is_low": percentage < LOW_ATTENDANCE_THRESHOLD,
            }
        )

    averages = [row["percentage"] for row in student_rows]
    avg_percentage = round(sum(averages) / len(averages), 2) if averages else 0
    low_attendance_rows = [row for row in student_rows if row["is_low"]]

    return {
        "student_rows": student_rows,
        "subject_rows": subject_rows,
        "avg_percentage": avg_percentage,
        "low_attendance_rows": low_attendance_rows,
    }


def build_teacher_subject_summary(teacher_id: int):
    rows = (
        Attendance.query.outerjoin(Timetable, Attendance.timetable_id == Timetable.id)
        .outerjoin(TemporaryTimetableAdjustment, Attendance.temporary_adjustment_id == TemporaryTimetableAdjustment.id)
        .filter(
            or_(
                Timetable.teacher_id == teacher_id,
                TemporaryTimetableAdjustment.teacher_id == teacher_id,
            )
        )
        .order_by(Attendance.date.desc(), Attendance.time.desc())
        .all()
    )

    summary = defaultdict(lambda: {"present_count": 0, "courses": set(), "classes": set()})
    for row in rows:
        bucket = summary[row.subject]
        bucket["present_count"] += 1
        slot = row.temporary_adjustment or row.timetable_entry
        if slot is not None:
            bucket["courses"].add(_slot_course_label(slot))
            bucket["classes"].add(_slot_classroom_label(slot))

    return rows, [
        {
            "subject": subject,
            "present_count": values["present_count"],
            "courses": ", ".join(sorted(item for item in values["courses"] if item and item != "-")),
            "classes": ", ".join(sorted(item for item in values["classes"] if item and item != "-")),
        }
        for subject, values in sorted(summary.items())
    ]


def build_teacher_monthly_assessment(teacher_id: int, months: int = 6):
    weekly_slots = Timetable.query.filter_by(teacher_id=teacher_id).all()
    temporary_slots = TemporaryTimetableAdjustment.query.filter_by(teacher_id=teacher_id).all()
    scope_slots = [*weekly_slots, *temporary_slots]

    if scope_slots:
        institute_id = scope_slots[0].institute_id
        students = Student.query.filter_by(institute_id=institute_id).all()
        scoped_students = [
            student for student in students
            if any(slot_matches_student(student, slot) for slot in scope_slots)
        ]
        external_summary = summarize_external_attendance_for_students(scoped_students, months=months)
        if external_summary["matched_count"]:
            return {
                "labels": external_summary["labels"],
                "values": external_summary["values"],
                "peak": external_summary["peak"],
                "total": external_summary["total_present"],
            }

    today = date.today()
    rows = (
        Attendance.query.outerjoin(Timetable, Attendance.timetable_id == Timetable.id)
        .outerjoin(TemporaryTimetableAdjustment, Attendance.temporary_adjustment_id == TemporaryTimetableAdjustment.id)
        .filter(
            or_(
                Timetable.teacher_id == teacher_id,
                TemporaryTimetableAdjustment.teacher_id == teacher_id,
            )
        )
        .all()
    )

    month_starts = []
    cursor = date(today.year, today.month, 1)
    for _ in range(months):
        month_starts.append(cursor)
        if cursor.month == 1:
            cursor = date(cursor.year - 1, 12, 1)
        else:
            cursor = date(cursor.year, cursor.month - 1, 1)
    month_starts.reverse()

    month_counts = {month.strftime("%Y-%m"): 0 for month in month_starts}
    for row in rows:
        key = row.date.strftime("%Y-%m")
        if key in month_counts:
            month_counts[key] += 1

    labels = [month.strftime("%b %Y") for month in month_starts]
    values = [month_counts[month.strftime("%Y-%m")] for month in month_starts]
    peak = max(values) if values else 0

    return {
        "labels": labels,
        "values": values,
        "peak": peak,
        "total": sum(values),
    }


def build_teacher_defaulter_rows(teacher):
    today = date.today()
    weekly_slots = Timetable.query.filter_by(teacher_id=teacher.id).all()
    temporary_slots = TemporaryTimetableAdjustment.query.filter_by(teacher_id=teacher.id).all()
    students = Student.query.filter_by(institute_id=teacher.institute_id).order_by(Student.name).all()

    attendance_rows = (
        Attendance.query.outerjoin(Timetable, Attendance.timetable_id == Timetable.id)
        .outerjoin(TemporaryTimetableAdjustment, Attendance.temporary_adjustment_id == TemporaryTimetableAdjustment.id)
        .filter(
            Attendance.student_id.in_([student.id for student in students]) if students else False,
            or_(
                Timetable.teacher_id == teacher.id,
                TemporaryTimetableAdjustment.teacher_id == teacher.id,
            ),
        )
        .all()
    )

    attendance_by_student = defaultdict(int)
    subject_by_student = defaultdict(set)
    for row in attendance_rows:
        attendance_by_student[row.student_id] += 1
        subject_by_student[row.student_id].add(row.subject)

    rows = []
    for student in students:
        relevant_weekly_slots = [slot for slot in weekly_slots if slot_matches_student(student, slot)]
        relevant_temporary_slots = [
            slot for slot in temporary_slots
            if slot_matches_student(student, slot) and student.created_at.date() <= slot.adjustment_date <= today
        ]
        total_lectures = sum(count_slot_lectures(slot, student.created_at.date(), today) for slot in relevant_weekly_slots)
        total_lectures += len(relevant_temporary_slots)
        if total_lectures <= 0:
            continue

        present = attendance_by_student.get(student.id, 0)
        percentage = round((present / total_lectures) * 100, 2) if total_lectures else 0
        rows.append(
            {
                "student": student,
                "subjects": ", ".join(sorted(subject_by_student.get(student.id, {slot.subject for slot in relevant_weekly_slots if slot.subject}))),
                "present": present,
                "total": total_lectures,
                "percentage": percentage,
                "is_defaulter": percentage < LOW_ATTENDANCE_THRESHOLD,
            }
        )

    return [row for row in rows if row["is_defaulter"]]


"""学员班级调整的作用域与语义（docs 决策：教师只能调整本人所带班级）。"""

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.crud import student as student_crud
from app.models.enrollment import Class, Student, StudentClass
from app.models.user import User

TEST_DB_NAME = "child_code_test_stuclasses"


def _engine():
    from app.core.config import get_settings

    base_url = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()
    engine = create_engine(base_url + f"/{TEST_DB_NAME}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def ctx():
    engine = _engine()
    Session = sessionmaker(bind=engine)
    with Session() as s:
        t1 = User(id=uuid.uuid4(), role="teacher", username=f"t1{uuid.uuid4().hex[:5]}", name="王", password_hash="x")
        t2 = User(id=uuid.uuid4(), role="teacher", username=f"t2{uuid.uuid4().hex[:5]}", name="李", password_hash="x")
        s.add_all([t1, t2])
        s.flush()
        c1 = Class(id=uuid.uuid4(), name="王班A", subject="Python", teacher_id=t1.id)
        c2 = Class(id=uuid.uuid4(), name="王班B", subject="Python", teacher_id=t1.id)
        cb = Class(id=uuid.uuid4(), name="李班", subject="Scratch", teacher_id=t2.id)
        cb2 = Class(id=uuid.uuid4(), name="李班2", subject="Scratch", teacher_id=t2.id)
        s.add_all([c1, c2, cb, cb2])
        s.flush()
        stu = Student(id=uuid.uuid4(), name="小明", lesson_balance=5, status="active")
        s.add(stu)
        s.flush()
        s.add_all([StudentClass(student_id=stu.id, class_id=c1.id), StudentClass(student_id=stu.id, class_id=cb.id)])
        s.commit()
        ids = {"t1": t1.id, "c1": c1.id, "c2": c2.id, "cb": cb.id, "cb2": cb2.id, "stu": stu.id}
    try:
        yield Session, ids
    finally:
        engine.dispose()


def _class_ids(student):
    return sorted(str(c.id) for c in student.classes)


def test_teacher_scoped_change_preserves_others(ctx):
    Session, ids = ctx
    with Session() as s:
        stu = student_crud.get(s, ids["stu"])
        # 王老师把小明从自己的 c1 调到 c2；李老师的 cb 必须保留
        student_crud.set_classes(s, stu, [ids["c2"]], restrict_teacher_id=ids["t1"])
        got = _class_ids(student_crud.get(s, ids["stu"]))
        assert got == sorted([str(ids["c2"]), str(ids["cb"])]), got


def test_teacher_cannot_assign_other_teachers_class(ctx):
    Session, ids = ctx
    with Session() as s:
        stu = student_crud.get(s, ids["stu"])
        # cb2 是李老师的班且小明不在其中：王老师不能新增
        with pytest.raises(ValueError):
            student_crud.set_classes(s, stu, [ids["cb2"], ids["c2"]], restrict_teacher_id=ids["t1"])


def test_teacher_unenroll_keeps_other_teachers_class(ctx):
    Session, ids = ctx
    with Session() as s:
        stu = student_crud.get(s, ids["stu"])
        # 退班：回传除本人 c1 外的全部归属（含李老师的 cb），cb 必须保留
        student_crud.set_classes(s, stu, [ids["cb"]], restrict_teacher_id=ids["t1"])
        got = _class_ids(student_crud.get(s, ids["stu"]))
        assert got == [str(ids["cb"])], got


def test_admin_replaces_all(ctx):
    Session, ids = ctx
    with Session() as s:
        stu = student_crud.get(s, ids["stu"])
        student_crud.set_classes(s, stu, [ids["c1"], ids["c2"]], restrict_teacher_id=None)
        got = _class_ids(student_crud.get(s, ids["stu"]))
        assert got == sorted([str(ids["c1"]), str(ids["c2"])]), got


def test_invalid_class_rejected(ctx):
    Session, ids = ctx
    with Session() as s:
        stu = student_crud.get(s, ids["stu"])
        with pytest.raises(ValueError):
            student_crud.set_classes(s, stu, [uuid.uuid4()], restrict_teacher_id=None)

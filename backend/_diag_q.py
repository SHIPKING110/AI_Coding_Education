from sqlalchemy import create_engine, text

e = create_engine("postgresql+psycopg://postgres:123456@localhost:5432/child_code")
with e.connect() as c:
    rows = c.execute(text(
        "select r.title, r.status, r.period_start, r.period_end, u.name as teacher, u.role "
        "from reports r join users u on u.id = r.teacher_id "
        "where r.type='QUARTERLY' order by u.name, r.period_start"
    )).mappings().all()
    print("TOTAL", len(rows))
    for r in rows:
        d = dict(r)
        print(d["teacher"], "|", d["title"], "|", d["status"], "|",
              d["period_start"], "->", d["period_end"])

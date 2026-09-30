from app.core.database import SessionLocal
from app.models.user import User
from app.services import agent_planner

db = SessionLocal()
u = db.query(User).filter(User.username == "teacher01").first()
for q in ["我有哪些学员", "这周考勤怎么样，顺便看看哪些学员课时不足、再给我教学数据"]:
    out = agent_planner.plan_and_run(db, u, q)
    print("Q:", q)
    print("  rounds:", out.rounds, "degraded:", out.degraded, "tools:", out.tools)
    print("  block_len:", len(out.block))
db.close()
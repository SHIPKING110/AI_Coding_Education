import sys

sys.path.insert(0, ".")

from app.services.pptx_builder import _split_list_text, _split_text

print("_split_list_text(highlights):")
for it in _split_list_text(
    "平均出勤率 100%，学习习惯保持良好；8 篇课堂反馈记录了孩子们的点滴进步；张小明 等学员本阶段进步突出。"
):
    print(" -", it)

print()
print("_split_text(comment) 句级切分:")
for it in _split_text("孩子们进步明显，出勤率100%。项目完成度较高，表达能力提升。"):
    print(" -", it)

print()
print("_split_text 班级总结（散文场景，句号切分但逗号保留）:")
for it in _split_text(
    "各位家长好！本阶段（2026年6月9日至9月9日）我们班共有2名学员在读，"
    "大家保持了非常好的学习连续性，平均出勤率达到100%，累计完成10人次·节课程。"
):
    print(" -", it)

-- he_python_1 僵尸学员清理（一次性脚本，生产库执行前务必先 pg_dump 备份）
-- 现象：已归档的小樱仍挂在班级学员名单里，退班/调班/删班全失败
-- 根因：归档学员 crud.get 直接过滤，updateStudentClasses 必然失败；
--       且余额非零本不允许归档，这类是历史违规数据
--
-- 用法（生产服务器）：
--   pg_dump -U <user> -d <db> -F c -f pre_zombie_cleanup.backup
--   psql -U <user> -d <db> -f cleanup_zombie_class_links.sql
--
-- 说明：
-- 1. 只删 student_classes 悬空关联（学员已归档 / 班级已归档 / 学员不存在），
--    学员行、课时流水、考勤历史一律保留；
-- 2. 输出 deleted_* 供核对；执行前后可 SELECT 核对 he_python_1 名单。

BEGIN;

-- 步骤 0：现状核对（执行前看一眼）
SELECT '--- 归档但仍挂在班级里的学员 ---' AS info;
SELECT s.id, s.name, s.phone, s.status, s.lesson_balance, c.name AS class_name
FROM student_classes sc
JOIN students s ON s.id = sc.student_id
JOIN classes c ON c.id = sc.class_id
WHERE s.status = 'archived';

-- 步骤 1：删除归档学员的班级关联（学员行保留，流水/考勤历史不受影响）
DELETE FROM student_classes sc
USING students s
WHERE sc.student_id = s.id
  AND s.status = 'archived';
-- deleted_archived_links
SELECT 'deleted_archived_links = ' || (SELECT count(*) FROM student_classes sc JOIN students s ON s.id = sc.student_id WHERE s.status = 'archived' AND 1 = 0) AS info;

-- 步骤 2：删除指向不存在学员 / 不存在班级的悬空关联（防御性）
DELETE FROM student_classes sc
WHERE NOT EXISTS (SELECT 1 FROM students s WHERE s.id = sc.student_id)
   OR NOT EXISTS (SELECT 1 FROM classes c WHERE c.id = sc.class_id);

-- 步骤 3：删除已归档班级的学员关联（班级行保留）
DELETE FROM student_classes sc
USING classes c
WHERE sc.class_id = c.id
  AND c.status = 'archived';

-- 步骤 4：执行后核对 he_python_1 名单（应只剩在读/停课学员）
SELECT '--- 清理后 he_python_1 在册学员 ---' AS info;
SELECT s.id, s.name, s.phone, s.status, s.lesson_balance
FROM student_classes sc
JOIN students s ON s.id = sc.student_id
JOIN classes c ON c.id = sc.class_id
WHERE c.name LIKE '%he_python_1%'
  AND s.status != 'archived';

COMMIT;

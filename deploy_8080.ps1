# AI 习题 v3 部署脚本：从运行中容器恢复 env → 备份库 → 校正 alembic 版本 → 重建镜像 → 冒烟
$ErrorActionPreference = 'Stop'
$root = 'e:\VS_code_project\person_project\Child_Code'
Set-Location $root
$utf8 = New-Object System.Text.UTF8Encoding($false)

Write-Host '=== 1. 恢复 .env / .env.prod（来自真实容器环境） ==='
$backendEnv = docker inspect child_code-backend-1 --format '{{range .Config.Env}}{{println .}}{{end}}'
$exclude = '^(PATH|PYTHON_VERSION|HOSTNAME|LANG|GPG_KEY|PYTHON_SHA256|DATABASE_URL|UPLOAD_DIR)='
$keep = @($backendEnv | Where-Object { $_ -and $_ -notmatch $exclude })
[IO.File]::WriteAllLines("$root\.env.prod", $keep, $utf8)
$dbEnv = docker inspect child_code-db-1 --format '{{range .Config.Env}}{{println .}}{{end}}'
$keepDb = @($dbEnv | Where-Object { $_ -match '^POSTGRES_(USER|PASSWORD|DB)=' })
$keepDb += 'WEB_PORT=8080'
[IO.File]::WriteAllLines("$root\.env", $keepDb, $utf8)
Write-Host "  .env 行数: $($keepDb.Count) / .env.prod 行数: $($keep.Count)"

Write-Host '=== 2. 备份数据库 ==='
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backup = Join-Path $env:TEMP "opencode\child_code_backup_$stamp.dump"
docker exec child_code-db-1 pg_dump -U app -Fc -f /tmp/child_code_backup.dump child_code
docker cp child_code-db-1:/tmp/child_code_backup.dump $backup
Write-Host "  备份: $backup ($([math]::Round((Get-Item $backup).Length/1MB,2)) MB)"

Write-Host '=== 3. 检查生产库 alembic 版本与关键对象 ==='
docker exec child_code-db-1 psql -U app -d child_code -tAc "select version_num from alembic_version"
docker exec child_code-db-1 psql -U app -d child_code -tAc "select column_name from information_schema.columns where table_name='question_bank_attempts' and column_name in ('user_id','kind','paper_title','paper_meta','question_results') order by 1"
docker exec child_code-db-1 psql -U app -d child_code -tAc "select table_name from information_schema.tables where table_name in ('question_bank_user_marks','question_bank_ai_reviews','question_bank_knowledge_points') order by 1"

Write-Host '=== 4. 校正 alembic_version 至 c00000000004（schema 已齐） ==='
docker exec child_code-db-1 psql -U app -d child_code -c "update alembic_version set version_num='c00000000004';"
docker exec child_code-db-1 psql -U app -d child_code -tAc "select version_num from alembic_version"

Write-Host '=== 5. 重建镜像并重启 ==='
docker compose up -d --build
docker compose ps

Write-Host '=== 6. 冒烟 ==='
$index = (Invoke-WebRequest -Uri 'http://localhost:8080/' -UseBasicParsing).Content
$localIndex = Get-Content "$root\frontend\dist\index.html" -Raw
$hashRemote = [regex]::Match($index, 'assets/index-[A-Za-z0-9_-]+\.js').Value
$hashLocal = [regex]::Match($localIndex, 'assets/index-[A-Za-z0-9_-]+\.js').Value
Write-Host "  远端 index: $hashRemote"
Write-Host "  本地 dist: $hashLocal"
$openapi = (Invoke-WebRequest -Uri 'http://localhost:8080/api/openapi.json' -UseBasicParsing).Content
Write-Host "  openapi 含 compose/availability: $($openapi.Contains('/question-bank/compose/availability'))"
Write-Host "  openapi 含 validation: $($openapi.Contains('/question-bank/sets/{set_id}/validation'))"
docker exec child_code-db-1 psql -U app -d child_code -tAc "select version_num from alembic_version"
Write-Host '=== 完成 ==='

# One-time security cleanup: purge database dumps from Git history.
#
# Context: backups/pre_zombie_cleanup_20261007.{sql,backup} were committed and
# contain student PII (names/phones/password hashes). This script rewrites
# history with git-filter-repo. Before executing:
#   1. Freeze collaborator activity (others must re-clone afterwards)
#   2. Back up the whole repo and confirm force-push is allowed
#   3. Rotate any credentials that may appear in the dumps
#
# Usage (from repo root):
#   powershell -File backend/scripts/purge_backups_from_history.ps1 -DryRun
#   powershell -File backend/scripts/purge_backups_from_history.ps1 -Execute
param(
    [switch]$DryRun = $false,
    [switch]$Execute = $false
)

$ErrorActionPreference = 'Stop'

if (-not $DryRun -and -not $Execute) {
    Write-Host 'Default = DryRun. Use -DryRun to rehearse or -Execute to rewrite history.'
    $DryRun = $true
}

$repoRoot = (git rev-parse --show-toplevel)
Set-Location $repoRoot

Write-Host '== 1. Sensitive paths still present in history =='
git log --oneline --all -- backups/ | Select-Object -First 10
Write-Host ''

Write-Host '== 2. Check git-filter-repo availability =='
$hasFilterRepo = $false
try { git filter-repo --version | Out-Null; $hasFilterRepo = $true } catch {}
if (-not $hasFilterRepo) {
    Write-Host 'git-filter-repo not found. Install it first:'
    Write-Host '  pip install git-filter-repo'
    Write-Host 'Fallback: remove backups/ with BFG Repo-Cleaner, then reflog expire + gc.'
    if (-not $Execute) { exit 0 }
    exit 1
}
Write-Host 'git-filter-repo is available.'
Write-Host ''

if ($DryRun) {
    Write-Host '=== DryRun finished: repository unchanged ==='
    Write-Host 'To actually rewrite all history (force-push required afterwards):'
    Write-Host '  backend/scripts/purge_backups_from_history.ps1 -Execute'
    exit 0
}

Write-Host '== 3. Rewriting history: removing backups/ =='
git filter-repo --force --invert-paths --path backups/
Write-Host ''

Write-Host '== 4. Verify =='
$remaining = git log --oneline --all -- backups/
if ($remaining) { Write-Host "Residual commits found:`n$remaining"; exit 1 }
Write-Host 'History cleanup done.'
Write-Host ''
Write-Host '== 5. Mandatory manual follow-up =='
Write-Host '  1) Re-add remote: git remote add origin <url>  (filter-repo drops origin)'
Write-Host '  2) Force push: git push --force --all; git push --force --tags'
Write-Host '  3) Ask collaborators to re-clone; old clones cannot pull anymore'
Write-Host '  4) Rotate credentials found in dumps and delete plaintext dumps on servers'

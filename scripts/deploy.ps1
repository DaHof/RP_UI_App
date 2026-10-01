# Push this branch to GitHub, then tell the Pi to pull it and restart the
# dashboard -- a one-command "push a software update" for PIP-UI.
#
#   ./scripts/deploy.ps1
#   ./scripts/deploy.ps1 -HostName 192.168.1.50 -User pi
#
# Defaults come from $env:PIPUI_HOST / $env:PIPUI_USER if set, else
# pipui.local / pi. Set them once per machine instead of passing flags every
# time:
#   [Environment]::SetEnvironmentVariable("PIPUI_HOST", "pipui.local", "User")
#
# Requires: git push access to origin, and SSH key auth to the Pi already set
# up (ssh-copy-id, or paste your Windows public key into the Pi's
# ~/.ssh/authorized_keys) -- otherwise this stops to ask for a password twice.
#
# All the actual update logic -- the fast-forward-only pull, the conditional
# dependency reinstall, the service restart -- lives in
# scripts/pipui-update.sh on the Pi. This script only pushes and triggers it.

param(
    [string]$HostName = $(if ($env:PIPUI_HOST) { $env:PIPUI_HOST } else { "pipui.local" }),
    [string]$User     = $(if ($env:PIPUI_USER) { $env:PIPUI_USER } else { "pi" }),
    [string]$RepoPath = "~/RP_UI_App",
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if (-not $?) { Write-Error "Not a git repo?"; exit 1 }

Write-Host "Pushing '$branch' to origin..." -ForegroundColor Cyan
git push origin $branch
if ($LASTEXITCODE -ne 0) { Write-Error "git push failed -- fix that before deploying."; exit 1 }

$updateArgs = if ($NoRestart) { "--no-restart" } else { "" }
Write-Host "Deploying to ${User}@${HostName}:${RepoPath}..." -ForegroundColor Cyan
ssh "${User}@${HostName}" "cd $RepoPath && git checkout $branch && ./scripts/pipui-update.sh $updateArgs"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Deploy failed. Check output above, or SSH in directly: ssh ${User}@${HostName}"
    exit 1
}
Write-Host "Done." -ForegroundColor Green

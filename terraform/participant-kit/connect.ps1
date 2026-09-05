# Run this from the same folder as your participant-XX.yaml kubeconfig file.
# Windows PowerShell.

$ErrorActionPreference = "Stop"
$dir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$kcfg = Get-ChildItem -Path $dir -Filter "participant-*.yaml" | Select-Object -First 1

if (-not $kcfg) {
    Write-Host "Could not find a participant-XX.yaml kubeconfig file next to this script." -ForegroundColor Red
    Write-Host "Make sure connect.ps1 and your participant-XX.yaml are in the same folder."
    exit 1
}

if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    Write-Host "kubectl is not installed. Install it, then re-run this script:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  winget install -e --id Kubernetes.kubectl"
    Write-Host "  (or)  choco install kubernetes-cli"
    Write-Host "  Docs: https://kubernetes.io/docs/tasks/tools/"
    exit 1
}

$env:KUBECONFIG = $kcfg.FullName
$ns = kubectl config view --minify -o jsonpath='{.contexts[0].context.namespace}'

Write-Host "Using kubeconfig: $($kcfg.FullName)"
Write-Host "Your namespace:   $ns"
Write-Host ""
Write-Host "Testing access to the cluster..."

kubectl get pods 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Connected. You have full access inside '$ns' only." -ForegroundColor Green
} else {
    Write-Host "Could not reach the cluster. Check your internet connection and try again." -ForegroundColor Red
    Write-Host "If this keeps failing, contact the trainer."
    exit 1
}

Write-Host ""
Write-Host "-------------------------------------------------------------"
Write-Host "You're connected as: $ns"
Write-Host ""
Write-Host "Try:"
Write-Host "  kubectl get all -n $ns"
Write-Host "  kubectl get pods -n participant-01     # <- someone else's namespace, will be denied"
Write-Host ""
Write-Host "To make this permanent for your current PowerShell session, run:"
Write-Host "  `$env:KUBECONFIG = `"$($kcfg.FullName)`""
Write-Host "-------------------------------------------------------------"

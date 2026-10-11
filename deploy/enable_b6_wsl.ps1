# Administrator-only, authorized B6 setup. No automatic restart or distro deletion.
[CmdletBinding()]
param([string]$SetupRoot = 'D:\B2-B6-20261011\setup')
$ErrorActionPreference = 'Stop'
$b6ExpectedRoot = [IO.Path]::GetFullPath('D:\B2-B6-20261011\setup')
if ([IO.Path]::GetFullPath($SetupRoot) -ne $b6ExpectedRoot) { throw 'Unexpected setup root' }
$b6Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$b6Principal = [Security.Principal.WindowsPrincipal]::new($b6Identity)
if (-not $b6Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator approval is required; no setup action performed'
}
$b6LogRoot = Join-Path $SetupRoot 'logs'
New-Item -ItemType Directory -Force -Path $b6LogRoot | Out-Null
$b6StatusPath = Join-Path $b6LogRoot 'windows-setup-status.json'
$b6Status = [ordered]@{ started_at_utc = [DateTime]::UtcNow.ToString('o'); administrator = $true; succeeded = $false; restart_requested = $false; steps = @() }
try {
    $b6DownloadReport = Get-Content -LiteralPath (Join-Path $SetupRoot 'downloads-verified.json') -Raw | ConvertFrom-Json
    $b6Msi = @($b6DownloadReport.files | Where-Object kind -eq 'WSL')
    if ($b6Msi.Count -ne 1) { throw 'Exactly one verified WSL MSI is required' }
    $b6MsiPath = [IO.Path]::GetFullPath($b6Msi[0].path)
    if (-not $b6MsiPath.StartsWith((Join-Path $b6ExpectedRoot 'downloads') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Installer path escapes the D setup directory' }
    if ((Get-FileHash -LiteralPath $b6MsiPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $b6Msi[0].sha256) { throw 'Installer digest differs from verified official download' }
    $b6Signature = Get-AuthenticodeSignature -LiteralPath $b6MsiPath
    if ($b6Signature.Status -ne 'Valid' -or $b6Signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'Valid Microsoft installer signature is required' }
    $b6MsiLog = Join-Path $b6LogRoot 'wsl-msi.log'
    $b6InstallArgs = @('/i', ('"' + $b6MsiPath + '"'), '/qn', '/norestart', '/L*v', ('"' + $b6MsiLog + '"'))
    $b6Installer = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" -ArgumentList $b6InstallArgs -WindowStyle Hidden -Wait -PassThru
    $b6Status.steps += [ordered]@{ name = 'official_wsl_msi'; exit_code = $b6Installer.ExitCode; log = $b6MsiLog }
    if ($b6Installer.ExitCode -notin @(0, 3010)) { throw ('WSL MSI failed: ' + $b6Installer.ExitCode) }
    $b6DismOut = Join-Path $b6LogRoot 'virtual-machine-platform.stdout.txt'
    $b6DismErr = Join-Path $b6LogRoot 'virtual-machine-platform.stderr.txt'
    $b6Dism = Start-Process -FilePath "$env:SystemRoot\System32\dism.exe" -ArgumentList @('/online','/enable-feature','/featurename:VirtualMachinePlatform','/all','/norestart') -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $b6DismOut -RedirectStandardError $b6DismErr
    $b6Status.steps += [ordered]@{ name = 'enable_virtual_machine_platform'; exit_code = $b6Dism.ExitCode; stdout_log = $b6DismOut; stderr_log = $b6DismErr }
    if ($b6Dism.ExitCode -notin @(0, 3010)) { throw ('Windows feature enable failed: ' + $b6Dism.ExitCode) }
    $b6Status.restart_required = ($b6Installer.ExitCode -eq 3010 -or $b6Dism.ExitCode -eq 3010)
    $b6Status.succeeded = $true
} catch {
    $b6Status.failure = $_.Exception.Message
} finally {
    $b6Status.finished_at_utc = [DateTime]::UtcNow.ToString('o')
    $b6Status | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $b6StatusPath -Encoding UTF8
}
if (-not $b6Status.succeeded) { exit 1 }
if ($b6Status.restart_required) { exit 3010 }
exit 0

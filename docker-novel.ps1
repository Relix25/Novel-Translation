param(
    [ValidateSet('Up','Restart','Stop','Status','Logs','Login')]
    [string]$Action = 'Up',
    [string]$SourcesPath = '',
    [string]$BackupPath = '',
    [switch]$EmptyLibrary
)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    & docker version --format '{{.Server.Version}}'
    if ($LASTEXITCODE -ne 0) { throw 'Docker daemon access denied. Run this launcher from a Windows session with Docker Desktop access.' }
    $settingsFile = Join-Path $PSScriptRoot 'docker-data\settings.json'
    if (-not $SourcesPath -and (Test-Path -LiteralPath $settingsFile)) {
        # Windows PowerShell 5.1 otherwise treats BOM-less UTF-8 as ANSI.
        $SourcesPath = (Get-Content -LiteralPath $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json).sources
    }
    if ($SourcesPath) {
        $resolvedSources = (Resolve-Path -LiteralPath $SourcesPath).Path
        if (-not (Test-Path -LiteralPath $resolvedSources -PathType Container)) { throw 'The source folder was not found.' }
        $env:NOVEL_SOURCES_DIR = $resolvedSources.Replace('\','/')
        if ($Action -eq 'Up') {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $settingsFile) | Out-Null
            @{sources=$resolvedSources} | ConvertTo-Json | Set-Content -LiteralPath $settingsFile -Encoding utf8
        }
    }
    function Invoke-NovelCompose {
        param([string[]]$Arguments)
        & docker compose --file (Join-Path $PSScriptRoot 'compose.yaml') @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Docker command failed: $($Arguments -join ' ')" }
    }
    function Get-NovelState {
        try { $state = Invoke-RestMethod 'http://127.0.0.1:8791/api/state' -TimeoutSec 3 }
        catch {
            $runningId = Invoke-NovelCompose -Arguments @('ps','--status','running','--quiet','novel')
            if ($runningId) { throw 'Novel is running but its state is unavailable. Update or stop refused; retry when the server responds.' }
            return $null
        }
        if (-not $state.PSObject.Properties['jobs'] -or -not $state.PSObject.Properties['runs']) {
            throw 'Novel state is incomplete; update or stop refused.'
        }
        return $state
    }
    if ($Action -eq 'Up') {
        $running = Get-NovelState
        if ($running -and (@($running.jobs | Where-Object {$_.state -in @('queued','running')}).Count -gt 0 -or @($running.runs | Where-Object {$_.state -in @('queued','running','pause_requested')}).Count -gt 0)) {
            throw 'A Docker job is active. Pause the run before updating.'
        }
        $libraryFolder = Join-Path $PSScriptRoot 'docker-data\library'
        if ($EmptyLibrary -and $BackupPath) { throw 'Choose -EmptyLibrary or -BackupPath, not both.' }
        if ($EmptyLibrary -and -not (Test-Path -LiteralPath $libraryFolder)) {
            New-Item -ItemType Directory -Path $libraryFolder -Force | Out-Null
        }
        if (-not (Test-Path -LiteralPath $libraryFolder)) {
            if (-not $BackupPath) {
                $legacyOrigin = 'http://127.0.0.1:8790'
                try {
                    $legacy = Invoke-RestMethod "$legacyOrigin/api/state" -TimeoutSec 10
                    $headers = @{Origin=$legacyOrigin; 'X-Novel-CSRF'=$legacy.csrf}
                    $body = @{action='backup';series_id=$legacy.series[0].id} | ConvertTo-Json
                    $backup = Invoke-RestMethod "$legacyOrigin/api/action" -Method Post -ContentType 'application/json' -Headers $headers -Body $body -TimeoutSec 60
                    $BackupPath = $backup.database_backup
                } catch {
                    throw 'Automatic backup failed. Pause jobs or provide -BackupPath with an existing complete backup. No data was replaced.'
                }
            }
            $novelPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
            if (-not (Test-Path -LiteralPath $novelPython)) { $novelPython = 'python' }
            & $novelPython (Join-Path $PSScriptRoot 'docker_bootstrap.py') $BackupPath $libraryFolder
            if ($LASTEXITCODE -ne 0) { throw 'Backup import refused; startup cancelled.' }
        }
        Invoke-NovelCompose -Arguments @('build','novel')
        # A build can take several minutes. Recheck immediately before replacing
        # the running container so work started during the build is preserved.
        $running = Get-NovelState
        if ($running -and (@($running.jobs | Where-Object {$_.state -in @('queued','running')}).Count -gt 0 -or @($running.runs | Where-Object {$_.state -in @('queued','running','pause_requested')}).Count -gt 0)) {
            throw 'Image built, but a job started meanwhile. Pause the run, then run Up again.'
        }
        Invoke-NovelCompose -Arguments @('up','--detach','--no-build','--wait')
        Write-Output 'Novel Docker : http://127.0.0.1:8791'
        Write-Output 'First sign-in only: .\docker-novel.ps1 Login'
        Write-Output 'Mounted sources are available in Novel at /imports.'
    } elseif ($Action -in @('Restart','Stop')) {
        $state = Get-NovelState
        if (@($state.jobs | Where-Object {$_.state -in @('queued','running')}).Count -gt 0 -or @($state.runs | Where-Object {$_.state -in @('queued','running','pause_requested')}).Count -gt 0) {
            throw "A job is active. Pause it in Novel and wait for the current call to finish before restarting or stopping."
        }
        if ($Action -eq 'Restart') { Invoke-NovelCompose -Arguments @('restart','novel') }
        else { Invoke-NovelCompose -Arguments @('stop','novel') }
    } elseif ($Action -eq 'Login') {
        Invoke-NovelCompose -Arguments @('exec','novel','codex','login','--device-auth')
    } elseif ($Action -eq 'Logs') {
        Invoke-NovelCompose -Arguments @('logs','--tail','100','novel')
    } else { Invoke-NovelCompose -Arguments @('ps') }
} finally { Pop-Location }

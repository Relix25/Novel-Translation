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
    if ($LASTEXITCODE -ne 0) { throw 'Accès au moteur Docker refusé. Exécuter ce lanceur depuis votre session Windows autorisée à utiliser Docker Desktop.' }
    $settingsFile = Join-Path $PSScriptRoot 'docker-data\settings.json'
    if (-not $SourcesPath -and (Test-Path -LiteralPath $settingsFile)) {
        # Windows PowerShell 5.1 otherwise treats BOM-less UTF-8 as ANSI.
        $SourcesPath = (Get-Content -LiteralPath $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json).sources
    }
    if ($SourcesPath) {
        $resolvedSources = (Resolve-Path -LiteralPath $SourcesPath).Path
        if (-not (Test-Path -LiteralPath $resolvedSources -PathType Container)) { throw 'Le dossier source est introuvable.' }
        $env:NOVEL_SOURCES_DIR = $resolvedSources.Replace('\','/')
        if ($Action -eq 'Up') {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $settingsFile) | Out-Null
            @{sources=$resolvedSources} | ConvertTo-Json | Set-Content -LiteralPath $settingsFile -Encoding utf8
        }
    }
    function Invoke-NovelCompose {
        param([string[]]$Arguments)
        & docker compose --file (Join-Path $PSScriptRoot 'compose.yaml') @Arguments
        if ($LASTEXITCODE -ne 0) { throw "La commande Docker a échoué : $($Arguments -join ' ')" }
    }
    function Get-NovelState {
        try { $state = Invoke-RestMethod 'http://127.0.0.1:8791/api/state' -TimeoutSec 3 }
        catch {
            $runningId = Invoke-NovelCompose -Arguments @('ps','--status','running','--quiet','novel')
            if ($runningId) { throw 'Novel fonctionne mais son état est inaccessible. Mise à jour ou arrêt refusé ; réessayer lorsque le serveur répond.' }
            return $null
        }
        if (-not $state.PSObject.Properties['jobs'] -or -not $state.PSObject.Properties['runs']) {
            throw 'État Novel incomplet ; mise à jour ou arrêt refusé.'
        }
        return $state
    }
    if ($Action -eq 'Up') {
        $running = Get-NovelState
        if ($running -and (@($running.jobs | Where-Object {$_.state -in @('queued','running')}).Count -gt 0 -or @($running.runs | Where-Object {$_.state -in @('queued','running','pause_requested')}).Count -gt 0)) {
            throw 'Un travail est actif dans Docker. Mettre le lot en pause avant la mise à jour.'
        }
        $libraryFolder = Join-Path $PSScriptRoot 'docker-data\library'
        if ($EmptyLibrary -and $BackupPath) { throw 'Choisir -EmptyLibrary ou -BackupPath, pas les deux.' }
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
                    throw 'Sauvegarde automatique impossible. Mettre les travaux en pause ou fournir -BackupPath avec une sauvegarde complète existante. Aucune donnée remplacée.'
                }
            }
            $novelPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
            if (-not (Test-Path -LiteralPath $novelPython)) { $novelPython = 'python' }
            & $novelPython (Join-Path $PSScriptRoot 'docker_bootstrap.py') $BackupPath $libraryFolder
            if ($LASTEXITCODE -ne 0) { throw 'Import de sauvegarde refusé ; lancement interrompu.' }
        }
        Invoke-NovelCompose -Arguments @('build','novel')
        # A build can take several minutes. Recheck immediately before replacing
        # the running container so work started during the build is preserved.
        $running = Get-NovelState
        if ($running -and (@($running.jobs | Where-Object {$_.state -in @('queued','running')}).Count -gt 0 -or @($running.runs | Where-Object {$_.state -in @('queued','running','pause_requested')}).Count -gt 0)) {
            throw 'Image construite, mais un travail a démarré entre-temps. Mettre le lot en pause puis relancer Up.'
        }
        Invoke-NovelCompose -Arguments @('up','--detach','--no-build','--wait')
        Write-Output 'Novel Docker : http://127.0.0.1:8791'
        Write-Output 'Première connexion uniquement : .\docker-novel.ps1 Login'
        Write-Output 'Les sources montées sont accessibles dans Novel sous /imports.'
    } elseif ($Action -in @('Restart','Stop')) {
        $state = Get-NovelState
        if (@($state.jobs | Where-Object {$_.state -in @('queued','running')}).Count -gt 0 -or @($state.runs | Where-Object {$_.state -in @('queued','running','pause_requested')}).Count -gt 0) {
            throw "Un travail est actif. Demander sa pause dans Novel et attendre la fin de l'appel avant de redémarrer ou arrêter."
        }
        if ($Action -eq 'Restart') { Invoke-NovelCompose -Arguments @('restart','novel') }
        else { Invoke-NovelCompose -Arguments @('stop','novel') }
    } elseif ($Action -eq 'Login') {
        Invoke-NovelCompose -Arguments @('exec','novel','codex','login','--device-auth')
    } elseif ($Action -eq 'Logs') {
        Invoke-NovelCompose -Arguments @('logs','--tail','100','novel')
    } else { Invoke-NovelCompose -Arguments @('ps') }
} finally { Pop-Location }

param(
    [switch] $DryRun,
    [switch] $KeepIntegrations,
    [switch] $Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]] $RemainingArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PackageName = "mrjeffagency"
$MjaHomeDirname = ".mja"
$MjaCommands = @(
    # Include retired entry points so older installations are fully stopped and removed.
    "mja-desktop",
    "mja-server",
    "mja-claude",
    "mja-codex",
    "mja-pi",
    "mja-opencode",
    "mja-cline",
    "mja-hermes",
    "mja-dsh",
    "mja-grok",
    "mja-muse",
    "mja-aider",
    "mja-agy",
    "mja-doctor",
    "mja-update",
    "mja-init",
    "mrjeffagency"
)
$script:UvPath = ""
$script:UvToolBin = ""

function Show-Usage {
    @"
Usage: uninstall.ps1 [options]

Removes the MrJeffAgency uv tool and deletes ~/.mja/ after removal is verified.
Does not remove uv, Claude Code, Codex, Pi, OpenCode, Cline, Hermes Agent, DeepSeek Harness, Grok Build, Muse Code, Aider, Antigravity CLI, the uv-managed Python runtime, or shared PATH entries.

Options:
  -DryRun                Print commands without running them.
  -KeepIntegrations      Leave editor/app integrations unchanged.
  -Help                  Show this help text.
"@
}

function Write-Step {
    param([string] $Message)

    Write-Host ""
    Write-Host "==> $Message"
}

function Format-Argument {
    param([string] $Value)

    if ($Value -match '^[A-Za-z0-9_./:@%+=,\[\]\\-]+$') {
        return $Value
    }
    return "'" + ($Value -replace "'", "''") + "'"
}

function Format-Command {
    param(
        [string] $FilePath,
        [string[]] $Arguments = @()
    )

    $parts = @($FilePath) + $Arguments
    return ($parts | ForEach-Object { Format-Argument ([string] $_) }) -join " "
}

function Get-ApplicationCommand {
    param([string] $Name)

    $commands = @(Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue)
    if ($commands.Count -eq 0) {
        return $null
    }
    return $commands[0]
}

function Invoke-NativeResult {
    param(
        [string] $FilePath,
        [string[]] $Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $global:LASTEXITCODE = 0
        $output = (& $FilePath @Arguments 2>&1 | Out-String).Trim()
        return [pscustomobject] @{
            ExitCode = $LASTEXITCODE
            Output = $output
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Test-MissingUvToolError {
    param([string] $Output)

    $normalized = $Output.ToLowerInvariant()
    return $normalized.Contains($PackageName) -and $normalized.Contains("is not installed")
}

function Add-PathEntry {
    param([string] $PathEntry)

    if ([string]::IsNullOrWhiteSpace($PathEntry)) {
        return
    }
    $separator = [IO.Path]::PathSeparator
    $entries = @()
    if (-not [string]::IsNullOrEmpty($env:Path)) {
        $entries = $env:Path -split [regex]::Escape([string] $separator)
    }
    if ($entries -notcontains $PathEntry) {
        $env:Path = "$PathEntry$separator$env:Path"
    }
}

function Add-KnownUvPaths {
    Add-PathEntry (Join-Path $env:USERPROFILE ".local\bin")
    Add-PathEntry (Join-Path $env:USERPROFILE ".cargo\bin")
}

function Assert-NoMjaProcessesRunning {
    $running = @()
    foreach ($commandName in $MjaCommands) {
        $processes = @(Get-Process -Name $commandName -ErrorAction SilentlyContinue)
        if ($processes.Count -gt 0) {
            $running += $commandName
        }
    }
    if ($running.Count -gt 0) {
        throw "MrJeffAgency is still running ($($running -join ', ')). Stop those processes, then rerun uninstall."
    }
}

function Initialize-UvContext {
    Add-KnownUvPaths

    if ($DryRun) {
        Write-Host "+ uv tool dir --bin"
        return
    }

    $uvCommand = Get-ApplicationCommand "uv"
    if (-not $uvCommand) {
        throw "uv is required to remove the MrJeffAgency tool. Install uv, then rerun this uninstaller; ~/.mja was not deleted."
    }
    $script:UvPath = $uvCommand.Source

    $commandText = Format-Command -FilePath $script:UvPath -Arguments @("tool", "dir", "--bin")
    Write-Host "+ $commandText"
    $result = Invoke-NativeResult -FilePath $script:UvPath -Arguments @("tool", "dir", "--bin")
    if ($result.ExitCode -ne 0) {
        if (-not [string]::IsNullOrWhiteSpace($result.Output)) {
            [Console]::Error.WriteLine($result.Output)
        }
        throw "Could not determine the uv tool bin directory (exit code $($result.ExitCode)); ~/.mja was not deleted."
    }
    $script:UvToolBin = $result.Output.Trim()
    if ([string]::IsNullOrWhiteSpace($script:UvToolBin)) {
        throw "uv returned an empty tool bin directory; ~/.mja was not deleted."
    }
}

function Uninstall-MrJeffAgency {
    Write-Host "+ uv tool uninstall $PackageName"
    if ($DryRun) {
        return
    }

    $result = Invoke-NativeResult -FilePath $script:UvPath -Arguments @(
        "tool",
        "uninstall",
        $PackageName
    )
    if ($result.ExitCode -eq 0) {
        if (-not [string]::IsNullOrWhiteSpace($result.Output)) {
            Write-Host $result.Output
        }
        return
    }
    if (Test-MissingUvToolError -Output $result.Output) {
        Write-Host "MrJeffAgency uv tool is already absent; verifying its entry points."
        return
    }
    if (-not [string]::IsNullOrWhiteSpace($result.Output)) {
        [Console]::Error.WriteLine($result.Output)
    }
    throw "uv tool uninstall $PackageName failed with exit code $($result.ExitCode); ~/.mja was not deleted."
}

function Disconnect-MjaIntegrations {
    if ($KeepIntegrations) {
        return
    }
    if ($DryRun) {
        Write-Host "+ mja-doctor --disconnect-integrations"
        return
    }
    $doctorPath = $null
    foreach ($extension in @(".exe", ".cmd", ".bat", "")) {
        $candidate = Join-Path $script:UvToolBin "mja-doctor$extension"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $doctorPath = $candidate
            break
        }
    }
    if (-not $doctorPath) {
        throw "MJA's integration cleanup command is unavailable. Update MJA first, or disconnect editor/app integrations manually and rerun with -KeepIntegrations. MJA data was not deleted."
    }
    Write-Host "+ $(Format-Command -FilePath $doctorPath -Arguments @('--disconnect-integrations'))"
    $result = Invoke-NativeResult -FilePath $doctorPath -Arguments @("--disconnect-integrations")
    if (-not [string]::IsNullOrWhiteSpace($result.Output)) {
        Write-Host $result.Output
    }
    if ($result.ExitCode -ne 0) {
        throw "Editor/app integration cleanup failed. Correct the reported problem and retry. For older MJA versions, update first or disconnect manually and rerun with -KeepIntegrations. MJA and its data were not deleted."
    }
}

function Confirm-MjaCommandsRemoved {
    if ($DryRun) {
        Write-Host "+ verify all MrJeffAgency entry points are absent from the uv tool bin directory"
        return
    }

    $remaining = @()
    $extensions = @("", ".exe", ".cmd", ".bat", ".ps1")
    foreach ($commandName in $MjaCommands) {
        foreach ($extension in $extensions) {
            $commandPath = Join-Path $script:UvToolBin "$commandName$extension"
            if (Test-Path -LiteralPath $commandPath) {
                $remaining += $commandPath
            }
        }
    }
    if ($remaining.Count -gt 0) {
        throw "MrJeffAgency entry points remain after uv uninstall: $($remaining -join ', '); ~/.mja was not deleted."
    }
}

function Test-EquivalentPath {
    param(
        [string] $Left,
        [string] $Right
    )

    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) {
        return $false
    }
    try {
        return [string]::Equals(
            [IO.Path]::GetFullPath($Left),
            [IO.Path]::GetFullPath($Right),
            [StringComparison]::OrdinalIgnoreCase
        )
    }
    catch {
        return $false
    }
}

function Test-MjaDesktopShortcutTarget {
    param([string] $TargetPath)

    foreach ($extension in @("", ".exe", ".cmd", ".bat", ".ps1")) {
        $expectedTarget = Join-Path $script:UvToolBin "mja-desktop$extension"
        if (Test-EquivalentPath -Left $TargetPath -Right $expectedTarget) {
            return $true
        }
    }
    return $false
}

function Remove-MjaDesktopShortcuts {
    $shortcutPaths = @(
        (Join-Path $env:USERPROFILE "Desktop\MrJeffAgency.lnk"),
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\MrJeffAgency.lnk")
    )
    $shell = New-Object -ComObject WScript.Shell
    foreach ($shortcutPath in $shortcutPaths) {
        if (-not (Test-Path -LiteralPath $shortcutPath)) {
            continue
        }
        try {
            $shortcut = $shell.CreateShortcut($shortcutPath)
            $isMjaShortcut = Test-MjaDesktopShortcutTarget -TargetPath $shortcut.TargetPath
        }
        catch {
            $isMjaShortcut = $false
        }
        if (-not $isMjaShortcut) {
            Write-Host "A shortcut not managed by MrJeffAgency exists at $shortcutPath; leaving it unchanged."
            continue
        }
        Write-Host "+ Remove-Item -LiteralPath $(Format-Argument $shortcutPath) -Force"
        if (-not $DryRun) {
            Remove-Item -LiteralPath $shortcutPath -Force
        }
    }
}

function Purge-MjaHome {
    $mjaHome = Join-Path $env:USERPROFILE $MjaHomeDirname
    if (-not (Test-Path -LiteralPath $mjaHome)) {
        Write-Host "No MJA config directory at $mjaHome; skipping purge."
        return
    }

    $commandText = @(
        "Remove-Item",
        "-LiteralPath",
        (Format-Argument $mjaHome),
        "-Recurse",
        "-Force"
    ) -join " "
    Write-Host "+ $commandText"
    if ($DryRun) {
        return
    }

    Remove-Item -LiteralPath $mjaHome -Recurse -Force
    if (Test-Path -LiteralPath $mjaHome) {
        throw "MJA config directory still exists after deletion: $mjaHome"
    }
}

if ($Help) {
    Show-Usage
    return
}
if ($RemainingArgs.Count -gt 0) {
    Show-Usage
    throw "Unknown option: $($RemainingArgs -join ' ')"
}
if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
    throw "USERPROFILE is not set; cannot locate MrJeffAgency data."
}

Write-Step "Checking for running MrJeffAgency processes"
Assert-NoMjaProcessesRunning

Write-Step "Locating the uv-managed MrJeffAgency installation"
Initialize-UvContext

Write-Step "Disconnecting MJA editor/app integrations"
Disconnect-MjaIntegrations

Write-Step "Removing the MrJeffAgency uv tool"
Uninstall-MrJeffAgency

Write-Step "Verifying MrJeffAgency entry points were removed"
Confirm-MjaCommandsRemoved

Write-Step "Removing MrJeffAgency desktop shortcuts"
Remove-MjaDesktopShortcuts

Write-Step "Purging MJA config and data from ~/.mja"
Purge-MjaHome

Write-Host ""
if ($DryRun) {
    Write-Host "Dry run complete. No changes were made."
}
else {
    Write-Host "MrJeffAgency has been removed and verified."
    Write-Host "uv, Claude Code, Codex, Pi, OpenCode, Cline, Hermes Agent, DeepSeek Harness, Grok Build, Muse Code, Aider, the uv-managed Python runtime, and shared PATH entries were left installed."
}

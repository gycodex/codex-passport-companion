$ErrorActionPreference = 'Stop'
$repoPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$launcherPath = Join-Path $repoPath 'start-console.vbs'
if (-not (Test-Path -LiteralPath $launcherPath)) { throw 'Extract the entire Passport package before installing.' }
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcutFolders = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
foreach ($shortcutFolder in $shortcutFolders) {
    $shortcut = $shortcutShell.CreateShortcut((Join-Path $shortcutFolder 'Passport.lnk'))
    $shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $shortcut.Arguments = '"' + $launcherPath + '"'
    $shortcut.WorkingDirectory = $repoPath
    $shortcut.IconLocation = (Join-Path $PSScriptRoot 'console\passport.ico') + ',0'
    $shortcut.Description = 'Passport desktop companion'
    $shortcut.Save()
}
Write-Host 'Passport shortcuts are ready on your desktop and Start menu.'
Write-Host 'Keep this folder in place. Open Passport using its shortcut.'
Read-Host 'Press Enter to close'

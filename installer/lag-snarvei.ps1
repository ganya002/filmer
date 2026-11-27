param(
  [Parameter(Mandatory = $true)][string]$Dest,
  [string]$PythonCmd = ""
)
$ErrorActionPreference = "Stop"

if ($PythonCmd -ne "") {
  if ($PythonCmd -eq "py -3") {
    $run = 'py -3 "%~dp0app\server.py"'
  } elseif ($PythonCmd -eq "python") {
    $run = 'python "%~dp0app\server.py"'
  } else {
    $run = '"' + $PythonCmd + '" "%~dp0app\server.py"'
  }
  $bat = "@echo off`r`ncd /d `"%~dp0`"`r`n" + $run + "`r`n"
  Set-Content -LiteralPath (Join-Path $Dest "kjor.bat") -Value $bat -Encoding Default
}

$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$programs = [Environment]::GetFolderPath("Programs")
$icon = Join-Path $Dest "assets\icon.ico"
$target = Join-Path $env:SystemRoot "System32\wscript.exe"
$arguments = '"' + (Join-Path $Dest "Start.vbs") + '"'

foreach ($lnkPath in @(
  (Join-Path $desktop "Mine filmer.lnk"),
  (Join-Path $programs "Mine filmer.lnk")
)) {
  $shortcut = $shell.CreateShortcut($lnkPath)
  $shortcut.TargetPath = $target
  $shortcut.Arguments = $arguments
  $shortcut.WorkingDirectory = $Dest
  $shortcut.Description = "Mine filmer"
  if (Test-Path -LiteralPath $icon) {
    $shortcut.IconLocation = "$icon,0"
  }
  $shortcut.Save()
}

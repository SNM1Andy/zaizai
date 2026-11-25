param([switch]$Restore)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$shell=New-Object -ComObject WScript.Shell
$legacy=if ($env:ZAIZAI_LEGACY_SHORTCUT) {$env:ZAIZAI_LEGACY_SHORTCUT} else {Join-Path (Split-Path $root -Parent) 'Zaizai\Zaizai.lnk'}
$backup=Join-Path $root 'rollback\Zaizai.lnk'
$desktop=Join-Path ([Environment]::GetFolderPath('Desktop')) '再再.lnk'
$exe=Join-Path $root '再再.exe'
if($Restore){
    if((Get-CimInstance Win32_Process -Filter "Name='python.exe'"|Where-Object {$_.CommandLine -like "*$root\host\desktop.py*"})){throw '请先关闭再再窗口后恢复旧入口。'}
    Copy-Item -LiteralPath $backup -Destination $legacy -Force
    $link=$shell.CreateShortcut($desktop)
    $link.TargetPath=$shell.CreateShortcut($backup).TargetPath
    $link.Arguments=$shell.CreateShortcut($backup).Arguments
    $link.WorkingDirectory=$shell.CreateShortcut($backup).WorkingDirectory
    $link.Save()
    Write-Output '已恢复 1.0 入口，2.0 的全部存档保存在 D:\再再2.0\state。'
    exit
}
foreach($path in @($legacy,$desktop)){
    if(Test-Path -LiteralPath $path){
        $existing=$shell.CreateShortcut($path)
        if($path -eq $desktop -and $existing.TargetPath -ne $exe -and $existing.Arguments -notlike '*Zaizai.wsb*'){
            throw "已经存在其他同名入口：$path"
        }
    }
    $link=$shell.CreateShortcut($path)
    $link.TargetPath=$exe
    $link.Arguments=''
    $link.WorkingDirectory=$root
    $link.Description='再再 2.0 原生对话和监测'
    $link.IconLocation="$exe,0"
    $link.Save()
    if($shell.CreateShortcut($path).TargetPath -ne $exe){throw "快捷方式读回失败：$path"}
}


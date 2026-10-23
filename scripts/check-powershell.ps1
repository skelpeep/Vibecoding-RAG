$ErrorActionPreference = 'Stop'
$failedFiles = @()
foreach ($file in Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1') {
    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
    $nonAscii = @($bytes | Where-Object { $_ -gt 127 }).Count -gt 0
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if (($nonAscii -and -not $hasBom) -or $parseErrors.Count -gt 0) {
        $failedFiles += $file.Name
        Write-Output "FAIL $($file.Name): UTF8_BOM=$hasBom; parse_errors=$($parseErrors.Count)"
        foreach ($problem in $parseErrors) { Write-Output $problem.Message }
    } else {
        Write-Output "PASS $($file.Name)"
    }
}
if ($failedFiles.Count -gt 0) { throw 'PowerShell script encoding or syntax check failed.' }
Write-Output "PowerShell $($PSVersionTable.PSVersion): all scripts passed."

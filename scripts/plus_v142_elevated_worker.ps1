[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Bridge,
    [Parameter(Mandatory = $true)][string]$Request,
    [Parameter(Mandatory = $true)][string]$Response
)

$ErrorActionPreference = "Stop"
$arguments = @($Bridge, "--elevated-request", $Request, "--elevated-response", $Response)
$process = Start-Process -FilePath $Python -ArgumentList $arguments -Verb RunAs -Wait -PassThru
exit $process.ExitCode

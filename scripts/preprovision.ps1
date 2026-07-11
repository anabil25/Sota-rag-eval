$ErrorActionPreference = 'Stop'

python "$PSScriptRoot/preprovision.py"
if ($LASTEXITCODE -ne 0) {
  throw "preprovision.py failed with exit code $LASTEXITCODE"
}
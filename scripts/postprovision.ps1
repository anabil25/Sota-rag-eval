$ErrorActionPreference = 'Stop'

python "$PSScriptRoot/postprovision.py"
if ($LASTEXITCODE -ne 0) {
  throw "postprovision.py failed with exit code $LASTEXITCODE"
}
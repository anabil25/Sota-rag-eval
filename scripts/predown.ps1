$ErrorActionPreference = 'Stop'

python "$PSScriptRoot/predown.py"
if ($LASTEXITCODE -ne 0) {
  throw "predown.py failed with exit code $LASTEXITCODE"
}

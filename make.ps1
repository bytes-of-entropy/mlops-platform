<#
    Windows mirror of the Makefile. The Makefile stays canonical, since CI runs it, and
    tests/test_makefile_mirror.py fails if a target exists in one and not the other.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Target = 'help'
)

$ErrorActionPreference = 'Stop'

# --project-directory anchors both the .env lookup and every relative bind mount at the
# repository root. See the Makefile for what happens without it; a test asserts both
# entrypoints and the integration suite pass it.
$Compose = @('compose', '--project-directory', '.', '-f', 'compose/docker-compose.yml')
$ComposeQs = @('compose', '--project-directory', '.', '-f', 'compose/docker-compose.yml', '-f', 'compose/docker-compose.quickstart.yml')
$Py = '.venv/Scripts/python.exe'
$BootstrapPy = 'py'
# Kept in step with WAIT_TIMEOUT in the Makefile; a test fails if the two diverge.
$WaitTimeout = '300'
# Kept in step with the Makefile's SYFT, GRYPE, SBOM_DIR and SCAN_FAIL_ON; a test fails if the
# cataloguer versions diverge, because two machines pinning different cataloguers produce two
# inventories and only one of them is in the diff.
$Syft = 'anchore/syft:v1.9.0'
$Grype = 'anchore/grype:v0.79.0'
$SbomDir = 'sbom'
$ScanFailOn = 'high'

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        $rendered = $Arguments -join ' '
        throw ('{0} {1} failed with exit code {2}' -f $Exe, $rendered, $LASTEXITCODE)
    }
}

switch ($Target) {
    'help' {
        Write-Output 'setup           create .venv and install dev dependencies'
        Write-Output 'test            run the test suite'
        Write-Output 'lint            formatting, ruff and mypy, changing nothing'
        Write-Output 'hooks           run every pre-commit hook over the whole tree'
        Write-Output 'check           everything the gate requires: lint, hooks, test'
        Write-Output 'doctor          check the machine can start the stack, and say what is wrong'
        Write-Output 'build           build the one image in the spine, without starting anything'
        Write-Output 'sbom            catalogue every image and write the reviewable inventories'
        Write-Output 'scan            scan the catalogued SBOMs and fail on high or above'
        Write-Output 'up              start the full spine (all services)'
        Write-Output 'up-quickstart   start the 4 GB / 2 CPU reviewer profile'
        Write-Output 'down            stop and remove containers, KEEP volumes'
        Write-Output 'clean           stop and remove containers AND volumes'
        Write-Output 'reset           clean, then start the full spine from nothing'
    }
    'setup' {
        Invoke-Checked $BootstrapPy @('-3', '-m', 'venv', '.venv')
        Invoke-Checked $Py @('-m', 'pip', 'install', '--upgrade', 'pip')
        Invoke-Checked $Py @('-m', 'pip', 'install', '-e', '.[dev]')
        # Mirrors the Makefile: hooks are per-clone, so a committed config installs nothing on
        # its own. Absent .git is not an error; the CI hooks job runs them either way.
        if (Test-Path '.git') { Invoke-Checked $Py @('-m', 'pre_commit', 'install') }
        else { Write-Output 'no .git here, so no hook was installed; the CI hooks job runs them regardless' }
    }
    'test' { Invoke-Checked $Py @('-m', 'pytest') }
    'lint' {
        Invoke-Checked $Py @('-m', 'ruff', 'format', '--check', '.')
        Invoke-Checked $Py @('-m', 'ruff', 'check', '.')
        Invoke-Checked $Py @('-m', 'mypy')
    }
    'hooks' { Invoke-Checked $Py @('-m', 'pre_commit', 'run', '--all-files') }
    'check' {
        Invoke-Checked $Py @('-m', 'ruff', 'format', '--check', '.')
        Invoke-Checked $Py @('-m', 'ruff', 'check', '.')
        Invoke-Checked $Py @('-m', 'mypy')
        Invoke-Checked $Py @('-m', 'pre_commit', 'run', '--all-files')
        Invoke-Checked $Py @('-m', 'pytest')
    }
    'fmt' {
        Invoke-Checked $Py @('-m', 'ruff', 'format', '.')
        Invoke-Checked $Py @('-m', 'ruff', 'check', '--fix', '.')
    }
    # Mirrors the Makefile's prerequisite: both start targets refuse before they start
    # something that would come up healthy and wrong. A test asserts this branch runs it.
    'doctor' { Invoke-Checked $Py @('-m', 'preflight') }
    'build' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'build')) }
    'sbom' {
        # Mirrors the Makefile target, including the bind mount: the SPDX document is written by the
        # cataloguer straight into $SbomDir rather than piped through PowerShell, which would have to
        # pick an encoding for it and would produce a document byte-different from the Makefile's.
        New-Item -ItemType Directory -Force $SbomDir | Out-Null
        $mount = ($PWD.Path -replace '\\', '/') + "/$SbomDir"
        # Not `config --images`: that reports the profiles it is given and has already omitted a
        # profiled service from this repository's list once. supply.images reads the `image` keys, so
        # it cannot come back short, and it already sorts and deduplicates.
        $images = & $Py @('-m', 'supply.images')
        if ($LASTEXITCODE -ne 0) { throw 'supply.images could not list the spine images' }
        foreach ($image in $images) {
            $name = ($image -split '@')[0] -replace '[/:]', '_'
            Write-Output "cataloguing $image"
            Invoke-Checked 'docker' @(
                'run', '--rm',
                '-v', '/var/run/docker.sock:/var/run/docker.sock',
                '-v', "${mount}:/out",
                $Syft, $image, '-o', "spdx-json=/out/$name.spdx.json"
            )
            Invoke-Checked $Py @(
                '-m', 'supply.inventory',
                "$SbomDir/$name.spdx.json", "$SbomDir/$name.packages.txt"
            )
        }
    }
    'scan' {
        # Reads the SBOM rather than the image, so what is scanned is what was inventoried.
        $mount = ($PWD.Path -replace '\\', '/') + "/$SbomDir"
        $documents = @(Get-ChildItem -Path $SbomDir -Filter '*.spdx.json' -ErrorAction Ignore)
        if (-not $documents) { throw "no SBOMs in $SbomDir; run './make.ps1 sbom' first" }
        foreach ($document in $documents) {
            Write-Output "scanning $($document.Name)"
            Invoke-Checked 'docker' @(
                'run', '--rm', '-v', "${mount}:/sbom",
                $Grype, "sbom:/sbom/$($document.Name)", '--fail-on', $ScanFailOn
            )
        }
    }
    'up' {
        Invoke-Checked $Py @('-m', 'preflight')
        Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'up', '-d', '--build', '--wait', '--wait-timeout', $WaitTimeout))
    }
    'up-quickstart' {
        Invoke-Checked $Py @('-m', 'preflight')
        Invoke-Checked 'docker' ($ComposeQs + @('up', '-d', '--build', '--wait', '--wait-timeout', $WaitTimeout))
    }
    'down' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'down', '--remove-orphans')) }
    'clean' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'down', '--remove-orphans', '--volumes')) }
    'reset' {
        Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'down', '--remove-orphans', '--volumes'))
        Invoke-Checked $Py @('-m', 'preflight')
        Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'up', '-d', '--build', '--wait', '--wait-timeout', $WaitTimeout))
    }
    'ps' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'ps')) }
    'logs' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'logs', '--tail=100')) }
    'config' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'config')) }
    default { throw "Unknown target. Run './make.ps1 help' for the list." }
}

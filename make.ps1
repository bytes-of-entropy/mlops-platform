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
# Kept in step with the Makefile's five supply settings; a test fails if they diverge, because two
# machines pinning different cataloguers produce two inventories and only one is in the diff. Both
# tools are digest-pinned and both carry an expiry: a scanner is only as good as a database that must
# be fresh, and its publisher retires the schema old versions speak, so a pin that is merely exact
# stops working rather than merely ageing. Record 020 argues it.
# SUPPLY_TOOLS_EXPIRE: 2027-02-28
$Syft = 'anchore/syft:v1.51.1@sha256:95fe0835e5bebc6f8b1f8acef68d47d63d594ef4c0f25c097ff853b23cbac74c'
$Grype = 'anchore/grype:v0.118.0@sha256:8a93fc48da96bd6ec5981279d099b69de11541dc68fdf222fb9161f8ff284af7'
$SbomDir = 'sbom'
$GrypeDbVolume = 'mlops-platform-grype-db'
# Mirrors the Makefile's `?=`. Kept as four separate overrides after the defaults rather than folded
# into them, so the line a reader looks at to learn the pinned version is still a plain assignment.
if ($env:SYFT) { $Syft = $env:SYFT }
if ($env:GRYPE) { $Grype = $env:GRYPE }
if ($env:SBOM_DIR) { $SbomDir = $env:SBOM_DIR }
if ($env:GRYPE_DB_VOLUME) { $GrypeDbVolume = $env:GRYPE_DB_VOLUME }

function Get-SbomNames {
    <#
        The base name of every SBOM in $SbomDir, which is the stem every other file for that image
        shares: <name>.spdx.json, <name>.findings.json, <name>.known.txt.
    #>
    $documents = @(Get-ChildItem -Path $SbomDir -Filter '*.spdx.json' -ErrorAction Ignore)
    if (-not $documents) { throw "no SBOMs in $SbomDir; run './make.ps1 sbom' first" }
    $documents | ForEach-Object { $_.BaseName -replace '\.spdx$', '' }
}

function Invoke-Scan {
    <#
        Scan every SBOM and write both outputs: a table for a person reading the log and JSON for the
        gate. Parsing the table would mean owning a column layout nobody promised.

        Shared by scan-report, scan and scan-accept, which differ only in what they do with the
        answer: nothing, gate on it, or accept it.
    #>
    $mount = ($PWD.Path -replace '\\', '/') + "/$SbomDir"
    Invoke-GrypeDb
    foreach ($name in Get-SbomNames) {
        Write-Output "scanning $name"
        Invoke-Checked 'docker' @(
            'run', '--rm', '-v', "${mount}:/sbom",
            '-v', "${GrypeDbVolume}:/db", '-e', 'GRYPE_DB_CACHE_DIR=/db',
            $Grype, "sbom:/sbom/$name.spdx.json",
            '-o', 'table', '-o', "json=/sbom/$name.findings.json"
        )
    }
}

function Invoke-GrypeDb {
    <#
        Fetch the vulnerability database, then say what was fetched. `db status` reports on a
        database and does not fetch one, so on a fresh cache the report alone was what stopped the
        database existing; see docs/decisions/020. A scan result is a function of the SBOM, the
        scanner and the database, and this is the only one of the three the log would not otherwise
        record.
    #>
    foreach ($verb in @('update', 'status')) {
        Invoke-Checked 'docker' @(
            'run', '--rm', '-v', "${GrypeDbVolume}:/db", '-e', 'GRYPE_DB_CACHE_DIR=/db',
            $Grype, 'db', $verb
        )
    }
}

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
        Write-Output 'scan-report      scan every SBOM and print what was found, gating on nothing'
        Write-Output 'scan            the same scan, failing on an advisory not in the baseline'
        Write-Output 'scan-accept     rewrite the baselines from the current scan, as a diff to review'
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
    'scan-report' {
        Invoke-Scan
    }
    'scan' {
        # The gate is supply.findings rather than --fail-on. After record 021 the residue is 138
        # Critical and 870 High with no fix inside the current major, so a severity threshold fails
        # identically every run and says nothing. What fails here is an advisory identifier absent
        # from the committed baseline. Record 022 argues it.
        #
        # Every document is compared before anything throws, so one new advisory in the first image
        # does not hide three in the last.
        Invoke-Scan
        $failed = @()
        foreach ($name in Get-SbomNames) {
            & $Py @('-m', 'supply.findings', "$SbomDir/$name.known.txt",
                    "$SbomDir/$name.findings.json")
            if ($LASTEXITCODE -ne 0) { $failed += $name }
        }
        if ($failed.Count -gt 0) {
            throw ('unbaselined advisories in: {0}' -f ($failed -join ' '))
        }
    }
    'scan-accept' {
        # Deliberate, and separate from `scan` for that reason: it rewrites every baseline from the
        # current scan, so the record of what changed is the git diff and the review is reading it.
        & $PSCommandPath 'sbom'
        if ($LASTEXITCODE -ne 0) { throw 'sbom failed' }
        Invoke-Scan
        foreach ($name in Get-SbomNames) {
            Invoke-Checked $Py @(
                '-m', 'supply.findings', '--accept',
                "$SbomDir/$name.known.txt", "$SbomDir/$name.findings.json"
            )
        }
        Write-Output "review the diff in $SbomDir/*.known.txt before committing it"
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

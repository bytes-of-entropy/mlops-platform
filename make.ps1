<#
    Windows mirror of the Makefile. The Makefile stays canonical — CI runs it — and
    tests/test_makefile_mirror.py fails if a target exists in one and not the other.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Target = 'help'
)

$ErrorActionPreference = 'Stop'

$Compose = @('compose', '-f', 'compose/docker-compose.yml')
$ComposeQs = @('compose', '-f', 'compose/docker-compose.yml', '-f', 'compose/docker-compose.quickstart.yml')
$Py = '.venv/Scripts/python.exe'
$BootstrapPy = 'py'
# Kept in step with WAIT_TIMEOUT in the Makefile; a test fails if the two diverge.
$WaitTimeout = '300'

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
        Write-Output 'up              start the full spine (all services)'
        Write-Output 'up-quickstart   start the 4 GB / 2 CPU reviewer profile'
        Write-Output 'down            stop and remove containers, KEEP volumes'
        Write-Output 'clean           stop and remove containers AND volumes'
    }
    'setup' {
        Invoke-Checked $BootstrapPy @('-3', '-m', 'venv', '.venv')
        Invoke-Checked $Py @('-m', 'pip', 'install', '--upgrade', 'pip')
        Invoke-Checked $Py @('-m', 'pip', 'install', '-e', '.[dev]')
        # Mirrors the Makefile: hooks are per-clone, so a committed config installs nothing on
        # its own. Absent .git is not an error -- the CI hooks job runs them either way.
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
    'up' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'up', '-d', '--wait', '--wait-timeout', $WaitTimeout)) }
    'up-quickstart' { Invoke-Checked 'docker' ($ComposeQs + @('up', '-d', '--wait', '--wait-timeout', $WaitTimeout)) }
    'down' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'down', '--remove-orphans')) }
    'clean' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'down', '--remove-orphans', '--volumes')) }
    'ps' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'ps')) }
    'logs' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'logs', '--tail=100')) }
    'config' { Invoke-Checked 'docker' ($Compose + @('--profile', 'full', 'config')) }
    default { throw "Unknown target. Run './make.ps1 help' for the list." }
}

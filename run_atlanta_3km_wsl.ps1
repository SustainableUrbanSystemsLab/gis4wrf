param(
  [string]$Distro = "auto",
  [int]$Nproc = 24,
  [string]$WinRoot = "$env:USERPROFILE\\Documents\\gis4wrf"
)

$resolvedDistro = $Distro
if ($Distro -eq "auto" -or [string]::IsNullOrWhiteSpace($Distro)) {
  $distros = @(wsl -l -q 2>$null | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  if ($distros.Count -eq 0) {
    Write-Error "No WSL distros found. Install one first (for example, Ubuntu)."
    exit 1
  }
  $preferred = @(
    "Ubuntu-20.04",
    "Ubuntu-22.04",
    "Ubuntu-24.04",
    "Ubuntu"
  )
  $resolvedDistro = ($preferred | Where-Object { $distros -contains $_ } | Select-Object -First 1)
  if (-not $resolvedDistro) {
    $resolvedDistro = $distros[0]
  }
}

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoSlash = ($repo -replace '\\','/')
$rootSlash = ($WinRoot -replace '\\','/')
$repoWsl = wsl -d $resolvedDistro -- wslpath -u -- "$repoSlash" 2>$null | ForEach-Object { $_.Trim() }
$rootWsl = wsl -d $resolvedDistro -- wslpath -u -- "$rootSlash" 2>$null | ForEach-Object { $_.Trim() }
if (-not $repoWsl) {
  if ($repo -match '^[A-Za-z]:') {
    $drive = $repo.Substring(0,1).ToLower()
    $repoWsl = "/mnt/$drive/" + ($repo.Substring(3) -replace '\\','/')
  }
}
if (-not $rootWsl) {
  if ($WinRoot -match '^[A-Za-z]:') {
    $drive = $WinRoot.Substring(0,1).ToLower()
    $rootWsl = "/mnt/$drive/" + ($WinRoot.Substring(3) -replace '\\','/')
  }
}

if (-not $repoWsl) {
  Write-Error "Failed to resolve repo path in WSL. Is the distro '$resolvedDistro' installed?"
  exit 1
}

$cmd = @"
cd "$repoWsl"
export NPROC=$Nproc
export WIN_ROOT="$rootWsl"
./wsl_run_atlanta_3km.sh
"@

wsl -d $resolvedDistro -- bash -lc $cmd

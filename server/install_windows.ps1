param([switch]$NonInteractive)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = $PSScriptRoot
$runtime = Join-Path $root '.runtime'
$venv = Join-Path $root '.venv'
$owner = Join-Path $runtime 'maibot-sing-managed.txt'
$config = Join-Path $root 'settings.json'
$gptCommit = 'b4570b876f5c086819ba84e3215472733c6a7b70'
$assetCommit = 'e6d0c1a17da07c33557852f9dfa2bd44cc75737d'

function Run-Checked([string]$exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "命令执行失败（退出码 $LASTEXITCODE）：$exe" }
}

function Download-Checked([string]$url, [string]$target, [string]$sha256) {
    if (Test-Path -LiteralPath $target) {
        if ($sha256 -and (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $sha256) {
            throw "已有文件校验失败：$target；请自行确认或移走该文件后重试。"
        }
        return
    }
    $part = "$target.$([guid]::NewGuid().ToString('N')).part"
    Write-Host "下载：$url"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
    if ($curl) {
        & $curl --fail --location --retry 2 --connect-timeout 20 --max-time 1800 --output $part $url
        if ($LASTEXITCODE -ne 0) { throw "下载失败，请检查网络：$url" }
    } else {
        Invoke-WebRequest -Uri $url -OutFile $part -UseBasicParsing -TimeoutSec 1800
    }
    if ($sha256 -and (Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash -ne $sha256) {
        throw "下载文件校验失败：$part"
    }
    Move-Item -LiteralPath $part -Destination $target
}

try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw '目前只支持 64 位 Windows。' }
    if ((Test-Path -LiteralPath $runtime) -and -not (Test-Path -LiteralPath $owner)) {
        throw '检测到已有 .runtime，但不是此安装器创建的目录；为避免覆盖，安装已停止。'
    }
    if ((Test-Path -LiteralPath $venv) -and -not (Test-Path -LiteralPath $owner)) {
        throw '检测到已有 .venv，安装器不会覆盖；请先使用独立目录。'
    }
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    if (-not (Test-Path -LiteralPath $owner)) {
        [IO.File]::WriteAllText($owner, 'Managed by maibot singing installer')
    }
    $env:PYTHONNOUSERSITE = '1'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $runtime 'python'
    $env:UV_CACHE_DIR = Join-Path $runtime 'uv-cache'
    $env:UV_NO_CONFIG = '1'
    $env:TEMP = Join-Path $runtime 'temp'
    $env:TMP = $env:TEMP
    $env:PIP_CACHE_DIR = Join-Path $runtime 'pip-cache'
    New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null

    Write-Host '[1/6] 准备独立 Python 工具'
    $uvZip = Join-Path $runtime 'uv-0.8.16.zip'
    Download-Checked 'https://github.com/astral-sh/uv/releases/download/0.8.16/uv-x86_64-pc-windows-msvc.zip' $uvZip '97fb93678eca3b4f731ea3879ae2e78787976e03f38c9c6fb744ab28bc3aec1b'
    $uvDir = Join-Path $runtime 'uv'
    $uv = Join-Path $uvDir 'uv.exe'
    if (-not (Test-Path -LiteralPath $uv)) { Expand-Archive -LiteralPath $uvZip -DestinationPath $uvDir -Force }
    if (-not (Test-Path -LiteralPath $uv)) { throw '无法找到下载的 uv.exe。' }
    Run-Checked $uv @('python', 'install', '3.9', '--install-dir', $env:UV_PYTHON_INSTALL_DIR)
    $python = Join-Path $venv 'Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) { Run-Checked $uv @('venv', '--managed-python', '--seed', '--python', '3.9', $venv) }

    Write-Host '[2/6] 安装独立 Python 依赖及 NVIDIA CUDA 版本 PyTorch'
    Run-Checked $python @('-s', '-m', 'pip', 'install', 'pip==23.3.2', 'setuptools<70', 'wheel')
    Run-Checked $python @('-s', '-m', 'pip', 'install', 'torch==2.0.1+cu118', 'torchaudio==2.0.2+cu118', '--index-url', 'https://download.pytorch.org/whl/cu118')
    $wheelDir = Join-Path $runtime 'wheels'
    New-Item -ItemType Directory -Path $wheelDir -Force | Out-Null
    $fairseqWheel = Join-Path $wheelDir 'fairseq-0.12.2-cp39-cp39-win_amd64.whl'
    Download-Checked 'https://github.com/real-Elysia886/maibot-maising/releases/download/v1.0.0/fairseq-0.12.2-cp39-cp39-win_amd64.whl' $fairseqWheel '6462b57088ba3d070016b5c58660233816bdbfe149747c9586b579a1e2355ea1'
    Run-Checked $python @('-s', '-m', 'pip', 'install', '--no-deps', $fairseqWheel)
    Run-Checked $python @('-s', '-m', 'pip', 'install', '-r', (Join-Path $root 'requirements.txt'), 'librosa==0.9.2', 'numba==0.56.4', 'scipy==1.9.3', 'imageio-ffmpeg')

    Write-Host '[3/6] 准备 Node.js 和音乐检索依赖'
    $node = (Get-Command node.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
    $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
    if ($node -and $npm) {
        & $node -e 'if(parseInt(process.versions.node,10)<18)process.exit(1)'
        if ($LASTEXITCODE -ne 0) { $node = $null; $npm = $null }
    }
    if (-not $node -or -not $npm) {
        $nodeZip = Join-Path $runtime 'node-v20.19.4-win-x64.zip'
        Download-Checked 'https://nodejs.org/dist/v20.19.4/node-v20.19.4-win-x64.zip' $nodeZip '1bf83e5958157d13673507349238236aec4f6efc95cf426cbe126a999a3e4c0b'
        $nodeDir = Join-Path $runtime 'node'
        $node = Join-Path $nodeDir 'node-v20.19.4-win-x64/node.exe'
        $npm = Join-Path $nodeDir 'node-v20.19.4-win-x64/npm.cmd'
        if (-not (Test-Path -LiteralPath $node)) { Expand-Archive -LiteralPath $nodeZip -DestinationPath $nodeDir -Force }
    }
    if (-not (Test-Path -LiteralPath $node) -or -not (Test-Path -LiteralPath $npm)) { throw '找不到可用的 Node.js 和 npm。' }
    $env:PATH = (Split-Path -Parent $node) + [IO.Path]::PathSeparator + $env:PATH
    $nodeDeps = Join-Path $runtime 'node-deps'
    New-Item -ItemType Directory -Path $nodeDeps -Force | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $nodeDeps 'package.json'))) {
        Copy-Item -LiteralPath (Join-Path $root 'package.json') -Destination $nodeDeps
        Copy-Item -LiteralPath (Join-Path $root 'package-lock.json') -Destination $nodeDeps
    }
    Push-Location $nodeDeps
    try { Run-Checked $npm @('install', '--no-audit', '--no-fund') } finally { Pop-Location }

    Write-Host '[4/6] 获取 UVR5 代码与基础模型'
    $gptZip = Join-Path $runtime "gpt-sovits-$gptCommit.zip"
    Download-Checked "https://github.com/RVC-Boss/GPT-SoVITS/archive/$gptCommit.zip" $gptZip 'ffdf9273348a58000cbed695aeaa4fd99f668451ef02cab5a59fe70a14bb8713'
    $gptRoot = Join-Path $runtime "GPT-SoVITS-$gptCommit"
    if (-not (Test-Path -LiteralPath (Join-Path $gptRoot 'tools/uvr5/vr.py'))) { Expand-Archive -LiteralPath $gptZip -DestinationPath $runtime -Force }
    $uvrDir = Join-Path $gptRoot 'tools/uvr5'
    if (-not (Test-Path -LiteralPath (Join-Path $uvrDir 'vr.py'))) { throw '下载的 UVR5 代码不完整。' }
    $rvcDir = (& $python -s -c "from importlib.metadata import distribution; print(distribution('rvc-python').locate_file('rvc_python'))").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $rvcDir) { throw '未能定位 rvc-python。' }
    $base = Join-Path $rvcDir 'base_model'
    New-Item -ItemType Directory -Path $base -Force | Out-Null
    $assets = Join-Path $runtime 'models'
    New-Item -ItemType Directory -Path $assets -Force | Out-Null
    $assetUrl = "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/$assetCommit"
    Download-Checked "$assetUrl/rmvpe.pt" (Join-Path $base 'rmvpe.pt') '6d62215f4306e3ca278246188607209f09af3dc77ed4232efdd069798c4ec193'
    # rvc-python 0.1.5 会检查此文件；预先下载以避免首次启动时从其他地址自动下载。
    Download-Checked "$assetUrl/rmvpe.onnx" (Join-Path $base 'rmvpe.onnx') '5370e71ac80af8b4b7c793d27efd51fd8bf962de3a7ede0766dac0befa3660fd'
    Download-Checked "$assetUrl/hubert_base.pt" (Join-Path $base 'hubert_base.pt') 'f54b40fd2802423a5643779c4861af1e9ee9c1564dc9d32f54f20b5ffba7db96'
    $uvrModel = Join-Path $assets 'HP5_only_main_vocal.pth'
    Download-Checked "$assetUrl/uvr5_weights/HP5_only_main_vocal.pth" $uvrModel '5908891829634926119720241e8573d97cbeb8277110a7512bdb0bd7563258ee'

    Write-Host '[5/6] 检查运行环境'
    $ffmpeg = (& $python -s -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())').Trim()
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ffmpeg)) { throw '无法定位 FFmpeg。' }
    Run-Checked $python @('-s', '-c', 'import torch,torchaudio,numpy,librosa,scipy;assert torch.cuda.is_available();print(torch.cuda.get_device_name(0))')

    Write-Host '[6/6] 配置用户选择的 RVC 模型'
    if (Test-Path -LiteralPath $config) {
        Write-Host '已有 settings.json，不做覆盖；请自行核对模型和依赖路径。'
    } else {
        $model = ''; $index = ''
        if (-not $NonInteractive) {
            Add-Type -AssemblyName System.Windows.Forms
            $dialog = New-Object System.Windows.Forms.OpenFileDialog
            $dialog.Title = '选择你有权使用的 RVC v2 音色模型（.pth）'
            $dialog.Filter = 'RVC 模型 (*.pth)|*.pth'
            if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $model = $dialog.FileName }
            if ($model) {
                $dialog.Title = '可选：选择与模型配套的 .index，没有则取消'
                $dialog.Filter = 'RVC 索引 (*.index)|*.index'
                if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $index = $dialog.FileName }
            }
        }
        $settings = [ordered]@{host='127.0.0.1';port=9881;api_token='';rvc_model=$model;rvc_index=$index;uvr_model=$uvrModel;uvr_tools_dir=$uvrDir;node_executable=$node;node_modules=(Join-Path $nodeDeps 'node_modules');ffmpeg_executable=$ffmpeg}
        [IO.File]::WriteAllText($config, ($settings | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
        if (-not $model) { Write-Host '尚未选择 RVC 模型，请在 settings.json 中填写 rvc_model。' }
    }
    Write-Host '环境准备完成。确认模型和 settings.json 后运行 start_server.bat；安装器不会启动服务。'
} catch {
    Write-Error "安装未完成：$($_.Exception.Message)"
    exit 1
}

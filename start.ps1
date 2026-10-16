# Starts Qwen3-4B (Tier 1, :8081), Qwen3-8B (Tier 2, :8082), then the companion (:8765). CPU only.
$root = $PSScriptRoot
$srv = "$root\llm\bin\llama-server.exe"
$cores = [Environment]::ProcessorCount
Start-Process $srv -WindowStyle Minimized -ArgumentList "-m `"$root\llm\models\Qwen3-4B-Q4_K_M.gguf`" --port 8081 -c 4096 -t $([math]::Max(4,$cores/2)) --jinja --reasoning-budget 0"
Start-Process $srv -WindowStyle Minimized -ArgumentList "-m `"$root\llm\models\Qwen3-8B-Q4_K_M.gguf`" --port 8082 -c 4096 -t $cores --jinja"
Set-Location "$root\companion"
python -m uvicorn server:app --host 127.0.0.1 --port 8765

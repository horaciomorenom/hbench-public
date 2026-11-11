# hbench on Windows (WSL2), e.g. a laptop with an NVIDIA GPU

hbench's scripts need a Unix environment, so on Windows it runs inside **WSL2** (a Linux VM built into Windows 10/11).
The NVIDIA GPU works inside WSL2, so the model server can run there too, or natively on Windows (Ollama, LM Studio).
The web UI opens in your normal Windows browser.

## 1. WSL2 and the GPU
1. In PowerShell **as administrator**: `wsl --install -d Ubuntu`, reboot, and create your Linux user when Ubuntu opens.
2. Keep the normal **Windows** NVIDIA driver up to date (GeForce/Studio driver from NVIDIA or the laptop maker).
   Do not install an NVIDIA driver inside Ubuntu: WSL2 uses the Windows one.
3. In Ubuntu, `nvidia-smi` should list the GPU and its memory.

Optional, in `C:\Users\<you>\.wslconfig` (then `wsl --shutdown` in PowerShell and reopen Ubuntu):
```ini
[wsl2]
memory=24GB                 # RAM for the Linux VM (default: half of the machine's)
networkingMode=mirrored     # Windows 11 22H2+: WSL and Windows share 127.0.0.1 (needed to reach Windows-side servers)
```

## 2. Tools in Ubuntu
```bash
sudo apt update && sudo apt install -y git curl python3-venv python3-pip build-essential cmake
# long tier (the pi agent needs Node 20+):
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
sudo npm install -g @earendil-works/pi-coding-agent
# judge packets as PDF (optional):
sudo apt install -y pandoc && wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
  && sudo apt install -y ./google-chrome-stable_current_amd64.deb
```

## 3. hbench
Put it in the Linux home folder (`~/hbench`), not under `/mnt/c/...`: Windows folders are slow from WSL, and paths with
spaces break the job queue. Then follow the README quickstart (`python3 -m venv .venv`, ..., `./fast.sh mock`).

Start the UI in Ubuntu with `python3 web/app.py` and open http://127.0.0.1:8090 in the Windows browser.

## 4. The model server: two ways
**A. Inside WSL** (llama.cpp or vLLM with CUDA); best performance and hbench can start and stop it.
Install the CUDA toolkit for WSL-Ubuntu from NVIDIA's site (the "WSL-Ubuntu" option, not the generic Linux one, so
it doesn't bring a driver), then build llama.cpp with `-DGGML_CUDA=ON` as in [BACKENDS.md](BACKENDS.md). Keep the
model files in the Linux home folder too.

**B. On Windows** (Ollama for Windows, LM Studio): an external server. With `networkingMode=mirrored`, use
`"base_url": "http://127.0.0.1:11434/v1"` (Ollama) or `:1234` (LM Studio). Without mirrored networking, the Windows
side is at the address `ip route show default | awk '{print $3}'` prints, and the server must listen on all
interfaces (Ollama: set the Windows environment variable `OLLAMA_HOST=0.0.0.0`; LM Studio: "serve on local network").

## 5. Sizing on a laptop GPU
Laptop GPUs have 8-16 GB of memory. Whole-model-on-GPU guide for 4-bit quantizations: 8 GB fits about 8B parameters
with a 32K context, 12 GB about 14B, 16 GB about 20B dense models or a 30B mixture-of-experts with part of the experts
on the CPU (llama.cpp `--n-cpu-moe`). Watch `nvidia-smi` while a run is going.

## 6. What works differently on WSL
- **Sleep**: hbench can't keep Windows awake. For overnight queues, plug in and set Settings > System > Power >
  "When plugged in, put my device to sleep after" to Never (and the lid action to "Do nothing" if you close it).
- **Memory meter**: shows the WSL VM's RAM, not GPU memory.
- Everything else (queue, pause, UI, PDFs) is the same as on Linux.

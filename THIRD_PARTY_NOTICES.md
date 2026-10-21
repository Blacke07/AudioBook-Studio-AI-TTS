# Third-party components

This project's MIT license does not relicense third-party software or models. Preserve their notices
when redistributing. `manifest.json` pins release versions, URLs and hashes rather than mutable latest tags.

| Component | License / source | Distribution |
| --- | --- | --- |
| qwentts.cpp, ggml and native dependencies | MIT; included in `licenses/` and native source archive | Engine binaries and CUDA backend included |
| Qwen3-TTS GGUF | Apache-2.0, [model card](https://huggingface.co/CC-TM/Qwen3-TTS-GGUF) | Downloaded or imported by setup |
| Gemma 4 12B (Standard), Gemma 4 E4B QAT (Compact) | Apache-2.0, [Google license page](https://ai.google.dev/gemma/apache_2) | Exact Ollama manifest/blobs of the chosen model set downloaded or imported |
| NVIDIA CUDA 12.8 runtime, cuBLAS, cuBLAS Lt | [CUDA 12.8 EULA](https://docs.nvidia.com/cuda/archive/12.8.0/eula/index.html); notice included | Only runtime DLLs in a private app folder; no development SDK |
| Microsoft Visual C++ runtime | [Microsoft redistribution terms](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170) | App-local VC142 redistributable DLLs, not a compiler |
| Microsoft WebView2 SDK 1.0.4258.31 | Microsoft BSD-style notice in `licenses/WebView2.txt`; [official NuGet package](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.4258.31) | Three pinned x64/.NET Framework redistributable DLLs, about 0.9 MiB total; no SDK tools or WPF assembly |
| Microsoft Edge WebView2 Evergreen Runtime | [Microsoft distribution documentation and runtime terms](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution) | Shared Microsoft runtime; setup offers the signed Microsoft bootstrapper only if missing, with explicit consent; not removed by this uninstaller |
| Python build standalone / CPython | CPython/PSF and bundled notices; [upstream](https://github.com/astral-sh/python-build-standalone) | Full runtime archive downloaded; its licenses retained |
| FFmpeg Gyan essentials build | GPL; [build/source information](https://www.gyan.dev/ffmpeg/builds/), [FFmpeg legal](https://ffmpeg.org/legal.html) | Downloaded from upstream; supplied notices copied to `licenses/ffmpeg` |
| Ollama | MIT and bundled third-party notices; [source](https://github.com/ollama/ollama) | Portable upstream archive downloaded with notices intact |
| Python packages | Individual licenses in installed wheel metadata | Pinned hashed wheels installed from `requirements.lock` |
| Pillow 12.3.0 | MIT-CMU; exact notice in `licenses/Pillow-MIT-CMU.txt` | Pinned Windows CPython 3.12 wheel installed by setup; used by optional video rendering |

Gemma 4 uses Apache-2.0. Google's [legacy Gemma terms](https://ai.google.dev/gemma/terms) explicitly direct
Gemma 4 users to its Apache license; do not substitute an older Gemma model's terms for this pinned model.
The exact pinned Gemma license blob is also included in `licenses/Gemma4-Apache-2.0.txt`; both pinned Gemma models
carry this same license blob (identical SHA-256).

The native engine's upstream copyright refers historically to "omnivoice.cpp authors". This is retained
attribution; the OmniVoice app, environment and model are not installed or required.

Video rendering uses the Windows-provided Segoe UI and Georgia fonts. This project does not redistribute
those fonts. Preserve the Pillow wheel's bundled license notices as well as the included upstream license.

The CUDA DLLs are shipped for this application's GPU inference, inside its own private folder. The CUDA
EULA includes redistribution conditions and a Windows redistributable list. Anyone publishing modified
builds must check the license for the exact runtime version being distributed. Microsoft runtime
redistribution likewise remains subject to Microsoft's license, not this app's MIT license.

This installer does not embed or mirror the FFmpeg, Python, Ollama or model download archives. If you
choose to redistribute those archives yourself, preserve the upstream notices and satisfy their
corresponding source/redistribution obligations. The native source archive accompanies this release;
it does not replace FFmpeg's corresponding source.

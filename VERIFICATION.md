# Compatibility and validation

AudioBook Studio runs locally on Windows 10/11 x64 with an AVX2-capable CPU and an NVIDIA GPU.
The native engine targets CUDA architecture 8.9, with PTX for driver JIT. NVIDIA driver 570.65 or newer is required.

| Model set | VRAM | Status |
| --- | --- | --- |
| Standard | At least 12 GB | Tested on RTX 4080 Laptop, 12 GB |
| Compact | At least 8 GB | Experimental; real-model measurements are pending |

Earlier GPU architectures are not supported by this version. Other physical GPUs have not been tested.
See [NVIDIA's compute capability list](https://developer.nvidia.com/cuda/gpus) for architecture mappings.

## Checks performed

- Application, installer, uninstaller, archive validation and UI helper tests.
- Local server Host/Origin restrictions, model hashes, safe archive extraction and process ownership.
- Native Base fixed-voice, Voice Design and CustomVoice synthesis on RTX 4080 Laptop.
- CPU and CUDA speaker encoders returned finite 2048-dimensional vectors with matching results.
- The 145 audited CUDA fatbinary blocks contain native images and PTX at 8.9.
- Installer resources, embedded payload, public source contents and distribution SHA-256 checksums.

To run the source tests and reproduce a Windows build, see [docs/BUILD.md](docs/BUILD.md).

## Limits

The installer is unsigned. Installation on a clean Windows system and uninstallation of a real
installation still require validation. Compact has not been measured for VRAM use, speed, dialogue
accuracy or audition quality on an 8 GB card.

Automatic tests do not certify voice quality or correct dialogue attribution. Review uncertain speaker
assignments and listen to important passages before exporting a complete audiobook.

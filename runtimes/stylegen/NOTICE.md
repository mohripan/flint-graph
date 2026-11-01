# Trainer provenance

The flow-matching objective, Flux2 latent normalization and LoRA target-module
selection follow Hugging Face Diffusers' FLUX.2 klein DreamBooth example:

https://github.com/huggingface/diffusers/blob/e04f0c5f24392fcd34b32d18d0ce03668f9bcd50/examples/dreambooth/train_dreambooth_lora_flux2_klein.py

Upstream is Copyright 2025 The HuggingFace Team, Apache License 2.0:
https://github.com/huggingface/diffusers/blob/e04f0c5f24392fcd34b32d18d0ce03668f9bcd50/LICENSE

FlintGraph implements a bounded private training child with staged text/VAE
caches, rank four, uniform schedule sampling and no checkpoint resume or model
upload. The upstream example is documentation, not downloaded/executed code.
The isolated dependency lock pins the libraries actually used. Base-model
weights must match the existing verified FLUX.2 klein 4B manifest. Training data
rights and the approved dataset are recorded separately; no blanket license for
user-trained adapters is asserted here.

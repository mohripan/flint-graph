"""Reference-image conditioning using the installed klein inference convention."""


def training_inputs(noisy, reference):
    import torch
    from diffusers import Flux2KleinPipeline

    target = Flux2KleinPipeline._pack_latents(noisy)
    context = Flux2KleinPipeline._pack_latents(reference.detach())
    ids = torch.cat(
        [
            Flux2KleinPipeline._prepare_latent_ids(noisy),
            Flux2KleinPipeline._prepare_image_ids([reference]),
        ],
        dim=1,
    ).to(noisy.device)
    return torch.cat([target, context], dim=1), ids


def target_prediction(prediction, target):
    from diffusers import Flux2KleinPipeline

    count = target.shape[-2] * target.shape[-1]
    ids = Flux2KleinPipeline._prepare_latent_ids(target).to(target.device)
    return Flux2KleinPipeline._unpack_latents_with_ids(prediction[:, :count], ids)

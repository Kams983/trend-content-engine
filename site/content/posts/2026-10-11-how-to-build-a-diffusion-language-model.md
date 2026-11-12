---
title: "How to build a diffusion language model"
description: "A walkthrough of building a diffusion language model, alongside papers on a tendon-driven robot hand, deformable-object dynamics and what text alone can teach a model about language."
date: 2026-10-11T21:04:04.521310+00:00
slug: "2026-10-11-how-to-build-a-diffusion-language-model"
topic_id: 1
ai_assisted: true
tags:
  - "hackernews"
  - "cs-ro"
  - "cs-ai"
  - "cs-lg"
  - "arxiv"
  - "cs-cl"
sources:
  - title: "How to build a diffusion language model"
    url: "https://kuleshov-group.github.io/blog/blog/2026/how-to-build-a-diffusion-language-model/"
    source: "hackernews"
  - title: "Continuous Diffusion Language Models (CDLM's)"
    url: "https://sander.ai/2026/08/24/continuous-dlms.html"
    source: "hackernews"
  - title: "Aero Hand Open: A Simulation-Ready Tendon-Driven Hand for Dexterous Manipulation Learning"
    url: "http://arxiv.org/abs/2608.28578v1"
    source: "arxiv"
  - title: "ChainSplat: A Physics-Inspired Screw-Theoretic Model for Learning Deformable Linear Object Dynamics from Multi-View RGB Videos"
    url: "http://arxiv.org/abs/2608.28570v1"
    source: "arxiv"
  - title: "A Formal Limitation on Learning Human Language From Textual Corpora"
    url: "http://arxiv.org/abs/2608.28560v1"
    source: "arxiv"
  - title: "Video Generative Models as Geometry Learner"
    url: "http://arxiv.org/abs/2608.28549v1"
    source: "arxiv"
  - title: "DARTS: Decoder-Aware Representation Tuning via Surgery for Model Merging"
    url: "http://arxiv.org/abs/2608.28547v1"
    source: "arxiv"
  - title: "InstructMesh: Selective Refinement of Generative 3D Models for Fabrication"
    url: "http://arxiv.org/abs/2608.28534v1"
    source: "arxiv"
  - title: "Learning the Target Priors Before Image Translation: A Decoupled Training Paradigm for Cross-Modal Image Translation in Remote Sensing"
    url: "http://arxiv.org/abs/2608.28517v1"
    source: "arxiv"
  - title: "Training Communication-Efficient Mixture-of-Experts Language Models with Layer Re-Configuration"
    url: "http://arxiv.org/abs/2608.28511v1"
    source: "arxiv"
  - title: "Phoneme- and Word-Level Metrics Using Self-Supervised Speech Representations for Forced Alignment Evaluation"
    url: "http://arxiv.org/abs/2608.28508v1"
    source: "arxiv"
  - title: "AcrossVAM1.0: Particle World Modeling for Text-Assisted Robot Video Prediction"
    url: "http://arxiv.org/abs/2608.28491v1"
    source: "arxiv"
---
How to build a diffusion language model was reported by hackernews (https://kuleshov-group.github.io/blog/blog/2026/how-to-build-a-diffusion-language-model/). Continuous Diffusion Language Models (CDLM's) was reported by hackernews (https://sander.ai/2026/08/24/continuous-dlms.html). Aero Hand Open: A Simulation-Ready Tendon-Driven Hand for Dexterous Manipulation Learning was reported by arxiv (http://arxiv.org/abs/2608.28578v1). Tendon-driven hands are anthropomorphic, and moving the actuators off the joints is what makes a hand of this capability affordable to build. Two effects produce that saving. Routing force through a cable removes the requirement that a motor fit inside the joint it drives, so smaller and cheaper motors suffice, and one motor can drive several joints through a single cable, so fewer motors are needed. They are also harder. ChainSplat: A Physics-Inspired Screw-Theoretic Model for Learning Deformable Linear Object Dynamics from Multi-View RGB Videos was reported by arxiv (http://arxiv.org/abs/2608.28570v1). Identifying the underlying dynamics and 3D geometry of deformable linear objects (DLOs), such as cables, ropes, and hoses, is essential for accurate robotic manipulation, but remains challenging due to their high-dimensional configuration spaces and diverse behaviors arising from varying material properties. Existing methods often rely on multi-stage pipelines and auxiliary depth inputs, which are prone to errors under dynamic interactions, while their high-dimensional state representations make model-based control computationally expensive. A Formal Limitation on Learning Human Language From Textual Corpora was reported by arxiv (http://arxiv.org/abs/2608.28560v1). Can a listener recover what a speaker means from the form of an utterance alone? We answer this question information-theoretically, and for a listener given by any featurizer of text, including the hidden states of contemporary large language models. Modeling language use as a joint distribution over meanings, contexts, and utterances, we derive upper bounds on the probability that a decoder recovers a speaker's intended meaning from a representation of. Video Generative Models as Geometry Learner was reported by arxiv (http://arxiv.org/abs/2608.28549v1). Recent generative approaches to geometry estimation adapt pretrained image diffusion models and treat the task as image-conditioned generation. Leveraging off-the-shelf image diffusion models, they either (i) train task-specific geometry models (for depth and surface normal estimation) independently, losing the opportunity of exploring the intrinsic correlation of these geometric targets, or (ii) jointly fine-tune modified image diffusion backbones (e.g., altered self-attention), which typically demands substantial labeled data. To overcome these limitations. DARTS: Decoder-Aware Representation Tuning via Surgery for Model Merging was reported by arxiv (http://arxiv.org/abs/2608.28547v1). Model merging combines multiple task-specific fine-tuned LLMs into a single multi-task model without additional training. However, merged models are known to suffer from representation bias: systematic drift between the merged model's hidden states and those of each individual source model. Prior work (Yang et al., 2024a) study and mitigate this bias for encoder-based vision models using a lightweight correction module trained with L1 loss. However, such bias is not studied. InstructMesh: Selective Refinement of Generative 3D Models for Fabrication was reported by arxiv (http://arxiv.org/abs/2608.28534v1). Recent advances in generative AI allow users to create 3D models from text or images. However, these models prioritize visual plausibility over geometric accuracy, often generating results with flaws that compromise their intended use post-fabrication. We present InstructMesh, an interactive post-generation refinement tool that enables selective repair of generative 3D models through region selection and targeted operations, such as opening or sealing voids, or adjusting local thickness. Users can invoke. Learning the Target Priors Before Image Translation: A Decoupled Training Paradigm for Cross-Modal Image Translation in Remote Sensing was reported by arxiv (http://arxiv.org/abs/2608.28517v1). Cross-modal image translation in remote sensing must preserve source-observed content while matching the target-domain distribution. Existing methods jointly learn the target prior and cross-modal dependence from scarce paired data, overlooking a key asymmetry: only the latter intrinsically requires cross-modal correspondence. We formalize this distinction through conditional-score and denoising-risk analyses and propose Learning the Target Priors Before Image Translation (LTP-BIT), a prior-first paradigm that decouples the two learning tasks. LTP-BIT first. Training Communication-Efficient Mixture-of-Experts Language Models with Layer Re-Configuration was reported by arxiv (http://arxiv.org/abs/2608.28511v1). When training Mixture-of-Experts (MoE) language models with expert parallelism, all-to-all token dispatch and combine collectives can consume a substantial fraction of end-to-end training time. In this work, we study communication-efficient MoE models (CE-MoE), in which we adopt a heterogeneous layer pattern that decouples token-mixing and channel-mixing depth. Compared to conventional models which interleave MoE layers after each token-mixing layer (e.g., attention, Mamba-2), CE-MoE models concentrate expert capacity in a select. Phoneme- and Word-Level Metrics Using Self-Supervised Speech Representations for Forced Alignment Evaluation was reported by arxiv (http://arxiv.org/abs/2608.28508v1). Forced alignment evaluation typically requires manually annotated timestamps, limiting large-scale and multilingual analysis. We introduce two corpus-level metrics based on self-supervised (SSL) speech representations for reference-free forced alignment evaluation: Phoneme-Cluster Mutual Information (PCMI) and Word Acoustic Consistency Score (WACS). PCMI measures agreement between aligned phoneme labels and clusters induced from SSL-speech representations, while WACS measures consistency of repeated word realizations using dynamic time warping similarity between word representation sequences. Using. AcrossVAM1.0: Particle World Modeling for.

## Sources

1. [How to build a diffusion language model](https://kuleshov-group.github.io/blog/blog/2026/how-to-build-a-diffusion-language-model/) — hackernews
2. [Continuous Diffusion Language Models (CDLM's)](https://sander.ai/2026/08/24/continuous-dlms.html) — hackernews
3. [Aero Hand Open: A Simulation-Ready Tendon-Driven Hand for Dexterous Manipulation Learning](http://arxiv.org/abs/2608.28578v1) — arxiv
4. [ChainSplat: A Physics-Inspired Screw-Theoretic Model for Learning Deformable Linear Object Dynamics from Multi-View RGB Videos](http://arxiv.org/abs/2608.28570v1) — arxiv
5. [A Formal Limitation on Learning Human Language From Textual Corpora](http://arxiv.org/abs/2608.28560v1) — arxiv
6. [Video Generative Models as Geometry Learner](http://arxiv.org/abs/2608.28549v1) — arxiv
7. [DARTS: Decoder-Aware Representation Tuning via Surgery for Model Merging](http://arxiv.org/abs/2608.28547v1) — arxiv
8. [InstructMesh: Selective Refinement of Generative 3D Models for Fabrication](http://arxiv.org/abs/2608.28534v1) — arxiv
9. [Learning the Target Priors Before Image Translation: A Decoupled Training Paradigm for Cross-Modal Image Translation in Remote Sensing](http://arxiv.org/abs/2608.28517v1) — arxiv
10. [Training Communication-Efficient Mixture-of-Experts Language Models with Layer Re-Configuration](http://arxiv.org/abs/2608.28511v1) — arxiv
11. [Phoneme- and Word-Level Metrics Using Self-Supervised Speech Representations for Forced Alignment Evaluation](http://arxiv.org/abs/2608.28508v1) — arxiv
12. [AcrossVAM1.0: Particle World Modeling for Text-Assisted Robot Video Prediction](http://arxiv.org/abs/2608.28491v1) — arxiv
